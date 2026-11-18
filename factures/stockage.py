"""Base SQLite de l'application : comptes, réglages Nextcloud, préférences partagées,
devis et factures de l'association, notes de frais et leurs justificatifs.

Les préférences (marge, taxe TPE, arrondi, puis par article : pièces, prix choisi,
catégorie Local) sont communes à tous les membres connectés.
"""
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

from werkzeug.security import check_password_hash, generate_password_hash

SCHEMA = """
CREATE TABLE IF NOT EXISTS utilisateurs (
    nom TEXT PRIMARY KEY,
    mot_de_passe TEXT NOT NULL,
    admin INTEGER NOT NULL DEFAULT 0,
    cree_le TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reglages (
    cle TEXT PRIMARY KEY,
    valeur TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS preferences (
    cle TEXT PRIMARY KEY,
    valeur TEXT NOT NULL,
    modifie_par TEXT,
    modifie_le TEXT
);
-- devis et factures de l'association ; « donnees » : le document complet en JSON
CREATE TABLE IF NOT EXISTS devis_factures (
    id INTEGER PRIMARY KEY,
    type TEXT NOT NULL,
    numero TEXT NOT NULL UNIQUE,
    annee INTEGER NOT NULL,
    rang INTEGER NOT NULL,
    date TEXT NOT NULL,
    client TEXT NOT NULL,
    objet TEXT NOT NULL,
    total_ttc REAL NOT NULL,
    statut TEXT NOT NULL,
    donnees TEXT NOT NULL,
    devis_id INTEGER,
    cree_par TEXT,
    cree_le TEXT NOT NULL,
    modifie_par TEXT,
    modifie_le TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS notes_frais (
    id INTEGER PRIMARY KEY,
    date TEXT NOT NULL,
    personne TEXT NOT NULL,
    objet TEXT NOT NULL,
    total_ttc REAL NOT NULL,
    statut TEXT NOT NULL,
    donnees TEXT NOT NULL,
    signature BLOB,
    cree_par TEXT,
    cree_le TEXT NOT NULL,
    modifie_par TEXT,
    modifie_le TEXT NOT NULL
);
-- images des justificatifs (JPEG) ; note_id vide tant que la note n'est pas enregistrée
CREATE TABLE IF NOT EXISTS justificatifs (
    id INTEGER PRIMARY KEY,
    note_id INTEGER,
    nom TEXT NOT NULL,
    largeur INTEGER NOT NULL,
    hauteur INTEGER NOT NULL,
    contenu BLOB NOT NULL,
    cree_le TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS justificatifs_note ON justificatifs (note_id);
"""

JUSTIFICATIF_ORPHELIN_JOURS = 2  # justificatif envoyé mais jamais rattaché à une note : supprimé après

NOM_VALIDE = re.compile(r"[a-z0-9][a-z0-9._-]{1,31}")
MDP_MIN = 8
# comparé quand le compte n'existe pas, pour que la réponse prenne le même temps
_HASH_FACTICE = generate_password_hash("mot de passe factice")


class ErreurCompte(Exception):
    pass


class ErreurDonnees(Exception):
    """Enregistrement impossible (numéro déjà pris, justificatif introuvable…) : réponse 400."""


def _maintenant():
    return datetime.now().isoformat(timespec="seconds")


def normaliser_nom(nom):
    nom = (nom or "").strip().lower()
    if not NOM_VALIDE.fullmatch(nom):
        raise ErreurCompte("Nom invalide : 2 à 32 caractères parmi a-z, 0-9, « . », « _ », « - ».")
    return nom


def verifier_mot_de_passe(mdp):
    if len(mdp or "") < MDP_MIN:
        raise ErreurCompte(f"Mot de passe trop court ({MDP_MIN} caractères minimum).")


class Stockage:
    def __init__(self, chemin):
        self.chemin = Path(chemin)
        self.chemin.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(SCHEMA)

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.chemin, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:  # valide la transaction, ou l'annule en cas d'erreur
                yield db
        finally:
            db.close()

    # -- comptes ---------------------------------------------------------------
    def utilisateurs(self):
        with self._db() as db:
            rows = db.execute("SELECT nom, admin, cree_le FROM utilisateurs ORDER BY nom").fetchall()
        return [{"nom": r["nom"], "admin": bool(r["admin"]), "cree_le": r["cree_le"]} for r in rows]

    def nb_utilisateurs(self):
        with self._db() as db:
            return db.execute("SELECT COUNT(*) FROM utilisateurs").fetchone()[0]

    def ajouter_utilisateur(self, nom, mot_de_passe, admin=False):
        nom = normaliser_nom(nom)
        verifier_mot_de_passe(mot_de_passe)
        try:
            with self._db() as db:
                db.execute(
                    "INSERT INTO utilisateurs (nom, mot_de_passe, admin, cree_le) VALUES (?, ?, ?, ?)",
                    (nom, generate_password_hash(mot_de_passe), int(admin), _maintenant()),
                )
        except sqlite3.IntegrityError as exc:
            raise ErreurCompte(f"Le compte « {nom} » existe déjà.") from exc
        return nom

    def changer_mot_de_passe(self, nom, mot_de_passe):
        nom = normaliser_nom(nom)
        verifier_mot_de_passe(mot_de_passe)
        with self._db() as db:
            n = db.execute("UPDATE utilisateurs SET mot_de_passe = ? WHERE nom = ?",
                           (generate_password_hash(mot_de_passe), nom)).rowcount
        if not n:
            raise ErreurCompte(f"Compte « {nom} » introuvable.")

    def definir_admin(self, nom, admin):
        nom = normaliser_nom(nom)
        with self._db() as db:
            n = db.execute("UPDATE utilisateurs SET admin = ? WHERE nom = ?", (int(admin), nom)).rowcount
        if not n:
            raise ErreurCompte(f"Compte « {nom} » introuvable.")

    def supprimer_utilisateur(self, nom):
        nom = normaliser_nom(nom)
        with self._db() as db:
            n = db.execute("DELETE FROM utilisateurs WHERE nom = ?", (nom,)).rowcount
        if not n:
            raise ErreurCompte(f"Compte « {nom} » introuvable.")

    def authentifier(self, nom, mot_de_passe):
        """Retourne {"nom", "admin"} si le mot de passe est bon, sinon None."""
        try:
            nom = normaliser_nom(nom)
        except ErreurCompte:
            check_password_hash(_HASH_FACTICE, mot_de_passe or "")
            return None
        with self._db() as db:
            row = db.execute("SELECT nom, mot_de_passe, admin FROM utilisateurs WHERE nom = ?", (nom,)).fetchone()
        if row is None:
            check_password_hash(_HASH_FACTICE, mot_de_passe or "")
            return None
        if not check_password_hash(row["mot_de_passe"], mot_de_passe or ""):
            return None
        return {"nom": row["nom"], "admin": bool(row["admin"])}

    def compte(self, nom):
        with self._db() as db:
            row = db.execute("SELECT nom, admin FROM utilisateurs WHERE nom = ?", (nom,)).fetchone()
        return {"nom": row["nom"], "admin": bool(row["admin"])} if row else None

    # -- réglages (connexion Nextcloud, dossier) -------------------------------
    def reglage(self, cle, defaut=None):
        with self._db() as db:
            row = db.execute("SELECT valeur FROM reglages WHERE cle = ?", (cle,)).fetchone()
        return json.loads(row["valeur"]) if row else defaut

    def definir_reglage(self, cle, valeur):
        with self._db() as db:
            db.execute("INSERT OR REPLACE INTO reglages (cle, valeur) VALUES (?, ?)",
                       (cle, json.dumps(valeur, ensure_ascii=False)))

    # -- préférences partagées -------------------------------------------------
    def preferences(self):
        with self._db() as db:
            rows = db.execute("SELECT cle, valeur FROM preferences").fetchall()
        return {r["cle"]: json.loads(r["valeur"]) for r in rows}

    def definir_preferences(self, valeurs, auteur):
        """`valeurs` : {clé: valeur} ; une valeur None supprime la clé."""
        quand = _maintenant()
        with self._db() as db:
            for cle, valeur in valeurs.items():
                if valeur is None:
                    db.execute("DELETE FROM preferences WHERE cle = ?", (cle,))
                else:
                    db.execute(
                        "INSERT OR REPLACE INTO preferences (cle, valeur, modifie_par, modifie_le) "
                        "VALUES (?, ?, ?, ?)",
                        (cle, json.dumps(valeur, ensure_ascii=False), auteur, quand),
                    )

    # -- devis et factures de l'association -----------------------------------
    def lister_pieces(self):
        """Résumé de chaque devis et facture ; pour un devis, le numéro de la facture qui en est issue."""
        with self._db() as db:
            rows = db.execute(
                "SELECT d.id, d.type, d.numero, d.date, d.client, d.objet, d.total_ttc, d.statut, d.devis_id, "
                "(SELECT f.numero FROM devis_factures f WHERE f.devis_id = d.id ORDER BY f.id LIMIT 1) AS facture "
                "FROM devis_factures d ORDER BY d.date DESC, d.annee DESC, d.rang DESC").fetchall()
        return [dict(r) for r in rows]

    def piece(self, id_):
        """Document complet (données saisies + numéro, suivi, auteurs), ou None."""
        with self._db() as db:
            row = db.execute("SELECT * FROM devis_factures WHERE id = ?", (id_,)).fetchone()
        if row is None:
            return None
        meta = {k: row[k] for k in ("id", "type", "numero", "annee", "rang", "statut", "devis_id",
                                    "cree_par", "cree_le", "modifie_par", "modifie_le")}
        return {**json.loads(row["donnees"]), **meta}

    def prochain_rang(self, type_, annee):
        with self._db() as db:
            dernier = db.execute("SELECT MAX(rang) FROM devis_factures WHERE type = ? AND annee = ?",
                                 (type_, annee)).fetchone()[0]
        return (dernier or 0) + 1

    def enregistrer_piece(self, piece, numero, annee, rang, total_ttc, auteur, id_=None, devis_id=None):
        """Crée (id_ None) ou remplace un document ; une facture créée d'après un devis en attente
        passe ce devis à « Accepté ». Renvoie l'identifiant."""
        quand = _maintenant()
        champs = (piece["type"], numero, annee, rang, piece["date"], piece["client_nom"].replace("\n", " · "),
                  piece["objet"], float(total_ttc), piece["statut"], json.dumps(piece, ensure_ascii=False))
        try:
            with self._db() as db:
                if id_ is None:
                    id_ = db.execute(
                        "INSERT INTO devis_factures (type, numero, annee, rang, date, client, objet, total_ttc, "
                        "statut, donnees, devis_id, cree_par, cree_le, modifie_par, modifie_le) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (*champs, devis_id, auteur, quand, auteur, quand)).lastrowid
                    if devis_id:
                        db.execute("UPDATE devis_factures SET statut = 'accepte' "
                                   "WHERE id = ? AND type = 'devis' AND statut = 'en_attente'", (devis_id,))
                else:
                    db.execute(
                        "UPDATE devis_factures SET type = ?, numero = ?, annee = ?, rang = ?, date = ?, client = ?, "
                        "objet = ?, total_ttc = ?, statut = ?, donnees = ?, modifie_par = ?, modifie_le = ? "
                        "WHERE id = ?", (*champs, auteur, quand, id_))
        except sqlite3.IntegrityError as exc:
            raise ErreurDonnees(f"Le numéro {numero} est déjà utilisé.") from exc
        return id_

    def statut_piece(self, id_, statut, auteur):
        with self._db() as db:
            row = db.execute("SELECT donnees FROM devis_factures WHERE id = ?", (id_,)).fetchone()
            donnees = {**json.loads(row["donnees"]), "statut": statut}
            db.execute("UPDATE devis_factures SET statut = ?, donnees = ?, modifie_par = ?, modifie_le = ? "
                       "WHERE id = ?", (statut, json.dumps(donnees, ensure_ascii=False), auteur, _maintenant(), id_))

    def supprimer_piece(self, id_):
        with self._db() as db:
            db.execute("UPDATE devis_factures SET devis_id = NULL WHERE devis_id = ?", (id_,))
            db.execute("DELETE FROM devis_factures WHERE id = ?", (id_,))

    def clients(self, maxi=50):
        """Clients des derniers documents (sans doublon), pour remplir un nouveau devis."""
        with self._db() as db:
            rows = db.execute("SELECT donnees FROM devis_factures ORDER BY modifie_le DESC").fetchall()
        vus, clients = set(), []
        for row in rows:
            d = json.loads(row["donnees"])
            cle = " ".join(d["client_nom"].lower().split())
            if cle not in vus:
                vus.add(cle)
                clients.append({k: d.get(f"client_{k}", "") for k in ("nom", "adresse", "telephone", "email")})
            if len(clients) >= maxi:
                break
        return clients

    # -- notes de frais ----------------------------------------------------------
    def lister_ndf(self):
        with self._db() as db:
            rows = db.execute(
                "SELECT n.id, n.date, n.personne, n.objet, n.total_ttc, n.statut, "
                "(SELECT COUNT(*) FROM justificatifs j WHERE j.note_id = n.id) AS nb_justificatifs "
                "FROM notes_frais n ORDER BY n.date DESC, n.id DESC").fetchall()
        return [dict(r) for r in rows]

    def note_frais(self, id_):
        """Note complète (données saisies + suivi + signature PNG), ou None."""
        with self._db() as db:
            row = db.execute("SELECT * FROM notes_frais WHERE id = ?", (id_,)).fetchone()
        if row is None:
            return None
        return {**json.loads(row["donnees"]), "id": row["id"], "statut": row["statut"],
                "signature": row["signature"], "cree_par": row["cree_par"], "modifie_le": row["modifie_le"]}

    def enregistrer_ndf(self, note, signature, resume, auteur, id_=None):
        """Crée ou remplace une note ; rattache les justificatifs de ses dépenses et supprime ceux
        qui n'y sont plus. `resume` : (date, personne, objet, total TTC). Renvoie l'identifiant."""
        quand = _maintenant()
        ids = [j for d in note["depenses"] for j in d["justificatifs"]]
        champs = (*resume[:3], float(resume[3]), note["statut"], json.dumps(note, ensure_ascii=False), signature)
        with self._db() as db:
            if id_ is None:
                id_ = db.execute(
                    "INSERT INTO notes_frais (date, personne, objet, total_ttc, statut, donnees, signature, "
                    "cree_par, cree_le, modifie_par, modifie_le) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (*champs, auteur, quand, auteur, quand)).lastrowid
            else:
                db.execute("UPDATE notes_frais SET date = ?, personne = ?, objet = ?, total_ttc = ?, statut = ?, "
                           "donnees = ?, signature = ?, modifie_par = ?, modifie_le = ? WHERE id = ?",
                           (*champs, auteur, quand, id_))
            if ids:
                marques = ", ".join("?" * len(ids))
                libres = db.execute(f"SELECT COUNT(*) FROM justificatifs WHERE id IN ({marques}) "
                                    "AND (note_id IS NULL OR note_id = ?)", (*ids, id_)).fetchone()[0]
                if libres != len(ids):
                    raise ErreurDonnees("Justificatif introuvable : retirez-le puis ajoutez-le à nouveau.")
                db.execute(f"UPDATE justificatifs SET note_id = ? WHERE id IN ({marques})", (id_, *ids))
                db.execute(f"DELETE FROM justificatifs WHERE note_id = ? AND id NOT IN ({marques})", (id_, *ids))
            else:
                db.execute("DELETE FROM justificatifs WHERE note_id = ?", (id_,))
        return id_

    def statut_ndf(self, id_, statut, auteur):
        with self._db() as db:
            row = db.execute("SELECT donnees FROM notes_frais WHERE id = ?", (id_,)).fetchone()
            donnees = {**json.loads(row["donnees"]), "statut": statut}
            db.execute("UPDATE notes_frais SET statut = ?, donnees = ?, modifie_par = ?, modifie_le = ? WHERE id = ?",
                       (statut, json.dumps(donnees, ensure_ascii=False), auteur, _maintenant(), id_))

    def supprimer_ndf(self, id_):
        with self._db() as db:
            db.execute("DELETE FROM justificatifs WHERE note_id = ?", (id_,))
            db.execute("DELETE FROM notes_frais WHERE id = ?", (id_,))

    def ajouter_justificatif(self, nom, contenu, largeur, hauteur):
        """Garde une image de justificatif (pas encore rattachée) ; renvoie son identifiant.
        Au passage, supprime ceux envoyés il y a plus de 2 jours et jamais rattachés."""
        limite = (datetime.now() - timedelta(days=JUSTIFICATIF_ORPHELIN_JOURS)).isoformat(timespec="seconds")
        with self._db() as db:
            db.execute("DELETE FROM justificatifs WHERE note_id IS NULL AND cree_le < ?", (limite,))
            return db.execute("INSERT INTO justificatifs (nom, largeur, hauteur, contenu, cree_le) "
                              "VALUES (?, ?, ?, ?, ?)", (nom[:200], largeur, hauteur, contenu, _maintenant())).lastrowid

    def justificatif(self, id_):
        with self._db() as db:
            row = db.execute("SELECT id, note_id, nom, largeur, hauteur, contenu FROM justificatifs WHERE id = ?",
                             (id_,)).fetchone()
        return dict(row) if row else None

    def images_justificatifs(self, ids):
        """{id: (jpeg, largeur, hauteur)} pour les justificatifs demandés."""
        if not ids:
            return {}
        with self._db() as db:
            rows = db.execute(f"SELECT id, contenu, largeur, hauteur FROM justificatifs "
                              f"WHERE id IN ({', '.join('?' * len(ids))})", list(ids)).fetchall()
        return {r["id"]: (r["contenu"], r["largeur"], r["hauteur"]) for r in rows}
