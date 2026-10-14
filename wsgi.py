"""Point d'entrée WSGI (gunicorn, waitress-serve, mod_wsgi…) : `wsgi:app`.

Lancer un seul processus (plusieurs threads) : les aperçus PDF utilisent un cache en mémoire.
"""
from app import app

application = app
