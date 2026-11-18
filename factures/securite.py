"""Sécurité : connexion obligatoire, anti-CSRF, en-têtes, limitation des essais de mot de passe."""
import threading
import time
from collections import defaultdict, deque
from functools import wraps

from flask import g, redirect, request, session, url_for

from .commun import RequeteInvalide, erreur, log, stockage
from .config import connexion_active
from .nextcloud import NextcloudError
from .stockage import ErreurCompte, ErreurDonnees

PAGES_PUBLIQUES = {"comptes.page_connexion", "comptes.connexion", "static"}

# Utilisateur de toutes les requêtes quand la connexion est désactivée (CONNEXION=0)
UTILISATEUR_LIBRE = {"nom": "Local Stock", "admin": True, "libre": True}


def utilisateur_courant():
    nom = session.get("utilisateur")
    return stockage().compte(nom) if nom else None  # compte supprimé = déconnecté


def admin_requis(vue):
    @wraps(vue)
    def verifiee(*args, **kwargs):
        if not g.utilisateur["admin"]:
            return erreur("Réservé aux administrateurs.", 403)
        return vue(*args, **kwargs)
    return verifiee


# Limite les essais de mot de passe : 5 échecs en 10 minutes par adresse IP
_ECHECS = defaultdict(deque)
_VERROU_ECHECS = threading.Lock()
ECHECS_MAX, ECHECS_FENETRE = 5, 600


def bloque(ip):
    with _VERROU_ECHECS:
        essais = _ECHECS[ip]
        while essais and essais[0] < time.monotonic() - ECHECS_FENETRE:
            essais.popleft()
        return len(essais) >= ECHECS_MAX


def noter_echec(ip):
    with _VERROU_ECHECS:
        _ECHECS[ip].append(time.monotonic())


def installer(app):
    """Contrôles avant chaque requête, en-têtes de sécurité et réponses d'erreur."""
    libre = not connexion_active()
    if libre:
        log.warning("Connexion désactivée (CONNEXION=0) : l'application est ouverte à tous ceux qui y ont accès.")

    @app.before_request
    def _controles():
        # Anti-CSRF : toute requête qui modifie doit venir du JavaScript de l'application
        # (un autre site ne peut pas ajouter cet en-tête ; les cookies SameSite=Lax complètent).
        if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get("X-Requested-With") != "fetch":
            return erreur("Requête refusée.", 403)
        if libre:
            g.utilisateur = dict(UTILISATEUR_LIBRE)
            if request.endpoint == "comptes.page_connexion":
                return redirect(url_for("factures.index"))
            return None
        if request.endpoint in PAGES_PUBLIQUES:
            return None
        g.utilisateur = utilisateur_courant()
        if g.utilisateur is None:
            if request.path.startswith("/api/"):
                return erreur("Session expirée : reconnectez-vous.", 401)
            return redirect(url_for("comptes.page_connexion"))
        return None

    @app.after_request
    def _entetes(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        if resp.mimetype == "text/html":
            resp.headers.setdefault("X-Frame-Options", "DENY")
            resp.headers.setdefault(
                "Content-Security-Policy",
                "default-src 'self'; img-src 'self' data:; object-src 'none'; "
                "frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
            )
        if request.path.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-store"
        if request.is_secure:
            resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        return resp

    @app.errorhandler(RequeteInvalide)
    def _requete_invalide(exc):
        return erreur(str(exc), 400)

    @app.errorhandler(ErreurCompte)
    def _erreur_compte(exc):
        return erreur(str(exc), 400)

    @app.errorhandler(ErreurDonnees)
    def _erreur_donnees(exc):
        return erreur(str(exc), 400)

    @app.errorhandler(NextcloudError)
    def _nextcloud_error(exc):
        return erreur(str(exc), 502)

    @app.errorhandler(413)
    def _trop_gros(_exc):
        return erreur("Fichier trop volumineux (25 Mo maximum).", 413)
