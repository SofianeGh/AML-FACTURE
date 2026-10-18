"""Réglages : connexion Nextcloud, dossiers, et préférences partagées entre les membres."""
import re

from flask import Blueprint, g, jsonify, request

from ..commun import (CONDUCTEUR_MAX, RequeteInvalide, client, erreur, load_config, log, public_config,
                      save_config, stockage)
from ..nextcloud import base_url, clean_path, dossier_dans_url
from ..pdf import DOCUMENTS

bp = Blueprint("reglages", __name__)

RE_CLE_ARTICLE = re.compile(r"(pieces|prix|local):\d{1,12}")


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


@bp.get("/api/preferences")
def lire_preferences():
    return jsonify(stockage().preferences())


@bp.put("/api/preferences")
def ecrire_preferences():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or len(data) > 500:
        raise RequeteInvalide("Préférences illisibles.")
    stockage().definir_preferences({cle: _valider_preference(cle, v) for cle, v in data.items()},
                                   g.utilisateur["nom"])
    return jsonify({"ok": True})


@bp.get("/api/config")
def lire_config():
    return jsonify(public_config(load_config()))


@bp.post("/api/config")
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


@bp.get("/api/nextcloud/dossiers")
def lister_dossiers():
    chemin = clean_path(request.args.get("chemin", ""))
    return jsonify({"chemin": chemin, "dossiers": client().list_folders(chemin)})


@bp.post("/api/nextcloud/dossiers")
def creer_dossier():
    data = request.get_json(silent=True) or {}
    nom = (data.get("nom") or "").strip()
    if not nom or "/" in nom or "\\" in nom:
        return erreur("Nom de dossier invalide.")
    chemin = clean_path(f"{data.get('parent', '')}/{nom}")
    client().make_dirs(chemin)
    return jsonify({"chemin": chemin})
