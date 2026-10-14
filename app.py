"""Application web : factures METRO -> prix TTC + marge, archivage sur Nextcloud.

Prévue pour être hébergée sur Internet : accès par compte, préférences partagées entre
les membres, cookies sécurisés, protection CSRF, en-têtes de sécurité, reverse proxy.
Réglages par variables d'environnement : voir DEPLOIEMENT.md.
"""
import hashlib
import io
import json
import logging
import os
import re
import secrets
import threading
import time
from collections import OrderedDict, defaultdict, deque
from datetime import timedelta
from functools import wraps
from pathlib import Path

from flask import Flask, g, jsonify, redirect, request, send_file, send_from_directory, session, url_for
from werkzeug.middleware.proxy_fix import ProxyFix

from metro_parser import FactureIllisible, parse_pdf
from nextcloud import Nextcloud, NextcloudError, base_url, clean_path
from recap_pdf import CATEGORIES, generer_recap
from stockage import ErreurCompte, Stockage

ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("DATA_DIR", ROOT / "data")).resolve()
NEXTCLOUD_DEFAUT = {
    "nextcloud_url": "",
    "nextcloud_login": "",
    "nextcloud_password": "",
    "nextcloud_user_id": "",
    "dossier": "Factures/Metro",
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("aml-factures")


def _env_bool(nom, defaut):
    valeur = os.environ.get(nom)
    return defaut if valeur is None else valeur.strip().lower() in ("1", "true", "oui", "yes", "on")


def _cle_secrete():
    """SECRET_KEY, sinon une clé générée une fois et gardée dans DATA_DIR (les sessions survivent aux redémarrages)."""
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    fichier = DATA_DIR / "secret_key"
    if not fichier.exists():
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        fichier.write_text(secrets.token_hex(32), encoding="utf-8")
        fichier.chmod(0o600)
    return fichier.read_text(encoding="utf-8").strip()


stockage = Stockage(DATA_DIR / "aml-factures.db")

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.config.update(
    SECRET_KEY=_cle_secrete(),
    MAX_CONTENT_LENGTH=25 * 1024 * 1024,
    SESSION_COOKIE_NAME="aml_factures",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    # à désactiver seulement pour un usage local en http (start.bat le fait)
    SESSION_COOKIE_SECURE=_env_bool("COOKIE_SECURE", True),
    PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
)

# Derrière un reverse proxy (nginx, Apache, Traefik…) : nombre de proxys de confiance.
# Prend en compte X-Forwarded-For/Proto/Host/Prefix (hébergement dans un sous-dossier, ex. /factures).
_PROXIES = int(os.environ.get("TRUST_PROXY", "0"))
if _PROXIES:
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=_PROXIES, x_proto=_PROXIES, x_host=_PROXIES, x_prefix=_PROXIES)


def _importer_ancienne_config():
    """Reprend le config.json des premières versions (réglages Nextcloud) dans la base."""
    ancien = ROOT / "config.json"
    if ancien.exists() and stockage.reglage("nextcloud") is None:
        stockage.definir_reglage("nextcloud", {**NEXTCLOUD_DEFAUT, **json.loads(ancien.read_text(encoding="utf-8"))})
        ancien.rename(ancien.with_name("config.json.importe"))
        log.info("Ancienne configuration Nextcloud importée dans la base.")


def _admin_initial():
    """Crée le premier administrateur depuis ADMIN_UTILISATEUR / ADMIN_MOT_DE_PASSE (base vide seulement)."""
    nom, mdp = os.environ.get("ADMIN_UTILISATEUR"), os.environ.get("ADMIN_MOT_DE_PASSE")
    if nom and mdp and stockage.nb_utilisateurs() == 0:
        stockage.ajouter_utilisateur(nom, mdp, admin=True)
        log.warning("Compte administrateur « %s » créé à partir des variables d'environnement.", nom)


_importer_ancienne_config()
_admin_initial()

# Dernières factures analysées (empreinte -> PDF), pour ouvrir les aperçus par simple lien.
# Gardées en mémoire : lancer un seul processus (avec plusieurs threads), voir DEPLOIEMENT.md.
FACTURES = OrderedDict()
FACTURES_MAX = 50
_VERROU_FACTURES = threading.Lock()


def garder_facture(data):
    empreinte = hashlib.sha1(data).hexdigest()
    with _VERROU_FACTURES:
        FACTURES[empreinte] = data
        FACTURES.move_to_end(empreinte)
        while len(FACTURES) > FACTURES_MAX:
            FACTURES.popitem(last=False)
    return empreinte


def load_config():
    return {**NEXTCLOUD_DEFAUT, **(stockage.reglage("nextcloud") or {})}


def save_config(cfg):
    stockage.definir_reglage("nextcloud", cfg)


def public_config(cfg):
    """Configuration renvoyée au navigateur : jamais le mot de passe."""
    return {
        "nextcloud_url": cfg["nextcloud_url"],
        "nextcloud_login": cfg["nextcloud_login"],
        "has_password": bool(cfg["nextcloud_password"]),
        "dossier": cfg["dossier"],
        "configure": bool(cfg["nextcloud_url"] and cfg["nextcloud_login"] and cfg["nextcloud_password"]),
    }


def client(cfg=None):
    cfg = cfg or load_config()
    return Nextcloud(cfg["nextcloud_url"], cfg["nextcloud_login"], cfg["nextcloud_password"],
                     cfg["nextcloud_user_id"] or None)


def erreur(message, code=400):
    return jsonify({"erreur": message}), code


class RequeteInvalide(Exception):
    pass


@app.errorhandler(RequeteInvalide)
def _requete_invalide(exc):
    return erreur(str(exc), 400)


@app.errorhandler(ErreurCompte)
def _erreur_compte(exc):
    return erreur(str(exc), 400)


@app.errorhandler(NextcloudError)
def _nextcloud_error(exc):
    return erreur(str(exc), 502)


@app.errorhandler(413)
def _trop_gros(_exc):
    return erreur("Fichier trop volumineux (25 Mo maximum).", 413)


# ---------------------------------------------------------------- sécurité

PAGES_PUBLIQUES = {"page_connexion", "connexion", "static"}


def utilisateur_courant():
    nom = session.get("utilisateur")
    return stockage.compte(nom) if nom else None  # compte supprimé = déconnecté


@app.before_request
def _controles():
    # Anti-CSRF : toute requête qui modifie doit venir du JavaScript de l'application
    # (un autre site ne peut pas ajouter cet en-tête ; les cookies SameSite=Lax complètent).
    if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get("X-Requested-With") != "fetch":
        return erreur("Requête refusée.", 403)
    if request.endpoint in PAGES_PUBLIQUES:
        return None
    g.utilisateur = utilisateur_courant()
    if g.utilisateur is None:
        if request.path.startswith("/api/"):
            return erreur("Session expirée : reconnectez-vous.", 401)
        return redirect(url_for("page_connexion"))
    return None


def admin_requis(vue):
    @wraps(vue)
    def verifiee(*args, **kwargs):
        if not g.utilisateur["admin"]:
            return erreur("Réservé aux administrateurs.", 403)
        return vue(*args, **kwargs)
    return verifiee


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


# Limite les essais de mot de passe : 5 échecs en 10 minutes par adresse IP
_ECHECS = defaultdict(deque)
_VERROU_ECHECS = threading.Lock()
ECHECS_MAX, ECHECS_FENETRE = 5, 600


def _bloque(ip):
    with _VERROU_ECHECS:
        essais = _ECHECS[ip]
        while essais and essais[0] < time.monotonic() - ECHECS_FENETRE:
            essais.popleft()
        return len(essais) >= ECHECS_MAX


def _noter_echec(ip):
    with _VERROU_ECHECS:
        _ECHECS[ip].append(time.monotonic())


# ---------------------------------------------------------------- connexion et comptes

@app.get("/connexion")
def page_connexion():
    if utilisateur_courant():
        return redirect(url_for("index"))
    return send_from_directory(app.static_folder, "connexion.html")


@app.post("/api/connexion")
def connexion():
    ip = request.remote_addr or "?"
    if _bloque(ip):
        return erreur("Trop d'essais : réessayez dans quelques minutes.", 429)
    data = request.get_json(silent=True) or {}
    compte = stockage.authentifier(data.get("nom"), data.get("mot_de_passe"))
    if compte is None:
        _noter_echec(ip)
        log.warning("Échec de connexion pour « %s » depuis %s", data.get("nom"), ip)
        return erreur("Identifiant ou mot de passe incorrect.", 401)
    session.clear()
    session["utilisateur"] = compte["nom"]
    session.permanent = True
    log.info("Connexion de %s depuis %s", compte["nom"], ip)
    return jsonify(compte)


@app.post("/api/deconnexion")
def deconnexion():
    session.clear()
    return jsonify({"ok": True})


@app.get("/api/moi")
def moi():
    return jsonify(g.utilisateur)


@app.post("/api/moi/mot-de-passe")
def changer_mon_mot_de_passe():
    data = request.get_json(silent=True) or {}
    if stockage.authentifier(g.utilisateur["nom"], data.get("actuel")) is None:
        return erreur("Mot de passe actuel incorrect.", 400)
    stockage.changer_mot_de_passe(g.utilisateur["nom"], data.get("nouveau"))
    return jsonify({"ok": True})


@app.get("/api/comptes")
@admin_requis
def lister_comptes():
    return jsonify(stockage.utilisateurs())


@app.post("/api/comptes")
@admin_requis
def creer_compte():
    data = request.get_json(silent=True) or {}
    nom = stockage.ajouter_utilisateur(data.get("nom"), data.get("mot_de_passe"), bool(data.get("admin")))
    log.info("%s a créé le compte %s", g.utilisateur["nom"], nom)
    return jsonify(stockage.utilisateurs())


@app.delete("/api/comptes/<nom>")
@admin_requis
def supprimer_compte(nom):
    if nom == g.utilisateur["nom"]:
        return erreur("Vous ne pouvez pas supprimer votre propre compte.", 400)
    stockage.supprimer_utilisateur(nom)
    log.info("%s a supprimé le compte %s", g.utilisateur["nom"], nom)
    return jsonify(stockage.utilisateurs())


# ---------------------------------------------------------------- préférences partagées

RE_CLE_ARTICLE = re.compile(r"(pieces|prix|local):\d{1,12}")


def _valider_preference(cle, valeur):
    if valeur is None:
        return None
    if cle in ("marge", "taxe", "arrondi") and isinstance(valeur, (str, int, float)) and len(str(valeur)) <= 12:
        return str(valeur)
    if cle == "margeType" and valeur in ("pct", "eur"):
        return valeur
    m = RE_CLE_ARTICLE.fullmatch(cle)
    if m and m[1] == "pieces" and isinstance(valeur, int) and 1 <= valeur <= 10000:
        return valeur
    if m and m[1] == "prix" and isinstance(valeur, (int, float)) and 0 <= valeur <= 100000:
        return round(float(valeur), 2)
    if m and m[1] == "local" and valeur is True:
        return True
    raise RequeteInvalide(f"Préférence invalide : {cle}")


@app.get("/api/preferences")
def lire_preferences():
    return jsonify(stockage.preferences())


@app.put("/api/preferences")
def ecrire_preferences():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or len(data) > 500:
        raise RequeteInvalide("Préférences illisibles.")
    stockage.definir_preferences({cle: _valider_preference(cle, v) for cle, v in data.items()},
                                 g.utilisateur["nom"])
    return jsonify({"ok": True})


# ---------------------------------------------------------------- factures

@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.post("/api/factures")
def analyser_facture():
    fichier = request.files.get("fichier")
    if not fichier:
        return erreur("Aucun fichier reçu.")
    data = fichier.read()
    try:
        facture = parse_pdf(io.BytesIO(data))
    except FactureIllisible as exc:
        return erreur(str(exc), 422)
    facture["id"] = garder_facture(data)
    facture["fichier"] = fichier.filename
    facture["nom_nextcloud"] = f"{facture['date']}.pdf" if facture["date"] else None
    return jsonify(facture)


@app.get("/api/config")
def lire_config():
    return jsonify(public_config(load_config()))


@app.post("/api/config")
def ecrire_config():
    data = request.get_json(silent=True) or {}
    connexion_nc = {"nextcloud_url", "nextcloud_login", "nextcloud_password"} & data.keys()
    if connexion_nc and not g.utilisateur["admin"]:
        return erreur("Seul un administrateur peut changer la connexion Nextcloud.", 403)
    cfg = load_config()
    if "nextcloud_url" in data:
        cfg["nextcloud_url"] = base_url(data["nextcloud_url"]) if data["nextcloud_url"].strip() else ""
    if "nextcloud_login" in data:
        cfg["nextcloud_login"] = data["nextcloud_login"].strip()
    if data.get("nextcloud_password"):  # vide = on garde l'ancien
        cfg["nextcloud_password"] = data["nextcloud_password"]
    if "dossier" in data:
        cfg["dossier"] = clean_path(data["dossier"])

    if connexion_nc:
        cfg["nextcloud_user_id"] = ""
        if cfg["nextcloud_url"] and cfg["nextcloud_login"] and cfg["nextcloud_password"]:
            cfg["nextcloud_user_id"] = client(cfg).check()  # lève NextcloudError si KO
        log.info("%s a modifié la connexion Nextcloud", g.utilisateur["nom"])
    save_config(cfg)
    return jsonify(public_config(cfg))


@app.get("/api/nextcloud/dossiers")
def lister_dossiers():
    chemin = clean_path(request.args.get("chemin", ""))
    return jsonify({"chemin": chemin, "dossiers": client().list_folders(chemin)})


@app.post("/api/nextcloud/dossiers")
def creer_dossier():
    data = request.get_json(silent=True) or {}
    nom = (data.get("nom") or "").strip()
    if not nom or "/" in nom or "\\" in nom:
        return erreur("Nom de dossier invalide.")
    chemin = clean_path(f"{data.get('parent', '')}/{nom}")
    client().make_dirs(chemin)
    return jsonify({"chemin": chemin})


def preparer(data, nom, categories):
    """Vérifie le nom (JJ-MM-AAAA.pdf), relit la facture et range ses lignes par catégorie.

    `categories` : la catégorie de chaque ligne, dans l'ordre (vide = tout en vente).
    Retourne (facture analysée, {catégorie: [lignes]}).
    """
    if not re.fullmatch(r"\d{2}-\d{2}-\d{4}\.pdf", nom):
        raise RequeteInvalide("Nom de fichier attendu : JJ-MM-AAAA.pdf")
    try:
        facture = parse_pdf(io.BytesIO(data))
    except FactureIllisible as exc:
        raise RequeteInvalide(str(exc)) from exc
    if not categories:
        categories = ["vente"] * len(facture["lignes"])
    if len(categories) != len(facture["lignes"]) or any(c not in CATEGORIES for c in categories):
        raise RequeteInvalide("Catégories invalides pour cette facture.")
    groupes = {}
    for ligne, cat in zip(facture["lignes"], categories):
        groupes.setdefault(cat, []).append(ligne)
    return facture, groupes


def nom_recap(nom_facture, categorie):
    """« 18-09-2026.pdf » + event -> « 18-09-2026 - EVENT.pdf »"""
    return f"{nom_facture.removesuffix('.pdf')} - {CATEGORIES[categorie][0]}.pdf"


@app.get("/api/recap/<empreinte>/<categorie>")
def apercu_recap(empreinte, categorie):
    """PDF d'une catégorie, ouvert dans un nouvel onglet : ?nom=JJ-MM-AAAA.pdf&categories=vente,event,…"""
    texte = {"Content-Type": "text/plain; charset=utf-8"}
    with _VERROU_FACTURES:
        data = FACTURES.get(empreinte)
    if data is None:
        return "Facture introuvable : rechargez-la dans l'application.", 404, texte
    nom = request.args.get("nom", "")
    try:
        facture, groupes = preparer(data, nom, [c for c in request.args.get("categories", "").split(",") if c])
    except RequeteInvalide as exc:
        return str(exc), 400, texte
    if categorie not in groupes:
        return "Aucune ligne dans cette catégorie.", 404, texte
    pdf = generer_recap(facture, categorie, groupes[categorie], nom)
    return send_file(io.BytesIO(pdf), mimetype="application/pdf", download_name=nom_recap(nom, categorie))


@app.post("/api/nextcloud/envoyer")
def envoyer():
    """Envoie la facture renommée, puis un PDF par catégorie utilisée.

    Les PDF de catégorie suivent le nom final de la facture (« 30-09-2026 (2) - EVENT.pdf »),
    sont remplacés à chaque envoi, et ceux d'une catégorie qui n'a plus de ligne sont supprimés.
    """
    fichier = request.files.get("fichier")
    if not fichier:
        raise RequeteInvalide("Aucun fichier reçu.")
    try:
        categories = json.loads(request.form.get("categories") or "[]")
    except ValueError as exc:
        raise RequeteInvalide("Catégories illisibles.") from exc
    data = fichier.read()
    nom = (request.form.get("nom") or "").strip()
    facture, groupes = preparer(data, nom, categories)
    cfg = load_config()
    dossier = clean_path(request.form.get("dossier", cfg["dossier"]))
    nc = client(cfg)
    resultat = nc.upload(dossier, nom, data)
    resultat["recaps"], resultat["supprimes"] = [], []
    for cat in CATEGORIES:
        nom_cat = nom_recap(resultat["nom"], cat)
        if cat in groupes:
            pdf = generer_recap(facture, cat, groupes[cat], resultat["nom"])
            resultat["recaps"].append(nc.put(dossier, nom_cat, pdf))
        elif nc.delete(dossier, nom_cat):
            resultat["supprimes"].append(nom_cat)
    log.info("%s a envoyé %s dans /%s (%s)", g.utilisateur["nom"], resultat["nom"], dossier,
             ", ".join(groupes))
    return jsonify(resultat)


def main():
    from waitress import serve

    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5000"))
    threads = int(os.environ.get("THREADS", "8"))
    if stockage.nb_utilisateurs() == 0:
        log.warning("Aucun compte : créez-en un avec « python manage.py ajouter-utilisateur NOM --admin ».")
    print(f"Application disponible sur http://{'localhost' if host == '127.0.0.1' else host}:{port}", flush=True)
    serve(app, host=host, port=port, threads=threads)


if __name__ == "__main__":
    main()
