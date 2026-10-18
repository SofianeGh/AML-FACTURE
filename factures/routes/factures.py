"""Factures : analyse du PDF METRO, aperçus des PDF générés, envoi sur Nextcloud."""
import hashlib
import io
import json
import re
import threading
from collections import OrderedDict

from flask import Blueprint, g, jsonify, render_template, request, send_file

from ..commun import (CONDUCTEUR_MAX, RequeteInvalide, client, dossier_de, erreur, lire_conducteur, load_config,
                      log)
from ..metro import FactureIllisible, parse_pdf
from ..nextcloud import clean_path
from ..pdf import CATEGORIES, DOCUMENTS, NOM_BILAN, NOM_VENTES, generer_bilan, generer_recap, generer_ventes

bp = Blueprint("factures", __name__)

# Dernières factures analysées (empreinte -> PDF), pour ouvrir les aperçus par simple lien.
# Gardées en mémoire : lancer un seul processus (avec plusieurs threads), voir docs/DEPLOIEMENT.md.
FACTURES = OrderedDict()
FACTURES_MAX = 50
_VERROU_FACTURES = threading.Lock()

NOTE_MAX = 1000
TEXTE = {"Content-Type": "text/plain; charset=utf-8"}


def garder_facture(data):
    empreinte = hashlib.sha1(data).hexdigest()
    with _VERROU_FACTURES:
        FACTURES[empreinte] = data
        FACTURES.move_to_end(empreinte)
        while len(FACTURES) > FACTURES_MAX:
            FACTURES.popitem(last=False)
    return empreinte


def facture_en_cache(empreinte):
    with _VERROU_FACTURES:
        return FACTURES.get(empreinte)


def nom_dossier_facture(nom, facture):
    """« 03-10-2026.pdf » + total 959,74 € -> « 2026_10_03 - 959,74 € »"""
    jour, mois, annee = nom.removesuffix(".pdf").split("-")
    total = facture["total_ttc"]
    if total is None:
        total = sum(l["montant_net_ht"] * (1 + (l["tva_taux"] or 0) / 100) for l in facture["lignes"])
    return f"{annee}_{mois}_{jour} - {total:.2f} €".replace(".", ",")


def nom_recap(nom_facture, categorie):
    """« 18-09-2026.pdf » + event -> « 18-09-2026 - EVENT.pdf »"""
    return f"{nom_facture.removesuffix('.pdf')} - {CATEGORIES[categorie][0]}.pdf"


def nom_bilan(nom_facture):
    """« 18-09-2026.pdf » -> « 18-09-2026 - BILAN FINAL.pdf »"""
    return f"{nom_facture.removesuffix('.pdf')} - {NOM_BILAN}.pdf"


def nom_ventes(nom_facture):
    """« 18-09-2026.pdf » -> « 18-09-2026 - BILAN VENTES.pdf »"""
    return f"{nom_facture.removesuffix('.pdf')} - {NOM_VENTES}.pdf"


# ---------------------------------------------------------------- lecture des données envoyées

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
    """Choix de vente faits dans l'interface, pour le bilan des ventes : une valeur par ligne pour
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


def lire_notes(brut):
    """Notes saisies pour les PDF : {"bilan": "…", "event": "…"} (la facture d'origine n'en a pas)."""
    try:
        notes = json.loads(brut or "{}")
    except ValueError as exc:
        raise RequeteInvalide("Notes illisibles.") from exc
    if not isinstance(notes, dict) or set(notes) - (DOCUMENTS.keys() - {"facture"}):
        raise RequeteInvalide("Notes invalides.")
    return {doc: str(texte or "")[:NOTE_MAX] for doc, texte in notes.items()}


def categories_url():
    return [c for c in request.args.get("categories", "").split(",") if c]


def conducteur_url():
    return request.args.get("conducteur", "")[:CONDUCTEUR_MAX].strip() or None


def note_url():
    return request.args.get("note", "")[:NOTE_MAX]


# ---------------------------------------------------------------- pages et analyse

@bp.get("/")
def index():
    return render_template("index.html")


@bp.post("/api/factures")
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


# ---------------------------------------------------------------- aperçus (nouvel onglet)

@bp.get("/api/recap/<empreinte>/<categorie>")
def apercu_recap(empreinte, categorie):
    """PDF d'une catégorie : ?nom=JJ-MM-AAAA.pdf&categories=vente,event,…&note=…&conducteur=…"""
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
    pdf = generer_recap(facture, categorie, groupes[categorie], nom, note_url(), conducteur_url())
    return send_file(io.BytesIO(pdf), mimetype="application/pdf", download_name=nom_recap(nom, categorie))


@bp.get("/api/bilan/<empreinte>")
def apercu_bilan(empreinte):
    """Bilan final (infos de la facture) : ?nom=…&categories=…&note=…&conducteur=…"""
    data = facture_en_cache(empreinte)
    if data is None:
        return "Facture introuvable : rechargez-la dans l'application.", 404, TEXTE
    nom = request.args.get("nom", "")
    try:
        facture, _, categories = preparer(data, nom, categories_url())
    except RequeteInvalide as exc:
        return str(exc), 400, TEXTE
    pdf = generer_bilan(facture, categories, nom, g.utilisateur["nom"], note_url(), conducteur_url())
    return send_file(io.BytesIO(pdf), mimetype="application/pdf", download_name=nom_bilan(nom))


@bp.get("/api/ventes/<empreinte>")
def apercu_ventes(empreinte):
    """Bilan des ventes : ?nom=…&categories=…&vente={json}&note=…&conducteur=…"""
    data = facture_en_cache(empreinte)
    if data is None:
        return "Facture introuvable : rechargez-la dans l'application.", 404, TEXTE
    nom = request.args.get("nom", "")
    try:
        facture, _, categories = preparer(data, nom, categories_url())
        vente = lire_vente(request.args.get("vente"), facture, categories)
    except RequeteInvalide as exc:
        return str(exc), 400, TEXTE
    pdf = generer_ventes(facture, categories, vente, nom, g.utilisateur["nom"], note_url(), conducteur_url())
    return send_file(io.BytesIO(pdf), mimetype="application/pdf", download_name=nom_ventes(nom))


# ---------------------------------------------------------------- envoi sur Nextcloud

@bp.post("/api/nextcloud/envoyer")
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
