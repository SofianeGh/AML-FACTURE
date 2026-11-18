"""Notes de frais : liste, enregistrement, justificatifs, signature et PDF."""
import base64
import io

from flask import Blueprint, g, jsonify, request, send_file

from ..aml.association import association
from ..aml.ndf import STATUTS, lire_note, lire_signature, nom_fichier, preparer_justificatif, resume
from ..commun import RequeteInvalide, erreur, log, stockage, tresorerie
from ..pdf.ndf import generer_ndf

bp = Blueprint("ndf", __name__)
TEXTE = {"Content-Type": "text/plain; charset=utf-8"}


@bp.get("/api/ndf")
def lister():
    """Notes de frais, avec les transactions de la trésorerie où elles sont jointes (« rapprochements »)."""
    liens = tresorerie().rapprochements("ndf")
    return jsonify([{**n, "rapprochements": liens.get(n["id"], [])} for n in stockage().lister_ndf()])


@bp.get("/api/ndf/<int:id_>")
def lire(id_):
    note = stockage().note_frais(id_)
    if note is None:
        return erreur("Note de frais introuvable.", 404)
    signature = note.pop("signature")
    note["signature"] = f"data:image/png;base64,{base64.b64encode(signature).decode()}" if signature else None
    return jsonify(note)


def _enregistrer(id_=None):
    data = request.get_json(silent=True)
    note = lire_note(data)
    signature = lire_signature(data.get("signature"))
    id_ = stockage().enregistrer_ndf(note, signature, resume(note), g.utilisateur["nom"], id_=id_)
    log.info("%s a enregistré la note de frais n° %s (%s)", g.utilisateur["nom"], id_, resume(note)[1])
    return jsonify({"id": id_})


@bp.post("/api/ndf")
def creer():
    return _enregistrer()


@bp.put("/api/ndf/<int:id_>")
def modifier(id_):
    if stockage().note_frais(id_) is None:
        return erreur("Note de frais introuvable.", 404)
    return _enregistrer(id_)


@bp.post("/api/ndf/<int:id_>/statut")
def changer_statut(id_):
    if stockage().note_frais(id_) is None:
        return erreur("Note de frais introuvable.", 404)
    statut = (request.get_json(silent=True) or {}).get("statut")
    if statut not in STATUTS:
        raise RequeteInvalide("Suivi invalide.")
    stockage().statut_ndf(id_, statut, g.utilisateur["nom"])
    return jsonify({"ok": True})


@bp.delete("/api/ndf/<int:id_>")
def supprimer(id_):
    note = stockage().note_frais(id_)
    if note is None:
        return erreur("Note de frais introuvable.", 404)
    stockage().supprimer_ndf(id_)
    tresorerie().retirer_liens("ndf", id_)
    log.info("%s a supprimé la note de frais n° %s", g.utilisateur["nom"], id_)
    return jsonify({"ok": True})


def pdf_note(note):
    """(PDF, nom du fichier) d'une note de frais, avec ses justificatifs en annexe."""
    images = stockage().images_justificatifs([j for d in note["depenses"] for j in d["justificatifs"]])
    annexes = [(i, images[j]) for i, d in enumerate(note["depenses"]) for j in d["justificatifs"] if j in images]
    asso = association()
    return generer_ndf(note, asso, note["signature"], annexes), nom_fichier(note, asso["sigle"])


@bp.get("/api/ndf/<int:id_>/pdf")
def pdf(id_):
    """PDF de la note (affiché dans le navigateur ; ?telecharger=1 pour l'enregistrer)."""
    note = stockage().note_frais(id_)
    if note is None:
        return "Note de frais introuvable.", 404, TEXTE
    contenu, nom = pdf_note(note)
    return send_file(io.BytesIO(contenu), mimetype="application/pdf", download_name=nom,
                     as_attachment=request.args.get("telecharger") == "1")


# ---------------------------------------------------------------- justificatifs

@bp.post("/api/ndf/justificatifs")
def televerser():
    """Un fichier (photo ou PDF) -> [{id, largeur, hauteur}, …] (une image par page)."""
    fichier = request.files.get("fichier")
    if not fichier:
        raise RequeteInvalide("Aucun fichier reçu.")
    data = fichier.read()
    if not data:
        raise RequeteInvalide("Fichier vide.")
    nom = fichier.filename or "justificatif"
    reponse = []
    for contenu, largeur, hauteur in preparer_justificatif(data):
        id_ = stockage().ajouter_justificatif(nom, contenu, largeur, hauteur)
        reponse.append({"id": id_, "largeur": largeur, "hauteur": hauteur})
    return jsonify(reponse)


@bp.get("/api/ndf/justificatifs/<int:id_>")
def voir_justificatif(id_):
    justificatif = stockage().justificatif(id_)
    if justificatif is None:
        return "Justificatif introuvable.", 404, TEXTE
    return send_file(io.BytesIO(justificatif["contenu"]), mimetype="image/jpeg")
