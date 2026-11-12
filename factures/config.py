"""Réglages de l'application, lus dans les variables d'environnement (voir docs/DEPLOIEMENT.md)."""
import os
import secrets
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent  # dossier du projet
TAILLE_MAX = 25 * 1024 * 1024  # taille maximale d'une facture envoyée

# Réglages Nextcloud par défaut (enregistrés ensuite dans la base)
NEXTCLOUD_DEFAUT = {
    "nextcloud_url": "",
    "nextcloud_login": "",
    "nextcloud_password": "",
    "nextcloud_user_id": "",
    "dossier": "Factures/Metro",
    # "type" : chaque type de PDF va dans son dossier (destinations) ;
    # "facture" : un dossier par facture « AAAA_MM_DD - total TTC » dans le dossier principal
    "rangement": "type",
    # dossier propre à un type de PDF (clé de DOCUMENTS) ; absent ou vide = dossier principal
    "destinations": {},
}


def dossier_donnees():
    """DATA_DIR, sinon le dossier « data » du projet (base, clé secrète)."""
    return Path(os.environ.get("DATA_DIR", RACINE / "data")).resolve()


def env_bool(nom, defaut):
    valeur = os.environ.get(nom)
    return defaut if valeur is None else valeur.strip().lower() in ("1", "true", "oui", "yes", "on")


def connexion_active():
    """CONNEXION=0 : pas d'écran de connexion, tout le monde a les droits d'administrateur.
    À réserver à un serveur privé (réseau local, VPN). Activée par défaut."""
    return env_bool("CONNEXION", True)


def cle_secrete(dossier):
    """SECRET_KEY, sinon une clé générée une fois et gardée dans le dossier de données
    (les sessions survivent aux redémarrages)."""
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    fichier = dossier / "secret_key"
    if not fichier.exists():
        dossier.mkdir(parents=True, exist_ok=True)
        fichier.write_text(secrets.token_hex(32), encoding="utf-8")
        fichier.chmod(0o600)
    return fichier.read_text(encoding="utf-8").strip()
