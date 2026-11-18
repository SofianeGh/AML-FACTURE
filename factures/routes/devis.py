"""Devis et factures de l'association : coordonnées, liste, numérotation, enregistrement, PDF."""
import io
from datetime import date, timedelta

from flask import Blueprint, g, jsonify, request, send_file

from ..aml.association import association, lire_association
from ..aml.champs import date_iso
from ..aml.devis import STATUTS, TYPES, calculer, lire_numero, lire_piece, nom_fichier, numero_de
from ..commun import RequeteInvalide, erreur, log, stockage, tresorerie
from ..pdf.devis import generer_piece
from ..securite import admin_requis

bp = Blueprint("devis", __name__)
TEXTE = {"Content-Type": "text/plain; charset=utf-8"}


def _prefixe(type_, asso):
    return asso["prefixe_devis" if type_ == "devis" else "prefixe_facture"]


# ---------------------------------------------------------------- coordonnées de l'association

@bp.get("/api/association")
def lire_coordonnees():
    return jsonify(association())


@bp.put("/api/association")
@admin_requis
def ecrire_coordonnees():
    valeurs = lire_association(request.get_json(silent=True))
    stockage().definir_reglage("association", valeurs)
    log.info("%s a modifié les coordonnées de l'association", g.utilisateur["nom"])
    return jsonify(association())


# ---------------------------------------------------------------- devis et factures

@bp.get("/api/devis")
def lister():
    """Devis et factures ; pour une facture, les transactions de la trésorerie où elle est jointe."""
    liens = tresorerie().rapprochements("facture")
    return jsonify([{**p, "rapprochements": liens.get(p["id"], []) if p["type"] == "facture" else []}
                    for p in stockage().lister_pieces()])


@bp.get("/api/devis/clients")
def clients():
    return jsonify(stockage().clients())


@bp.get("/api/devis/nouveau")
def nouveau():
    """Valeurs proposées pour un nouveau document : ?type=devis|facture&date=AAAA-MM-JJ"""
    type_ = request.args.get("type")
    if type_ not in TYPES:
        raise RequeteInvalide("Type de document invalide.")
    jour = date_iso(request.args, "date", "Date", obligatoire=False) or date.today().isoformat()
    asso, d = association(), date.fromisoformat(jour)
    valeurs = {"date": jour,
               "numero": numero_de(_prefixe(type_, asso), d.year, stockage().prochain_rang(type_, d.year))}
    if type_ == "devis":
        valeurs["validite"] = (d + timedelta(days=asso["validite_jours"])).isoformat()
    else:
        valeurs["echeance"] = (d + timedelta(days=asso["echeance_jours"])).isoformat()
        valeurs["conditions"] = asso["conditions_facture"]
    return jsonify(valeurs)


@bp.get("/api/devis/<int:id_>")
def lire(id_):
    piece = stockage().piece(id_)
    return jsonify(piece) if piece else erreur("Document introuvable.", 404)


@bp.post("/api/devis")
def creer():
    data = request.get_json(silent=True)
    piece = lire_piece(data)
    numero, annee, rang = lire_numero(data.get("numero"), _prefixe(piece["type"], association()))
    devis_id = data.get("devis_id")
    if devis_id is not None:  # facture établie d'après un devis
        source = stockage().piece(devis_id) if isinstance(devis_id, int) and not isinstance(devis_id, bool) else None
        if piece["type"] != "facture" or source is None or source["type"] != "devis":
            raise RequeteInvalide("Devis d'origine introuvable.")
        piece["devis_numero"] = source["numero"]
    id_ = stockage().enregistrer_piece(piece, numero, annee, rang, calculer(piece)["total_ttc"],
                                       g.utilisateur["nom"], devis_id=devis_id)
    log.info("%s a créé %s %s", g.utilisateur["nom"], TYPES[piece["type"]].lower(), numero)
    return jsonify(stockage().piece(id_))


@bp.put("/api/devis/<int:id_>")
def modifier(id_):
    ancien = stockage().piece(id_)
    if ancien is None:
        return erreur("Document introuvable.", 404)
    data = request.get_json(silent=True)
    piece = lire_piece(data)
    if piece["type"] != ancien["type"]:
        raise RequeteInvalide("Le type d'un document ne peut pas changer.")
    if "".join(str(data.get("numero") or "").split()).upper() == ancien["numero"]:
        numero, annee, rang = ancien["numero"], ancien["annee"], ancien["rang"]  # même si le préfixe a changé
    else:
        numero, annee, rang = lire_numero(data.get("numero"), _prefixe(piece["type"], association()))
    if ancien.get("devis_numero"):
        piece["devis_numero"] = ancien["devis_numero"]
    stockage().enregistrer_piece(piece, numero, annee, rang, calculer(piece)["total_ttc"], g.utilisateur["nom"],
                                 id_=id_)
    log.info("%s a modifié %s %s", g.utilisateur["nom"], TYPES[piece["type"]].lower(), numero)
    return jsonify(stockage().piece(id_))


@bp.post("/api/devis/<int:id_>/statut")
def changer_statut(id_):
    piece = stockage().piece(id_)
    if piece is None:
        return erreur("Document introuvable.", 404)
    statut = (request.get_json(silent=True) or {}).get("statut")
    if statut not in STATUTS[piece["type"]]:
        raise RequeteInvalide("Suivi invalide.")
    stockage().statut_piece(id_, statut, g.utilisateur["nom"])
    return jsonify({"ok": True})


@bp.delete("/api/devis/<int:id_>")
def supprimer(id_):
    piece = stockage().piece(id_)
    if piece is None:
        return erreur("Document introuvable.", 404)
    if piece["type"] == "facture" and piece["rang"] < stockage().prochain_rang("facture", piece["annee"]) - 1:
        raise RequeteInvalide("Seule la dernière facture de l'année peut être supprimée : les numéros de facture "
                              "doivent se suivre sans trou. Pour annuler celle-ci, faites une facture d'avoir.")
    stockage().supprimer_piece(id_)
    tresorerie().retirer_liens("facture", id_)
    log.info("%s a supprimé %s %s", g.utilisateur["nom"], TYPES[piece["type"]].lower(), piece["numero"])
    return jsonify({"ok": True})


def pdf_piece(piece):
    """(PDF, nom du fichier) d'un devis ou d'une facture."""
    return generer_piece(piece, calculer(piece), association()), nom_fichier(piece)


@bp.get("/api/devis/<int:id_>/pdf")
def pdf(id_):
    """PDF du document (affiché dans le navigateur ; ?telecharger=1 pour l'enregistrer)."""
    piece = stockage().piece(id_)
    if piece is None:
        return "Document introuvable.", 404, TEXTE
    contenu, nom = pdf_piece(piece)
    return send_file(io.BytesIO(contenu), mimetype="application/pdf", download_name=nom,
                     as_attachment=request.args.get("telecharger") == "1")
