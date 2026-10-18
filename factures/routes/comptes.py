"""Connexion, déconnexion, mot de passe et gestion des comptes."""
from flask import Blueprint, g, jsonify, redirect, render_template, request, session, url_for

from ..commun import erreur, log, stockage
from ..securite import admin_requis, bloque, noter_echec, utilisateur_courant

bp = Blueprint("comptes", __name__)


@bp.get("/connexion")
def page_connexion():
    if utilisateur_courant():
        return redirect(url_for("factures.index"))
    return render_template("connexion.html")


@bp.post("/api/connexion")
def connexion():
    ip = request.remote_addr or "?"
    if bloque(ip):
        return erreur("Trop d'essais : réessayez dans quelques minutes.", 429)
    data = request.get_json(silent=True) or {}
    compte = stockage().authentifier(data.get("nom"), data.get("mot_de_passe"))
    if compte is None:
        noter_echec(ip)
        log.warning("Échec de connexion pour « %s » depuis %s", data.get("nom"), ip)
        return erreur("Identifiant ou mot de passe incorrect.", 401)
    session.clear()
    session["utilisateur"] = compte["nom"]
    session.permanent = True
    log.info("Connexion de %s depuis %s", compte["nom"], ip)
    return jsonify(compte)


@bp.post("/api/deconnexion")
def deconnexion():
    session.clear()
    return jsonify({"ok": True})


@bp.get("/api/moi")
def moi():
    return jsonify(g.utilisateur)


@bp.post("/api/moi/mot-de-passe")
def changer_mon_mot_de_passe():
    data = request.get_json(silent=True) or {}
    if stockage().authentifier(g.utilisateur["nom"], data.get("actuel")) is None:
        return erreur("Mot de passe actuel incorrect.", 400)
    stockage().changer_mot_de_passe(g.utilisateur["nom"], data.get("nouveau"))
    return jsonify({"ok": True})


@bp.get("/api/comptes")
@admin_requis
def lister_comptes():
    return jsonify(stockage().utilisateurs())


@bp.post("/api/comptes")
@admin_requis
def creer_compte():
    data = request.get_json(silent=True) or {}
    nom = stockage().ajouter_utilisateur(data.get("nom"), data.get("mot_de_passe"), bool(data.get("admin")))
    log.info("%s a créé le compte %s", g.utilisateur["nom"], nom)
    return jsonify(stockage().utilisateurs())


@bp.delete("/api/comptes/<nom>")
@admin_requis
def supprimer_compte(nom):
    if nom == g.utilisateur["nom"]:
        return erreur("Vous ne pouvez pas supprimer votre propre compte.", 400)
    stockage().supprimer_utilisateur(nom)
    log.info("%s a supprimé le compte %s", g.utilisateur["nom"], nom)
    return jsonify(stockage().utilisateurs())
