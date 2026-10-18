"""Outils partagés par les routes : erreurs, journal, base de données, réglages Nextcloud."""
import logging

from flask import current_app, jsonify

from .config import NEXTCLOUD_DEFAUT
from .nextcloud import Nextcloud, clean_path
from .pdf import DOCUMENTS

log = logging.getLogger("aml-factures")

CONDUCTEUR_MAX = 60


class RequeteInvalide(Exception):
    """Données envoyées par le navigateur incorrectes : réponse 400 avec le message."""


def erreur(message, code=400):
    return jsonify({"erreur": message}), code


def stockage():
    """Base de l'application (comptes, réglages, préférences)."""
    return current_app.extensions["stockage"]


def lire_conducteur(texte):
    """Nom du conducteur de la course : obligatoire pour envoyer sur Nextcloud."""
    nom = " ".join(str(texte or "").split())
    if not nom:
        raise RequeteInvalide("Indiquez le nom du conducteur avant d'envoyer.")
    if len(nom) > CONDUCTEUR_MAX:
        raise RequeteInvalide(f"Nom du conducteur trop long ({CONDUCTEUR_MAX} caractères maximum).")
    return nom


# ---------------------------------------------------------------- réglages Nextcloud

def load_config():
    cfg = {**NEXTCLOUD_DEFAUT, **(stockage().reglage("nextcloud") or {})}
    cfg["destinations"] = dict(cfg["destinations"])  # copie : ne jamais modifier les valeurs par défaut
    return cfg


def save_config(cfg):
    stockage().definir_reglage("nextcloud", cfg)


def public_config(cfg):
    """Configuration renvoyée au navigateur : jamais le mot de passe."""
    return {
        "nextcloud_url": cfg["nextcloud_url"],
        "nextcloud_login": cfg["nextcloud_login"],
        "has_password": bool(cfg["nextcloud_password"]),
        "dossier": cfg["dossier"],
        "rangement": cfg["rangement"],
        "destinations": {cle: cfg["destinations"].get(cle, "") for cle in DOCUMENTS},
        "documents": DOCUMENTS,
        "configure": bool(cfg["nextcloud_url"] and cfg["nextcloud_login"] and cfg["nextcloud_password"]),
    }


def dossier_de(cfg, document):
    """Dossier Nextcloud d'un type de PDF : le sien s'il est défini, sinon le dossier principal."""
    return clean_path(cfg["destinations"].get(document) or cfg["dossier"])


def client(cfg=None):
    cfg = cfg or load_config()
    return Nextcloud(cfg["nextcloud_url"], cfg["nextcloud_login"], cfg["nextcloud_password"],
                     cfg["nextcloud_user_id"] or None)
