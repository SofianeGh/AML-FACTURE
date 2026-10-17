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
from nextcloud import Nextcloud, NextcloudError, base_url, clean_path, dossier_dans_url
from recap_pdf import CATEGORIES, DOCUMENTS, NOM_BILAN, NOM_VENTES, generer_bilan, generer_recap, generer_ventes
from stockage import ErreurCompte, Stockage

ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("DATA_DIR", ROOT / "data")).resolve()
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
app.json.sort_keys = False  # garder l'ordre des types de PDF (facture, bilan, vente…)
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
    cfg = {**NEXTCLOUD_DEFAUT, **(stockage.reglage("nextcloud") or {})}
    cfg["destinations"] = dict(cfg["destinations"])  # copie : ne jamais modifier les valeurs par défaut
    return cfg


def save_config(cfg):
    stockage.definir_reglage("nextcloud", cfg)


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


def nom_dossier_facture(nom, facture):
    """« 03-10-2026.pdf » + total 959,74 € -> « 2026_10_03 - 959,74 € »"""
    jour, mois, annee = nom.removesuffix(".pdf").split("-")
    total = facture["total_ttc"]
    if total is None:
        total = sum(l["montant_net_ht"] * (1 + (l["tva_taux"] or 0) / 100) for l in facture["lignes"])
    return f"{annee}_{mois}_{jour} - {total:.2f} €".replace(".", ",")


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


CONDUCTEUR_MAX = 60


def lire_conducteur(texte):
    """Nom du conducteur de la course : obligatoire pour envoyer sur Nextcloud."""
    nom = " ".join(str(texte or "").split())
    if not nom:
        raise RequeteInvalide("Indiquez le nom du conducteur avant d'envoyer.")
    if len(nom) > CONDUCTEUR_MAX:
        raise RequeteInvalide(f"Nom du conducteur trop long ({CONDUCTEUR_MAX} caractères maximum).")
    return nom


def _valider_preference(cle, valeur):
    if valeur is None:
        return None
    if cle in ("marge", "taxe", "arrondi") and isinstance(valeur, (str, int, float)) and len(str(valeur)) <= 12:
        return str(valeur)
    if cle == "margeType" and valeur in ("pct", "eur"):
        return valeur
    # noms des conducteurs déjà saisis, proposés dans la case « Conducteur »
    if (cle == "conducteurs" and isinstance(valeur, list) and len(valeur) <= 30
            and all(isinstance(v, str) and 0 < len(v) <= CONDUCTEUR_MAX for v in valeur)):
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
        # adresse copiée depuis la page Fichiers : le dossier ouvert devient la destination
        cfg["dossier"] = dossier_dans_url(data["nextcloud_url"]) or cfg["dossier"]
    if "nextcloud_login" in data:
        cfg["nextcloud_login"] = data["nextcloud_login"].strip()
    if data.get("nextcloud_password"):  # vide = on garde l'ancien
        cfg["nextcloud_password"] = data["nextcloud_password"]
    if "dossier" in data:
        cfg["dossier"] = clean_path(data["dossier"])
    if "rangement" in data:
        if data["rangement"] not in ("type", "facture"):
            raise RequeteInvalide("Rangement invalide.")
        cfg["rangement"] = data["rangement"]
    if "destinations" in data:
        destinations = data["destinations"]
        if not isinstance(destinations, dict) or set(destinations) - DOCUMENTS.keys():
            raise RequeteInvalide("Destinations invalides.")
        for document, chemin in destinations.items():
            cfg["destinations"][document] = clean_path(chemin or "")  # vide = dossier principal

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
    Retourne (facture analysée, {catégorie: [lignes]}, catégorie de chaque ligne).
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
    return facture, groupes, categories


def lire_vente(brut, facture, categories):
    """Choix de vente faits dans l'interface, pour le bilan final : une valeur par ligne pour
    "pieces", "prix" (prix de vente) et "optimal", plus les "reglages" (marge, taxe TPE, arrondi)."""
    try:
        vente = json.loads(brut or "null")
    except ValueError as exc:
        raise RequeteInvalide("Données de vente illisibles.") from exc
    n = len(facture["lignes"])
    if not (isinstance(vente, dict) and isinstance(vente.get("reglages"), dict)
            and all(isinstance(vente.get(k), list) and len(vente[k]) == n for k in ("pieces", "prix", "optimal"))):
        raise RequeteInvalide("Données de vente invalides pour cette facture.")
    for i, cat in enumerate(categories):
        pieces = vente["pieces"][i]
        if not isinstance(pieces, int) or not 1 <= pieces <= 10000:
            raise RequeteInvalide("Nombre de pièces invalide.")
        if cat == "vente" and not all(isinstance(vente[k][i], (int, float)) and 0 <= vente[k][i] <= 100000
                                      for k in ("prix", "optimal")):
            raise RequeteInvalide("Prix de vente invalide.")
    vente["reglages"] = {k: str(vente["reglages"].get(k, ""))[:12] for k in ("marge", "margeType", "taxe", "arrondi")}
    return vente


def nom_recap(nom_facture, categorie):
    """« 18-09-2026.pdf » + event -> « 18-09-2026 - EVENT.pdf »"""
    return f"{nom_facture.removesuffix('.pdf')} - {CATEGORIES[categorie][0]}.pdf"


def nom_bilan(nom_facture):
    """« 18-09-2026.pdf » -> « 18-09-2026 - BILAN FINAL.pdf »"""
    return f"{nom_facture.removesuffix('.pdf')} - {NOM_BILAN}.pdf"


def nom_ventes(nom_facture):
    """« 18-09-2026.pdf » -> « 18-09-2026 - BILAN VENTES.pdf »"""
    return f"{nom_facture.removesuffix('.pdf')} - {NOM_VENTES}.pdf"


def conducteur_url():
    return request.args.get("conducteur", "")[:CONDUCTEUR_MAX].strip() or None


TEXTE = {"Content-Type": "text/plain; charset=utf-8"}


def facture_en_cache(empreinte):
    with _VERROU_FACTURES:
        return FACTURES.get(empreinte)


def categories_url():
    return [c for c in request.args.get("categories", "").split(",") if c]


NOTE_MAX = 1000


def lire_notes(brut):
    """Notes saisies pour les PDF : {"bilan": "…", "event": "…"} (la facture d'origine n'en a pas)."""
    try:
        notes = json.loads(brut or "{}")
    except ValueError as exc:
        raise RequeteInvalide("Notes illisibles.") from exc
    if not isinstance(notes, dict) or set(notes) - (DOCUMENTS.keys() - {"facture"}):
        raise RequeteInvalide("Notes invalides.")
    return {doc: str(texte or "")[:NOTE_MAX] for doc, texte in notes.items()}


@app.get("/api/recap/<empreinte>/<categorie>")
def apercu_recap(empreinte, categorie):
    """PDF d'une catégorie, ouvert dans un nouvel onglet :
    ?nom=JJ-MM-AAAA.pdf&categories=vente,event,…&note=…&conducteur=…"""
    data = facture_en_cache(empreinte)
    if data is None:
        return "Facture introuvable : rechargez-la dans l'application.", 404, TEXTE
    nom = request.args.get("nom", "")
    try:
        facture, groupes, _ = preparer(data, nom, categories_url())
    except RequeteInvalide as exc:
        return str(exc), 400, TEXTE
    if categorie not in groupes:
        return "Aucune ligne dans cette catégorie.", 404, TEXTE
    pdf = generer_recap(facture, categorie, groupes[categorie], nom, request.args.get("note", "")[:NOTE_MAX],
                        request.args.get("conducteur", "")[:CONDUCTEUR_MAX].strip() or None)
    return send_file(io.BytesIO(pdf), mimetype="application/pdf", download_name=nom_recap(nom, categorie))


@app.get("/api/bilan/<empreinte>")
def apercu_bilan(empreinte):
    """Bilan final (infos de la facture), ouvert dans un nouvel onglet : ?nom=…&categories=…&note=…&conducteur=…"""
    data = facture_en_cache(empreinte)
    if data is None:
        return "Facture introuvable : rechargez-la dans l'application.", 404, TEXTE
    nom = request.args.get("nom", "")
    try:
        facture, _, categories = preparer(data, nom, categories_url())
    except RequeteInvalide as exc:
        return str(exc), 400, TEXTE
    pdf = generer_bilan(facture, categories, nom, g.utilisateur["nom"], request.args.get("note", "")[:NOTE_MAX],
                        conducteur_url())
    return send_file(io.BytesIO(pdf), mimetype="application/pdf", download_name=nom_bilan(nom))


@app.get("/api/ventes/<empreinte>")
def apercu_ventes(empreinte):
    """Bilan des ventes, ouvert dans un nouvel onglet : ?nom=…&categories=…&vente={json}&note=…&conducteur=…"""
    data = facture_en_cache(empreinte)
    if data is None:
        return "Facture introuvable : rechargez-la dans l'application.", 404, TEXTE
    nom = request.args.get("nom", "")
    try:
        facture, _, categories = preparer(data, nom, categories_url())
        vente = lire_vente(request.args.get("vente"), facture, categories)
    except RequeteInvalide as exc:
        return str(exc), 400, TEXTE
    pdf = generer_ventes(facture, categories, vente, nom, g.utilisateur["nom"], request.args.get("note", "")[:NOTE_MAX],
                         conducteur_url())
    return send_file(io.BytesIO(pdf), mimetype="application/pdf", download_name=nom_ventes(nom))


@app.post("/api/nextcloud/envoyer")
def envoyer():
    """Envoie la facture renommée, son bilan final, son bilan des ventes, puis un PDF par catégorie utilisée.

    Le conducteur est obligatoire. Rangement « facture » : tout va dans un dossier
    « AAAA_MM_DD - total TTC » créé dans le dossier principal. Rangement « type » : chaque PDF va
    dans le dossier choisi pour son type (dossier principal par défaut).
    Les autres PDF suivent le nom final de la facture (« 30-09-2026 (2) - EVENT.pdf »), sont
    remplacés à chaque envoi, et ceux d'une catégorie qui n'a plus de ligne sont supprimés.
    """
    fichier = request.files.get("fichier")
    if not fichier:
        raise RequeteInvalide("Aucun fichier reçu.")
    conducteur = lire_conducteur(request.form.get("conducteur"))
    try:
        categories = json.loads(request.form.get("categories") or "[]")
    except ValueError as exc:
        raise RequeteInvalide("Catégories illisibles.") from exc
    data = fichier.read()
    nom = (request.form.get("nom") or "").strip()
    facture, groupes, categories = preparer(data, nom, categories)
    vente = lire_vente(request.form.get("vente"), facture, categories)
    notes = lire_notes(request.form.get("notes"))

    cfg = load_config()
    nc = client(cfg)
    par_facture = cfg["rangement"] == "facture"
    dossier_facture = clean_path(f"{cfg['dossier']}/{nom_dossier_facture(nom, facture)}")

    def dossier(document):
        return dossier_facture if par_facture else dossier_de(cfg, document)

    resultat = nc.upload(dossier("facture"), nom, data)  # crée le dossier si besoin
    resultat["dossier"] = "/" + dossier_facture if par_facture else None
    base = resultat["nom"]
    dossiers_prets = {dossier("facture")}

    def deposer(document, nom_fichier, pdf):
        cible = dossier(document)
        if cible not in dossiers_prets:
            nc.make_dirs(cible)
            dossiers_prets.add(cible)
        return nc.put(cible, nom_fichier, pdf)

    resultat["bilan"] = deposer("bilan", nom_bilan(base), generer_bilan(
        facture, categories, base, g.utilisateur["nom"], notes.get("bilan"), conducteur))
    resultat["ventes"] = deposer("ventes", nom_ventes(base), generer_ventes(
        facture, categories, vente, base, g.utilisateur["nom"], notes.get("ventes"), conducteur))
    resultat["recaps"], resultat["supprimes"] = [], []
    for cat in CATEGORIES:
        nom_cat = nom_recap(base, cat)
        if cat in groupes:
            resultat["recaps"].append(deposer(cat, nom_cat, generer_recap(
                facture, cat, groupes[cat], base, notes.get(cat), conducteur)))
        elif nc.delete(dossier(cat), nom_cat):
            resultat["supprimes"].append(nom_cat)
    log.info("%s a envoyé %s (conducteur %s ; %s)", g.utilisateur["nom"], resultat["chemin"], conducteur,
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
