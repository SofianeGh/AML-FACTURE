"""Point d'entrée WSGI (gunicorn, waitress-serve, mod_wsgi…) : `wsgi:app`.

Lancer un seul processus (plusieurs threads) : les aperçus PDF utilisent un cache en mémoire.
"""
from factures import create_app

app = application = create_app()
