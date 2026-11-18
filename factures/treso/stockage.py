"""Tables de la trésorerie dans la base SQLite de l'application.

- mandat : période de gestion (ex. 2025 - 2026) ;
- catégorie : Événements, Fonctionnement… communes à tous les mandats ; « hors compte de résultat » possible ;
- classeur : rattaché à un mandat et à une catégorie (Escape Game, Galette des Rois…) ;
- opération : ligne du relevé (montant < 0 = charge, > 0 = produit), classée dans un classeur ou « à classer » ;
- justificatif : un fichier gardé dans la base, ou un lien vers une note de frais / une facture de l'appli
  (son PDF est refait à chaque ouverture, donc toujours à jour).

Les montants sont gardés en centimes (nombres entiers) : aucune erreur d'arrondi dans les totaux.
"""
import hashlib
import sqlite3
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from ..stockage import ErreurDonnees
from .releve import normaliser

SCHEMA = """
CREATE TABLE IF NOT EXISTS treso_mandats (
    id INTEGER PRIMARY KEY,
    nom TEXT NOT NULL UNIQUE,
    debut TEXT NOT NULL,
    fin TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS treso_categories (
    id INTEGER PRIMARY KEY,
    nom TEXT NOT NULL UNIQUE,
    hors_cr INTEGER NOT NULL DEFAULT 0,
    ordre INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS treso_classeurs (
    id INTEGER PRIMARY KEY,
    mandat_id INTEGER NOT NULL,
    categorie_id INTEGER NOT NULL,
    nom TEXT NOT NULL,
    UNIQUE (mandat_id, nom)
);
CREATE TABLE IF NOT EXISTS treso_operations (
    id INTEGER PRIMARY KEY,
    mandat_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    libelle TEXT NOT NULL,
    nature TEXT NOT NULL DEFAULT '',
    montant INTEGER NOT NULL,              -- en centimes
    classeur_id INTEGER,                   -- vide = à classer
    commentaire TEXT NOT NULL DEFAULT '',
    empreinte TEXT NOT NULL UNIQUE,        -- évite les doublons quand on réimporte un relevé
    cree_le TEXT NOT NULL,
    modifie_par TEXT,
    modifie_le TEXT
);
CREATE INDEX IF NOT EXISTS treso_operations_mandat ON treso_operations (mandat_id, date);
CREATE TABLE IF NOT EXISTS treso_justificatifs (
    id INTEGER PRIMARY KEY,
    operation_id INTEGER NOT NULL,
    nom TEXT NOT NULL,
    type TEXT NOT NULL,                    -- type MIME du fichier, ou application/pdf pour un lien
    contenu BLOB,                          -- vide pour un lien
    lien_type TEXT,                        -- « ndf » ou « facture »
    lien_id INTEGER,
    chemin_nextcloud TEXT,                 -- copie envoyée sur Nextcloud, si configuré
    cree_par TEXT,
    cree_le TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS treso_justificatifs_operation ON treso_justificatifs (operation_id);
CREATE INDEX IF NOT EXISTS treso_justificatifs_lien ON treso_justificatifs (lien_type, lien_id);
"""

# Données de départ d'une base neuve (les mêmes qu'AML Trésorerie)
CATEGORIES_DEFAUT = [("Événements", False), ("Fonctionnement", False), ("Local", False), ("Non Catégorisé", False),
                     ("Partenariats", False), ("Reliquats", False), ("Hors Compte de Résultats", True)]
MANDAT_DEFAUT = ("2025 - 2026", "2025-09-01", "2026-08-31")
CLASSEURS_DEFAUT = [
    ("Événements", "Escape Game"), ("Événements", "Gala Fin d'année AML"), ("Événements", "Galette des Rois"),
    ("Événements", "Remise des Diplômes"), ("Événements", "Vente de crèpes"), ("Événements", "Vente de panini"),
    ("Fonctionnement", "Adhésion"), ("Fonctionnement", "Adhésions Organismes Extérieurs"),
    ("Fonctionnement", "Assurance"), ("Fonctionnement", "Dons"),
    ("Fonctionnement", "Frais / Cotisations / Abonnements"), ("Fonctionnement", "Subventions"),
    ("Fonctionnement", "Vol"), ("Local", "Matériel"), ("Local", "Pharmacie"), ("Local", "Vente au local"),
    ("Non Catégorisé", "Retrait especes"), ("Partenariats", "Pulls du bureau"), ("Reliquats", "Adhésions"),
    ("Reliquats", "Gala N-1"), ("Reliquats", "Vente au local N-1"), ("Reliquats", "Vente bubble tea"),
    ("Hors Compte de Résultats", "Mouvement interne"),
]
LIENS = ("ndf", "facture")


def centimes(montant):
    return int((Decimal(str(montant)) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def euros(centimes_):
    return round(centimes_ / 100, 2)


def _maintenant():
    return datetime.now().isoformat(timespec="seconds")


def _cle_tri(nom):
    return normaliser(nom)


class Tresorerie:
    def __init__(self, stockage):
        self._db = stockage._db  # même base et mêmes connexions que le reste de l'application
        with self._db() as db:
            db.executescript(SCHEMA)
            if db.execute("SELECT 1 FROM treso_categories LIMIT 1").fetchone() is None:
                self._donnees_initiales(db)

    @staticmethod
    def _donnees_initiales(db):
        for ordre, (nom, hors) in enumerate(CATEGORIES_DEFAUT, 1):
            db.execute("INSERT INTO treso_categories (nom, hors_cr, ordre) VALUES (?, ?, ?)", (nom, int(hors), ordre))
        mandat = db.execute("INSERT INTO treso_mandats (nom, debut, fin) VALUES (?, ?, ?)", MANDAT_DEFAUT).lastrowid
        for categorie, nom in CLASSEURS_DEFAUT:
            db.execute("INSERT INTO treso_classeurs (mandat_id, categorie_id, nom) "
                       "SELECT ?, id, ? FROM treso_categories WHERE nom = ?", (mandat, nom, categorie))

    # -- mandats, catégories, classeurs -----------------------------------------
    def mandats(self):
        with self._db() as db:
            rows = db.execute("SELECT id, nom, debut, fin FROM treso_mandats ORDER BY debut DESC, id DESC").fetchall()
        return [dict(r) for r in rows]

    def mandat(self, id_):
        with self._db() as db:
            row = db.execute("SELECT id, nom, debut, fin FROM treso_mandats WHERE id = ?", (id_,)).fetchone()
        return dict(row) if row else None

    def creer_mandat(self, nom, debut, fin, copier_de=None):
        """Nouveau mandat ; `copier_de` : mandat dont on reprend les classeurs."""
        try:
            with self._db() as db:
                id_ = db.execute("INSERT INTO treso_mandats (nom, debut, fin) VALUES (?, ?, ?)",
                                 (nom, debut, fin)).lastrowid
                if copier_de:
                    db.execute("INSERT INTO treso_classeurs (mandat_id, categorie_id, nom) "
                               "SELECT ?, categorie_id, nom FROM treso_classeurs WHERE mandat_id = ?", (id_, copier_de))
        except sqlite3.IntegrityError as exc:
            raise ErreurDonnees(f"Le mandat « {nom} » existe déjà.") from exc
        return id_

    def categories(self):
        with self._db() as db:
            rows = db.execute("SELECT id, nom, hors_cr FROM treso_categories ORDER BY ordre, id").fetchall()
        return [{"id": r["id"], "nom": r["nom"], "hors_cr": bool(r["hors_cr"])} for r in rows]

    def classeurs(self, mandat_id):
        """Classeurs du mandat, rangés par catégorie puis par nom, avec leur nombre de transactions."""
        with self._db() as db:
            rows = db.execute(
                "SELECT cl.id, cl.nom, c.id AS categorie_id, c.nom AS categorie_nom, c.ordre, "
                "(SELECT COUNT(*) FROM treso_operations o WHERE o.classeur_id = cl.id) AS nb "
                "FROM treso_classeurs cl JOIN treso_categories c ON c.id = cl.categorie_id "
                "WHERE cl.mandat_id = ?", (mandat_id,)).fetchall()
        rows = sorted(rows, key=lambda r: (r["ordre"], _cle_tri(r["nom"])))
        return [{k: r[k] for k in ("id", "nom", "categorie_id", "categorie_nom", "nb")} for r in rows]

    def creer_classeur(self, mandat_id, categorie_id, nom):
        try:
            with self._db() as db:
                if db.execute("SELECT 1 FROM treso_mandats WHERE id = ?", (mandat_id,)).fetchone() is None:
                    raise ErreurDonnees("Mandat introuvable.")
                if db.execute("SELECT 1 FROM treso_categories WHERE id = ?", (categorie_id,)).fetchone() is None:
                    raise ErreurDonnees("Catégorie introuvable.")
                return db.execute("INSERT INTO treso_classeurs (mandat_id, categorie_id, nom) VALUES (?, ?, ?)",
                                  (mandat_id, categorie_id, nom)).lastrowid
        except sqlite3.IntegrityError as exc:
            raise ErreurDonnees(f"Le classeur « {nom} » existe déjà dans ce mandat.") from exc

    def supprimer_classeur(self, id_):
        with self._db() as db:
            if db.execute("SELECT 1 FROM treso_operations WHERE classeur_id = ? LIMIT 1", (id_,)).fetchone():
                raise ErreurDonnees("Ce classeur contient des transactions : reclassez-les avant de le supprimer.")
            if not db.execute("DELETE FROM treso_classeurs WHERE id = ?", (id_,)).rowcount:
                raise ErreurDonnees("Classeur introuvable.")

    # -- transactions ------------------------------------------------------------
    def operations(self, mandat_id, mois=None, classeur_id=None, a_classer=False):
        """Transactions du mandat (les plus récentes d'abord), avec leurs justificatifs."""
        sql = ("SELECT id, date, libelle, nature, montant, classeur_id, commentaire FROM treso_operations "
               "WHERE mandat_id = ?")
        params = [mandat_id]
        if classeur_id:
            sql += " AND classeur_id = ?"
            params.append(classeur_id)
        if mois:
            sql += " AND substr(date, 1, 7) = ?"
            params.append(mois)
        if a_classer:
            sql += " AND classeur_id IS NULL"
        with self._db() as db:
            rows = db.execute(sql + " ORDER BY date DESC, id DESC", params).fetchall()
            justificatifs = {}
            for j in db.execute("SELECT j.id, j.operation_id, j.nom, j.lien_type, j.lien_id FROM treso_justificatifs j "
                                "JOIN treso_operations o ON o.id = j.operation_id WHERE o.mandat_id = ? ORDER BY j.id",
                                (mandat_id,)):
                justificatifs.setdefault(j["operation_id"], []).append(
                    {"id": j["id"], "nom": j["nom"], "lien_type": j["lien_type"], "lien_id": j["lien_id"]})
        return [{**dict(r), "montant": euros(r["montant"]), "justificatifs": justificatifs.get(r["id"], [])}
                for r in rows]

    def operation(self, id_):
        """Une transaction avec les noms de son mandat, de sa catégorie et de son classeur, ou None."""
        with self._db() as db:
            row = db.execute(
                "SELECT o.*, m.nom AS mandat, c.nom AS categorie, cl.nom AS classeur FROM treso_operations o "
                "JOIN treso_mandats m ON m.id = o.mandat_id LEFT JOIN treso_classeurs cl ON cl.id = o.classeur_id "
                "LEFT JOIN treso_categories c ON c.id = cl.categorie_id WHERE o.id = ?", (id_,)).fetchone()
        if row is None:
            return None
        return {**{k: row[k] for k in row.keys() if k != "empreinte"}, "montant": euros(row["montant"])}

    def importer(self, mandat_id, lignes):
        """Ajoute les lignes d'un relevé ; réimporter le même fichier ne crée pas de doublon.
        Deux lignes identiques le même jour restent deux transactions. Renvoie le nombre ajouté."""
        quand, vues, ajoutees = _maintenant(), {}, 0
        with self._db() as db:
            if db.execute("SELECT 1 FROM treso_mandats WHERE id = ?", (mandat_id,)).fetchone() is None:
                raise ErreurDonnees("Mandat introuvable.")
            for l in lignes:
                base = f"{mandat_id}|{l.date}|{l.libelle}|{l.montant}"
                vues[base] = vues.get(base, 0) + 1
                empreinte = hashlib.sha256(f"{base}|{vues[base]}".encode()).hexdigest()
                ajoutees += db.execute(
                    "INSERT OR IGNORE INTO treso_operations (mandat_id, date, libelle, nature, montant, empreinte, "
                    "cree_le) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (mandat_id, l.date, l.libelle, l.nature, centimes(l.montant), empreinte, quand)).rowcount
        return ajoutees

    def modifier_operation(self, id_, classeur_id, commentaire, libelle, auteur):
        """Classe la transaction (classeur du même mandat, ou aucun) ; un motif vide garde l'ancien."""
        with self._db() as db:
            op = db.execute("SELECT mandat_id FROM treso_operations WHERE id = ?", (id_,)).fetchone()
            if op is None:
                raise ErreurDonnees("Transaction introuvable.")
            if classeur_id is not None and db.execute(
                    "SELECT 1 FROM treso_classeurs WHERE id = ? AND mandat_id = ?",
                    (classeur_id, op["mandat_id"])).fetchone() is None:
                raise ErreurDonnees("Ce classeur n'appartient pas au mandat de la transaction.")
            db.execute("UPDATE treso_operations SET classeur_id = ?, commentaire = ?, "
                       "libelle = COALESCE(NULLIF(?, ''), libelle), modifie_par = ?, modifie_le = ? WHERE id = ?",
                       (classeur_id, commentaire, libelle, auteur, _maintenant(), id_))

    def supprimer_operation(self, id_):
        with self._db() as db:
            db.execute("DELETE FROM treso_justificatifs WHERE operation_id = ?", (id_,))
            if not db.execute("DELETE FROM treso_operations WHERE id = ?", (id_,)).rowcount:
                raise ErreurDonnees("Transaction introuvable.")

    # -- justificatifs -------------------------------------------------------------
    def ajouter_justificatif(self, operation_id, nom, type_, contenu=None, lien_type=None, lien_id=None,
                             auteur=None, chemin_nextcloud=None):
        with self._db() as db:
            if db.execute("SELECT 1 FROM treso_operations WHERE id = ?", (operation_id,)).fetchone() is None:
                raise ErreurDonnees("Transaction introuvable.")
            if lien_type and db.execute(
                    "SELECT 1 FROM treso_justificatifs WHERE operation_id = ? AND lien_type = ? AND lien_id = ?",
                    (operation_id, lien_type, lien_id)).fetchone():
                raise ErreurDonnees("Ce document est déjà joint à cette transaction.")
            return db.execute(
                "INSERT INTO treso_justificatifs (operation_id, nom, type, contenu, lien_type, lien_id, "
                "chemin_nextcloud, cree_par, cree_le) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (operation_id, nom[:200], type_, contenu, lien_type, lien_id, chemin_nextcloud, auteur,
                 _maintenant())).lastrowid

    def justificatif(self, id_):
        with self._db() as db:
            row = db.execute("SELECT * FROM treso_justificatifs WHERE id = ?", (id_,)).fetchone()
        return dict(row) if row else None

    def supprimer_justificatif(self, id_):
        with self._db() as db:
            if not db.execute("DELETE FROM treso_justificatifs WHERE id = ?", (id_,)).rowcount:
                raise ErreurDonnees("Justificatif introuvable.")

    def retirer_liens(self, lien_type, lien_id):
        """La note de frais ou la facture est supprimée : elle n'est plus jointe à aucune transaction."""
        with self._db() as db:
            db.execute("DELETE FROM treso_justificatifs WHERE lien_type = ? AND lien_id = ?", (lien_type, lien_id))

    def rapprochements(self, lien_type):
        """{id du document: [{date, montant} des transactions où il est joint]} pour les listes NDF et factures."""
        with self._db() as db:
            rows = db.execute("SELECT j.lien_id, o.date, o.montant FROM treso_justificatifs j "
                              "JOIN treso_operations o ON o.id = j.operation_id WHERE j.lien_type = ? "
                              "ORDER BY o.date", (lien_type,)).fetchall()
        liens = {}
        for r in rows:
            liens.setdefault(r["lien_id"], []).append({"date": r["date"], "montant": euros(r["montant"])})
        return liens

    # -- compte de résultat ----------------------------------------------------------
    def compte_resultat(self, mandat_id):
        """Catégorie › classeur, avec charges (< 0), produits (> 0) et balance ; total du compte de résultat,
        bloc « hors compte de résultat », lignes non classées et contrôle avec le solde du relevé."""
        with self._db() as db:
            rows = db.execute(
                "SELECT c.id AS categorie_id, c.nom AS categorie, c.hors_cr, c.ordre, cl.id, cl.nom, "
                "COALESCE(SUM(CASE WHEN o.montant < 0 THEN o.montant END), 0) AS charges, "
                "COALESCE(SUM(CASE WHEN o.montant > 0 THEN o.montant END), 0) AS produits, COUNT(o.id) AS nb "
                "FROM treso_classeurs cl JOIN treso_categories c ON c.id = cl.categorie_id "
                "LEFT JOIN treso_operations o ON o.classeur_id = cl.id WHERE cl.mandat_id = ? GROUP BY cl.id",
                (mandat_id,)).fetchall()
            non_classe = db.execute(
                "SELECT COALESCE(SUM(CASE WHEN montant < 0 THEN montant END), 0) AS charges, "
                "COALESCE(SUM(CASE WHEN montant > 0 THEN montant END), 0) AS produits, COUNT(*) AS nb "
                "FROM treso_operations WHERE mandat_id = ? AND classeur_id IS NULL", (mandat_id,)).fetchone()
            solde = db.execute("SELECT COALESCE(SUM(montant), 0) FROM treso_operations WHERE mandat_id = ?",
                               (mandat_id,)).fetchone()[0]

        categories = {}
        for r in sorted(rows, key=lambda r: (r["ordre"], _cle_tri(r["nom"]))):
            cat = categories.setdefault(r["categorie_id"], {"nom": r["categorie"], "hors_cr": bool(r["hors_cr"]),
                                                            "charges": 0, "produits": 0, "classeurs": []})
            cat["charges"] += r["charges"]
            cat["produits"] += r["produits"]
            cat["classeurs"].append({"id": r["id"], "nom": r["nom"], "charges": r["charges"],
                                     "produits": r["produits"], "nb": r["nb"]})
        totaux = {True: {"charges": 0, "produits": 0}, False: {"charges": 0, "produits": 0}}
        for cat in categories.values():
            totaux[cat["hors_cr"]]["charges"] += cat["charges"]
            totaux[cat["hors_cr"]]["produits"] += cat["produits"]

        def montants(d):
            return {"charges": euros(d["charges"]), "produits": euros(d["produits"]),
                    "balance": euros(d["charges"] + d["produits"])}

        ecart = solde - sum(t["charges"] + t["produits"] for t in totaux.values()) \
            - non_classe["charges"] - non_classe["produits"]
        return {
            "categories": [{"nom": c["nom"], "hors_cr": c["hors_cr"], **montants(c),
                            "classeurs": [{"id": k["id"], "nom": k["nom"], "nb": k["nb"], **montants(k)}
                                          for k in c["classeurs"]]} for c in categories.values()],
            "total_cr": montants(totaux[False]),
            "total_hors_cr": montants(totaux[True]),
            "non_classe": {**montants(non_classe), "nb": non_classe["nb"]},
            "solde_releve": euros(solde),
            "ecart": euros(ecart),  # 0 : tout concorde
        }

    # -- reprise des données d'AML Trésorerie ----------------------------------------
    def reprendre_referentiel(self, donnees):
        """Remplace mandats, catégories et classeurs par ceux exportés d'AML Trésorerie (PostgreSQL),
        en gardant leurs numéros. Refusé s'il y a déjà des transactions."""
        with self._db() as db:
            if db.execute("SELECT 1 FROM treso_operations LIMIT 1").fetchone():
                raise ErreurDonnees("Des transactions existent déjà : reprise refusée.")
            for table in ("treso_classeurs", "treso_mandats", "treso_categories"):
                db.execute(f"DELETE FROM {table}")
            for c in donnees["categories"]:
                db.execute("INSERT INTO treso_categories (id, nom, hors_cr, ordre) VALUES (?, ?, ?, ?)",
                           (c["id"], c["nom"], int(c["hors_cr"]), c["ordre"]))
            for m in donnees["mandats"]:
                db.execute("INSERT INTO treso_mandats (id, nom, debut, fin) VALUES (?, ?, ?, ?)",
                           (m["id"], m["nom"], m["debut"], m["fin"]))
            for cl in donnees["classeurs"]:
                db.execute("INSERT INTO treso_classeurs (id, mandat_id, categorie_id, nom) VALUES (?, ?, ?, ?)",
                           (cl["id"], cl["mandat_id"], cl["categorie_id"], cl["nom"]))
        return {k: len(donnees[k]) for k in ("mandats", "categories", "classeurs")}
