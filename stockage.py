"""Base SQLite de l'application : comptes, réglages Nextcloud et préférences partagées.

Les préférences (marge, taxe TPE, arrondi, puis par article : pièces, prix choisi,
catégorie Local) sont communes à tous les membres connectés.
"""
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime
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
"""

NOM_VALIDE = re.compile(r"[a-z0-9][a-z0-9._-]{1,31}")
MDP_MIN = 8
# comparé quand le compte n'existe pas, pour que la réponse prenne le même temps
_HASH_FACTICE = generate_password_hash("mot de passe factice")


class ErreurCompte(Exception):
    pass


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
