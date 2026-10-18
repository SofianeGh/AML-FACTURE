"""Outils des tests : application sur une base temporaire, faux Nextcloud en mémoire, factures d'exemple.

Les factures d'exemple (PDF METRO réels) ne sont pas dans git : les déposer dans
tests/factures_exemple/ pour lancer les tests qui en ont besoin (sinon ils sont ignorés).
"""
import posixpath
import re
from pathlib import Path

import pytest

from factures import commun, create_app, securite
from factures.nextcloud import clean_path

EXEMPLES = Path(__file__).parent / "factures_exemple"
ENTETE = {"X-Requested-With": "fetch"}
ADMIN = ("admin", "motdepasse-admin")
MEMBRE = ("membre", "motdepasse-membre")


def factures_exemple():
    return sorted(EXEMPLES.glob("*.pdf"))


def date_du_fichier(chemin):
    """« 30_59_59900_20261003111554_… » -> « 03-10-2026 » (date de la facture dans le nom METRO)."""
    m = re.match(r"\d+_\d+_\d+_(\d{4})(\d{2})(\d{2})", chemin.name)
    return f"{m[3]}-{m[2]}-{m[1]}"


avec_exemples = pytest.mark.skipif(not factures_exemple(), reason="aucune facture dans tests/factures_exemple/")


class FauxNextcloud:
    """Remplace le client WebDAV : fichiers gardés en mémoire, mêmes règles d'envoi."""

    fichiers = {}  # chemin -> contenu
    dossiers = set()

    def __init__(self, url, login, password, user_id=None):
        self.user_id = user_id or login

    @classmethod
    def vider(cls):
        cls.fichiers, cls.dossiers = {}, {""}

    def check(self):
        return self.user_id

    def list_folders(self, path=""):
        path = clean_path(path)
        return sorted(d.rsplit("/", 1)[-1] for d in self.dossiers if d and posixpath.dirname(d) == path)

    def make_dirs(self, path):
        courant = ""
        for part in clean_path(path).split("/"):
            if part:
                courant = f"{courant}/{part}" if courant else part
                self.dossiers.add(courant)

    def upload(self, folder, filename, data):
        folder = clean_path(folder)
        self.make_dirs(folder)
        racine, ext = posixpath.splitext(filename)
        for i in range(1, 100):
            nom = filename if i == 1 else f"{racine} ({i}){ext}"
            chemin = f"{folder}/{nom}" if folder else nom
            if chemin not in self.fichiers:
                break
            if len(self.fichiers[chemin]) == len(data):
                return {"nom": nom, "chemin": "/" + chemin, "deja_present": True}
        self.fichiers[chemin] = data
        return {"nom": nom, "chemin": "/" + chemin, "deja_present": False}

    def put(self, folder, filename, data):
        chemin = f"{clean_path(folder)}/{filename}".lstrip("/")
        self.fichiers[chemin] = data
        return {"nom": filename, "chemin": "/" + chemin}

    def delete(self, folder, filename):
        return self.fichiers.pop(f"{clean_path(folder)}/{filename}".lstrip("/"), None) is not None


@pytest.fixture(autouse=True)
def compteur_essais_vide():
    """Chaque test repart sans essai de mot de passe raté (le compteur est global, par adresse IP)."""
    securite._ECHECS.clear()


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("COOKIE_SECURE", "0")  # le client de test parle en http
    monkeypatch.delenv("TRUST_PROXY", raising=False)
    monkeypatch.setattr(commun, "Nextcloud", FauxNextcloud)
    FauxNextcloud.vider()
    application = create_app(tmp_path)
    stockage = application.extensions["stockage"]
    stockage.ajouter_utilisateur(*ADMIN, admin=True)
    stockage.ajouter_utilisateur(*MEMBRE)
    return application


def connecter(application, identifiants):
    client = application.test_client()
    nom, mdp = identifiants
    reponse = client.post("/api/connexion", json={"nom": nom, "mot_de_passe": mdp}, headers=ENTETE)
    assert reponse.status_code == 200, reponse.get_json()
    return client


@pytest.fixture
def admin(app):
    return connecter(app, ADMIN)


@pytest.fixture
def membre(app):
    return connecter(app, MEMBRE)


@pytest.fixture
def nextcloud_configure(admin):
    """Connexion Nextcloud enregistrée (faux serveur), dossier principal « 2025-2026 »."""
    reponse = admin.post("/api/config", headers=ENTETE, json={
        "nextcloud_url": "https://cloud.exemple.fr/apps/files/files/1?dir=/2025-2026",
        "nextcloud_login": "aml", "nextcloud_password": "secret"})
    assert reponse.status_code == 200, reponse.get_json()
    return admin
