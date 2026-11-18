"""Application web de l'AML : factures METRO -> prix TTC + marge, archivage sur Nextcloud.

Prévue pour être hébergée sur Internet : accès par compte, préférences partagées entre
les membres, cookies sécurisés, protection CSRF, en-têtes de sécurité, reverse proxy.
Réglages par variables d'environnement : voir docs/DEPLOIEMENT.md.
"""
import json
import logging
import os
from datetime import timedelta
from pathlib import Path

from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix

from . import securite
from .commun import log
from .config import NEXTCLOUD_DEFAUT, RACINE, TAILLE_MAX, cle_secrete, dossier_donnees, env_bool
from .routes import BLUEPRINTS
from .stockage import Stockage
from .treso import Tresorerie


def create_app(dossier=None):
    """Crée l'application. `dossier` : dossier de données (sinon DATA_DIR ou « data » du projet)."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    dossier = Path(dossier or dossier_donnees())

    app = Flask(__name__)
    app.json.sort_keys = False  # garder l'ordre des types de PDF (facture, bilan, vente…)
    app.config.update(
        SECRET_KEY=cle_secrete(dossier),
        MAX_CONTENT_LENGTH=TAILLE_MAX,
        SESSION_COOKIE_NAME="aml_factures",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        # à désactiver seulement pour un usage local en http (start.bat le fait)
        SESSION_COOKIE_SECURE=env_bool("COOKIE_SECURE", True),
        PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
        DATA_DIR=dossier,
    )
    stockage = Stockage(dossier / "aml-factures.db")
    app.extensions["stockage"] = stockage
    app.extensions["treso"] = Tresorerie(stockage)

    # Derrière un reverse proxy (nginx, Apache, Traefik…) : nombre de proxys de confiance.
    # Prend en compte X-Forwarded-For/Proto/Host/Prefix (hébergement dans un sous-dossier, ex. /factures).
    proxies = int(os.environ.get("TRUST_PROXY", "0"))
    if proxies:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=proxies, x_proto=proxies, x_host=proxies, x_prefix=proxies)

    securite.installer(app)
    for bp in BLUEPRINTS:
        app.register_blueprint(bp)

    _importer_ancienne_config(stockage)
    _admin_initial(stockage)
    return app


def _importer_ancienne_config(stockage):
    """Reprend le config.json des premières versions (réglages Nextcloud) dans la base."""
    ancien = RACINE / "config.json"
    if ancien.exists() and stockage.reglage("nextcloud") is None:
        stockage.definir_reglage("nextcloud", {**NEXTCLOUD_DEFAUT, **json.loads(ancien.read_text(encoding="utf-8"))})
        ancien.rename(ancien.with_name("config.json.importe"))
        log.info("Ancienne configuration Nextcloud importée dans la base.")


def _admin_initial(stockage):
    """Crée le premier administrateur depuis ADMIN_UTILISATEUR / ADMIN_MOT_DE_PASSE (base vide seulement)."""
    nom, mdp = os.environ.get("ADMIN_UTILISATEUR"), os.environ.get("ADMIN_MOT_DE_PASSE")
    if nom and mdp and stockage.nb_utilisateurs() == 0:
        stockage.ajouter_utilisateur(nom, mdp, admin=True)
        log.warning("Compte administrateur « %s » créé à partir des variables d'environnement.", nom)
