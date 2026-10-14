"""Application web : factures METRO -> prix TTC + marge, archivage sur Nextcloud."""
import hashlib
import io
import json
import os
import re
from collections import OrderedDict
from pathlib import Path

from flask import Flask, jsonify, request, send_file, send_from_directory

from metro_parser import FactureIllisible, parse_pdf
from nextcloud import Nextcloud, NextcloudError, base_url, clean_path
from recap_pdf import CATEGORIES, generer_recap

ROOT = Path(__file__).resolve().parent
CONFIG_FILE = ROOT / "config.json"
DEFAULTS = {
    "nextcloud_url": "",
    "nextcloud_login": "",
    "nextcloud_password": "",
    "nextcloud_user_id": "",
    "dossier": "Factures/Metro",
}

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024

# Dernières factures analysées (empreinte -> PDF), pour ouvrir les aperçus par simple lien
FACTURES = OrderedDict()
FACTURES_MAX = 50


def garder_facture(data):
    empreinte = hashlib.sha1(data).hexdigest()
    FACTURES[empreinte] = data
    FACTURES.move_to_end(empreinte)
    while len(FACTURES) > FACTURES_MAX:
        FACTURES.popitem(last=False)
    return empreinte


def load_config():
    cfg = dict(DEFAULTS)
    if CONFIG_FILE.exists():
        cfg.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
    return cfg


def save_config(cfg):
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


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


@app.errorhandler(NextcloudError)
def _nextcloud_error(exc):
    return erreur(str(exc), 502)


@app.errorhandler(413)
def _trop_gros(_exc):
    return erreur("Fichier trop volumineux (25 Mo maximum).", 413)


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
    data = request.get_json(force=True) or {}
    cfg = load_config()
    if "nextcloud_url" in data:
        cfg["nextcloud_url"] = base_url(data["nextcloud_url"]) if data["nextcloud_url"].strip() else ""
    if "nextcloud_login" in data:
        cfg["nextcloud_login"] = data["nextcloud_login"].strip()
    if data.get("nextcloud_password"):  # vide = on garde l'ancien
        cfg["nextcloud_password"] = data["nextcloud_password"]
    if "dossier" in data:
        cfg["dossier"] = clean_path(data["dossier"])

    if {"nextcloud_url", "nextcloud_login", "nextcloud_password"} & data.keys():
        cfg["nextcloud_user_id"] = ""
        if cfg["nextcloud_url"] and cfg["nextcloud_login"] and cfg["nextcloud_password"]:
            cfg["nextcloud_user_id"] = client(cfg).check()  # lève NextcloudError si KO
    save_config(cfg)
    return jsonify(public_config(cfg))


@app.get("/api/nextcloud/dossiers")
def lister_dossiers():
    chemin = clean_path(request.args.get("chemin", ""))
    return jsonify({"chemin": chemin, "dossiers": client().list_folders(chemin)})


@app.post("/api/nextcloud/dossiers")
def creer_dossier():
    data = request.get_json(force=True) or {}
    nom = (data.get("nom") or "").strip()
    if not nom or "/" in nom or "\\" in nom:
        return erreur("Nom de dossier invalide.")
    chemin = clean_path(f"{data.get('parent', '')}/{nom}")
    client().make_dirs(chemin)
    return jsonify({"chemin": chemin})


class RequeteInvalide(Exception):
    pass


@app.errorhandler(RequeteInvalide)
def _requete_invalide(exc):
    return erreur(str(exc), 400)


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
    return jsonify(resultat)


if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5000"))
    print(f"Application disponible sur http://{'localhost' if host == '127.0.0.1' else host}:{port}")
    app.run(host=host, port=port, debug=False)
