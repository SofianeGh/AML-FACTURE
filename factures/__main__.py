"""Lance le serveur de production (waitress) : python -m factures"""
import os

from waitress import serve

from . import create_app
from .commun import log


def main():
    app = create_app()
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5000"))
    threads = int(os.environ.get("THREADS", "8"))
    if app.extensions["stockage"].nb_utilisateurs() == 0:
        log.warning("Aucun compte : créez-en un avec « python manage.py ajouter-utilisateur NOM --admin ».")
    print(f"Application disponible sur http://{'localhost' if host == '127.0.0.1' else host}:{port}", flush=True)
    serve(app, host=host, port=port, threads=threads)


if __name__ == "__main__":
    main()
