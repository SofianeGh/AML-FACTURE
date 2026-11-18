"""Trésorerie : mandats, classeurs, transactions du relevé, justificatifs, compte de résultat et exports.

Reprend l'API d'AML Trésorerie (sous /api/treso/…). En plus :
- une transaction peut recevoir comme justificatif une note de frais ou une facture de l'application ;
  la note passe alors à « Remboursée » (débit) et la facture à « Payée » (crédit) ;
- plusieurs transactions peuvent être classées d'un coup ;
- une transaction peut être répartie sur plusieurs classeurs (versement HelloAsso de plusieurs
  billetteries, versement du TPE qui mélange un événement et les ventes habituelles, frais déduits…).
"""
import io
import mimetypes
import posixpath
import re

from flask import Blueprint, g, jsonify, request, send_file

from ..aml.association import association
from ..aml.champs import date_iso, nombre, texte
from ..aml.devis import nom_fichier as nom_fichier_piece
from ..aml.ndf import nom_fichier as nom_fichier_note
from ..commun import RequeteInvalide, client, erreur, load_config, log, stockage, tresorerie
from ..nextcloud import NextcloudError
from ..treso.exports import export_csv, export_excel, export_pdf
from ..treso.releve import ReleveIllisible, lire_releve
from ..treso.stockage import LIENS, PARTS_MAX, centimes
from .devis import pdf_piece
from .ndf import pdf_note

bp = Blueprint("treso", __name__)
TEXTE = {"Content-Type": "text/plain; charset=utf-8"}
RELEVE_MAX = 5 * 1024 * 1024
JUSTIFICATIF_MAX = 15 * 1024 * 1024
# types affichés dans le navigateur ; les autres sont proposés au téléchargement (jamais exécutés)
AFFICHABLES = {"application/pdf", "image/jpeg", "image/png", "image/gif", "image/webp"}
STATUTS_AUTO = {"ndf": ("remboursee", "Remboursée"), "facture": ("payee", "Payée")}


def _entier(valeur, libelle, obligatoire=True):
    if valeur in (None, ""):
        if obligatoire:
            raise RequeteInvalide(f"{libelle} manquant.")
        return None
    if isinstance(valeur, bool):
        raise RequeteInvalide(f"{libelle} invalide.")
    try:
        return int(valeur)
    except (TypeError, ValueError) as exc:
        raise RequeteInvalide(f"{libelle} invalide.") from exc


def _mandat(valeur):
    mandat = tresorerie().mandat(_entier(valeur, "Mandat"))
    if mandat is None:
        raise RequeteInvalide("Mandat introuvable.")
    return mandat


def _operation(id_):
    op = tresorerie().operation(id_)
    if op is None:
        raise RequeteInvalide("Transaction introuvable.")
    return op


# ---------------------------------------------------------------- copie sur Nextcloud

def _nettoyer(nom):
    return re.sub(r'[\\/:*?"<>|]', "-", nom or "").strip() or "-"


def copie_nextcloud(op, nom, contenu):
    """Copie le justificatif dans <mandat>/[3] Trésorerie/<catégorie>/<classeur>/ (comme AML Trésorerie),
    seulement si Nextcloud est configuré. `contenu` : octets, ou fonction qui les fabrique.
    Renvoie (chemin, avertissement) ; une erreur Nextcloud n'empêche pas de garder le justificatif."""
    cfg = load_config()
    if not (cfg["nextcloud_url"] and cfg["nextcloud_login"] and cfg["nextcloud_password"]):
        return None, None
    sans = "Réparti" if op.get("ventilations") else "À classer"  # transaction répartie : pas de classeur unique
    dossier = "/".join(_nettoyer(d) for d in (op["mandat"], "[3] Trésorerie", op["categorie"] or sans,
                                               op["classeur"] or sans))
    try:
        nc = client(cfg)
        nc.make_dirs(dossier)
        res = nc.put(dossier, f"{op['date']}_op{op['id']}_{_nettoyer(nom)}", contenu() if callable(contenu) else contenu)
        return res["chemin"], None
    except NextcloudError as exc:
        return None, f"Justificatif gardé dans l'application, mais copie sur Nextcloud impossible : {exc}"


# ---------------------------------------------------------------- mandats, catégories, classeurs

@bp.get("/api/treso/mandats")
def mandats():
    return jsonify(tresorerie().mandats())


@bp.post("/api/treso/mandats")
def creer_mandat():
    data = request.get_json(silent=True) or {}
    nom = texte(data, "nom", 50, "Nom du mandat", obligatoire=True)
    debut, fin = date_iso(data, "debut", "Début"), date_iso(data, "fin", "Fin")
    if fin < debut:
        raise RequeteInvalide("La fin du mandat doit être après son début.")
    copier_de = _entier(data.get("copier_de"), "Mandat à reprendre", obligatoire=False)
    if copier_de is not None:
        _mandat(copier_de)
    id_ = tresorerie().creer_mandat(nom, debut, fin, copier_de)
    log.info("%s a créé le mandat %s", g.utilisateur["nom"], nom)
    return jsonify({"id": id_})


@bp.get("/api/treso/categories")
def categories():
    return jsonify(tresorerie().categories())


@bp.get("/api/treso/classeurs")
def classeurs():
    return jsonify(tresorerie().classeurs(_mandat(request.args.get("mandat"))["id"]))


@bp.post("/api/treso/classeurs")
def creer_classeur():
    data = request.get_json(silent=True) or {}
    id_ = tresorerie().creer_classeur(_entier(data.get("mandat_id"), "Mandat"),
                                      _entier(data.get("categorie_id"), "Catégorie"),
                                      texte(data, "nom", 150, "Nom du classeur", obligatoire=True))
    return jsonify({"id": id_})


@bp.delete("/api/treso/classeurs/<int:id_>")
def supprimer_classeur(id_):
    tresorerie().supprimer_classeur(id_)
    return jsonify({"ok": True})


# ---------------------------------------------------------------- transactions

@bp.get("/api/treso/operations")
def operations():
    mois = request.args.get("mois") or None
    if mois and not re.fullmatch(r"\d{4}-\d{2}", mois):
        raise RequeteInvalide("Mois attendu au format AAAA-MM.")
    return jsonify(tresorerie().operations(
        _mandat(request.args.get("mandat"))["id"], mois=mois,
        classeur_id=_entier(request.args.get("classeur"), "Classeur", obligatoire=False),
        a_classer=request.args.get("a_classer") in ("1", "true")))


@bp.post("/api/treso/operations/import")
def importer():
    """Relevé CSV d'un mois -> transactions ; les lignes déjà importées sont ignorées."""
    mandat = _mandat(request.form.get("mandat"))
    fichier = request.files.get("fichier")
    if not fichier:
        raise RequeteInvalide("Aucun fichier reçu.")
    data = fichier.read(RELEVE_MAX + 1)
    if len(data) > RELEVE_MAX:
        raise RequeteInvalide("Relevé trop gros (5 Mo maximum).")
    try:
        lignes = lire_releve(data)
    except ReleveIllisible as exc:
        raise RequeteInvalide(str(exc)) from exc
    ajoutees = tresorerie().importer(mandat["id"], lignes)
    hors = sum(1 for l in lignes if not mandat["debut"] <= l.date <= mandat["fin"])
    log.info("%s a importé %s (%s lignes, %s ajoutées) dans le mandat %s", g.utilisateur["nom"],
             fichier.filename, len(lignes), ajoutees, mandat["nom"])
    return jsonify({"lues": len(lignes), "ajoutees": ajoutees, "doublons": len(lignes) - ajoutees,
                    "hors_mandat": hors})


def _lire_parts(valeur):
    """[{classeur_id, montant, commentaire}, …] -> [(classeur_id, centimes, commentaire)] ; None = pas de répartition."""
    if not valeur:
        return None
    if not isinstance(valeur, list) or len(valeur) > PARTS_MAX:
        raise RequeteInvalide("Répartition illisible.")
    parts = []
    for i, part in enumerate(valeur, 1):
        if not isinstance(part, dict):
            raise RequeteInvalide(f"Part {i} illisible.")
        parts.append((_entier(part.get("classeur_id"), f"Part {i} : classeur"),
                      centimes(nombre(part.get("montant"), f"Part {i} : montant", -1_000_000, 1_000_000)),
                      texte(part, "commentaire", 200, f"Part {i} : note")))
    return parts


@bp.put("/api/treso/operations/<int:id_>")
def modifier_operation(id_):
    """Motif, commentaire et classement : un classeur, ou une répartition (« ventilations ») sur plusieurs."""
    data = request.get_json(silent=True) or {}
    tresorerie().modifier_operation(id_, _entier(data.get("classeur_id"), "Classeur", obligatoire=False),
                                    texte(data, "commentaire", 1000, "Commentaire", lignes=10),
                                    texte(data, "libelle", 300, "Motif"), g.utilisateur["nom"],
                                    ventilations=_lire_parts(data.get("ventilations")))
    return jsonify(tresorerie().operation(id_))


@bp.post("/api/treso/operations/classer")
def classer_plusieurs():
    """{ids: [...], classeur_id} : classe d'un coup les transactions cochées (classeur vide = « à classer »)."""
    data = request.get_json(silent=True) or {}
    ids = data.get("ids")
    if not isinstance(ids, list) or not 1 <= len(ids) <= 1000:
        raise RequeteInvalide("Choisissez au moins une transaction.")
    ids = [_entier(i, "Transaction") for i in ids]
    classees, ignorees = tresorerie().classer(ids, _entier(data.get("classeur_id"), "Classeur", obligatoire=False),
                                              g.utilisateur["nom"])
    log.info("%s a classé %s transactions d'un coup", g.utilisateur["nom"], classees)
    return jsonify({"classees": classees, "reparties_ignorees": ignorees})


@bp.delete("/api/treso/operations/<int:id_>")
def supprimer_operation(id_):
    tresorerie().supprimer_operation(id_)
    return jsonify({"ok": True})


# ---------------------------------------------------------------- justificatifs

@bp.post("/api/treso/operations/<int:id_>/justificatifs")
def ajouter_justificatif(id_):
    """Fichier joint à la transaction (photo, PDF…), gardé dans la base et copié sur Nextcloud si configuré."""
    op = _operation(id_)
    fichier = request.files.get("fichier")
    if not fichier:
        raise RequeteInvalide("Aucun fichier reçu.")
    data = fichier.read(JUSTIFICATIF_MAX + 1)
    if not data:
        raise RequeteInvalide("Fichier vide.")
    if len(data) > JUSTIFICATIF_MAX:
        raise RequeteInvalide("Fichier trop gros (15 Mo maximum).")
    nom = posixpath.basename((fichier.filename or "justificatif").replace("\\", "/")) or "justificatif"
    type_ = fichier.mimetype if fichier.mimetype not in (None, "", "application/octet-stream") \
        else mimetypes.guess_type(nom)[0] or "application/octet-stream"
    chemin, avertissement = copie_nextcloud(op, nom, data)
    jid = tresorerie().ajouter_justificatif(id_, nom, type_, contenu=data, auteur=g.utilisateur["nom"],
                                            chemin_nextcloud=chemin)
    return jsonify({"id": jid, "nextcloud": chemin, "avertissement": avertissement})


@bp.get("/api/treso/operations/<int:id_>/documents")
def documents(id_):
    """Notes de frais et factures qu'on peut joindre à la transaction ; celles du même montant d'abord."""
    op = _operation(id_)
    montant = abs(op["montant"])
    joints = {(j["lien_type"], j["lien_id"]) for o in tresorerie().operations(op["mandat_id"]) if o["id"] == id_
              for j in o["justificatifs"]}

    def trier(docs):
        docs.sort(key=lambda d: d["date"], reverse=True)
        docs.sort(key=lambda d: not d["identique"])  # tri stable : même montant d'abord, puis le plus récent
        return docs

    ndf = trier([{"type": "ndf", "id": n["id"], "titre": f"{n['personne']} · {n['objet']}", "date": n["date"],
                  "montant": n["total_ttc"], "statut": n["statut"], "identique": abs(n["total_ttc"] - montant) < 0.005,
                  "joint": ("ndf", n["id"]) in joints} for n in stockage().lister_ndf()])
    factures = trier([{"type": "facture", "id": p["id"], "titre": f"{p['numero']} · {p['client']}", "date": p["date"],
                       "montant": p["total_ttc"], "statut": p["statut"],
                       "identique": abs(p["total_ttc"] - montant) < 0.005, "joint": ("facture", p["id"]) in joints}
                      for p in stockage().lister_pieces() if p["type"] == "facture"])
    return jsonify({"ndf": ndf, "factures": factures, "debit": op["montant"] < 0})


@bp.post("/api/treso/operations/<int:id_>/liens")
def lier_document(id_):
    """Joint une note de frais ou une facture ; met son suivi à jour (remboursée / payée) selon le sens."""
    op = _operation(id_)
    data = request.get_json(silent=True) or {}
    type_ = data.get("type")
    if type_ not in LIENS:
        raise RequeteInvalide("Type de document invalide.")
    doc_id = _entier(data.get("id"), "Document")
    asso = association()
    if type_ == "ndf":
        doc = stockage().note_frais(doc_id)
        if doc is None:
            raise RequeteInvalide("Note de frais introuvable.")
        nom, fabriquer, a_jour = nom_fichier_note(doc, asso["sigle"]), lambda: pdf_note(doc)[0], op["montant"] < 0
    else:
        doc = stockage().piece(doc_id)
        if doc is None or doc["type"] != "facture":
            raise RequeteInvalide("Facture introuvable.")
        nom, fabriquer, a_jour = nom_fichier_piece(doc), lambda: pdf_piece(doc)[0], op["montant"] > 0
    chemin, avertissement = copie_nextcloud(op, nom, fabriquer)
    jid = tresorerie().ajouter_justificatif(id_, nom, "application/pdf", lien_type=type_, lien_id=doc_id,
                                            auteur=g.utilisateur["nom"], chemin_nextcloud=chemin)
    statut = None
    cle, libelle = STATUTS_AUTO[type_]
    if a_jour and doc["statut"] != cle:
        (stockage().statut_ndf if type_ == "ndf" else stockage().statut_piece)(doc_id, cle, g.utilisateur["nom"])
        statut = libelle
    log.info("%s a joint %s %s à la transaction %s", g.utilisateur["nom"], type_, doc_id, id_)
    return jsonify({"id": jid, "statut": statut, "nextcloud": chemin, "avertissement": avertissement})


@bp.get("/api/treso/justificatifs/<int:id_>")
def voir_justificatif(id_):
    j = tresorerie().justificatif(id_)
    if j is None:
        return "Justificatif introuvable.", 404, TEXTE
    nom, type_ = j["nom"], j["type"]
    if j["lien_type"] == "ndf":
        note = stockage().note_frais(j["lien_id"])
        if note is None:
            return "Cette note de frais a été supprimée.", 404, TEXTE
        contenu, nom = pdf_note(note)
    elif j["lien_type"] == "facture":
        piece = stockage().piece(j["lien_id"])
        if piece is None:
            return "Cette facture a été supprimée.", 404, TEXTE
        contenu, nom = pdf_piece(piece)
    else:
        contenu = j["contenu"]
    affichable = type_ in AFFICHABLES
    return send_file(io.BytesIO(contenu), mimetype=type_ if affichable else "application/octet-stream",
                     download_name=nom, as_attachment=not affichable)


@bp.delete("/api/treso/justificatifs/<int:id_>")
def supprimer_justificatif(id_):
    """Retire le justificatif de la transaction (la note ou la facture elle-même n'est pas supprimée)."""
    tresorerie().supprimer_justificatif(id_)
    return jsonify({"ok": True})


# ---------------------------------------------------------------- compte de résultat

@bp.get("/api/treso/compte-resultat")
def compte_resultat():
    return jsonify(tresorerie().compte_resultat(_mandat(request.args.get("mandat"))["id"]))


@bp.get("/api/treso/compte-resultat/export")
def exporter():
    """?mandat=…&format=pdf|xlsx|csv"""
    mandat = _mandat(request.args.get("mandat"))
    cr = tresorerie().compte_resultat(mandat["id"])
    format_ = request.args.get("format", "pdf")
    nom = f"Compte de resultat {mandat['nom']}".replace(" ", "_").replace("/", "-")
    if format_ == "csv":
        return send_file(io.BytesIO(export_csv(cr)), mimetype="text/csv", download_name=f"{nom}.csv",
                         as_attachment=True)
    if format_ == "xlsx":
        return send_file(io.BytesIO(export_excel(cr, mandat)), download_name=f"{nom}.xlsx", as_attachment=True,
                         mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    if format_ == "pdf":
        return send_file(io.BytesIO(export_pdf(cr, mandat, association())), mimetype="application/pdf",
                         download_name=f"{nom}.pdf")
    return erreur("Format inconnu (pdf, xlsx ou csv).")
