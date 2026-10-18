"""API : connexion, droits, sécurité, préférences, analyse, aperçus et envoi sur Nextcloud (faux serveur)."""
import json

import pytest

from conftest import ADMIN, ENTETE, FauxNextcloud, avec_exemples, date_du_fichier, factures_exemple


# ---------------------------------------------------------------- connexion et sécurité

def test_pages_protegees_sans_connexion(app):
    client = app.test_client()
    reponse = client.get("/")
    assert reponse.status_code == 302 and reponse.headers["Location"].endswith("/connexion")
    assert client.get("/api/config").status_code == 401
    assert client.get("/connexion").status_code == 200
    assert client.get("/static/css/style.css").status_code == 200
    assert client.get("/static/js/main.js").status_code == 200


def test_sous_dossier_derriere_un_proxy(app, monkeypatch):
    monkeypatch.setenv("TRUST_PROXY", "1")
    from factures import create_app
    application = create_app(app.config["DATA_DIR"])
    reponse = application.test_client().get("/", headers={"X-Forwarded-Prefix": "/factures"})
    assert reponse.headers["Location"].endswith("/factures/connexion")


def test_en_tetes_de_securite(app):
    reponse = app.test_client().get("/connexion")
    assert "default-src 'self'" in reponse.headers["Content-Security-Policy"]
    assert reponse.headers["X-Frame-Options"] == "DENY"
    assert reponse.headers["X-Content-Type-Options"] == "nosniff"


def test_anti_csrf(app):
    reponse = app.test_client().post("/api/connexion", json={"nom": ADMIN[0], "mot_de_passe": ADMIN[1]})
    assert reponse.status_code == 403


def test_connexion_et_deconnexion(admin):
    assert admin.get("/api/moi").get_json() == {"nom": "admin", "admin": True}
    assert admin.get("/api/moi").headers["Cache-Control"] == "no-store"
    assert admin.post("/api/deconnexion", headers=ENTETE).status_code == 200
    assert admin.get("/api/moi").status_code == 401


def test_blocage_apres_cinq_essais(app):
    client = app.test_client()
    codes = [client.post("/api/connexion", json={"nom": "admin", "mot_de_passe": "faux"}, headers=ENTETE).status_code
             for _ in range(6)]
    assert codes == [401] * 5 + [429]


def test_cookie_de_session_securise_en_production(tmp_path, monkeypatch):
    monkeypatch.delenv("COOKIE_SECURE", raising=False)
    from factures import create_app
    application = create_app(tmp_path)
    application.extensions["stockage"].ajouter_utilisateur("chef", "motdepasse-chef", admin=True)
    reponse = application.test_client().post("/api/connexion", json={"nom": "chef", "mot_de_passe": "motdepasse-chef"},
                                             headers=ENTETE)
    cookie = reponse.headers["Set-Cookie"]
    assert "Secure" in cookie and "HttpOnly" in cookie and "SameSite=Lax" in cookie


# ---------------------------------------------------------------- comptes et droits

def test_gestion_des_comptes(admin, membre):
    reponse = admin.post("/api/comptes", json={"nom": "Bob", "mot_de_passe": "motdepasse-bob"}, headers=ENTETE)
    assert any(c["nom"] == "bob" for c in reponse.get_json())
    assert admin.post("/api/comptes", json={"nom": "bob", "mot_de_passe": "motdepasse-bob"},
                      headers=ENTETE).status_code == 400
    assert admin.delete("/api/comptes/admin", headers=ENTETE).status_code == 400
    assert membre.get("/api/comptes").status_code == 403
    assert admin.delete("/api/comptes/membre", headers=ENTETE).status_code == 200
    assert membre.get("/api/moi").status_code == 401  # compte supprimé = déconnecté


def test_mot_de_passe(membre):
    assert membre.post("/api/moi/mot-de-passe", json={"actuel": "faux", "nouveau": "nouveau-mdp"},
                       headers=ENTETE).status_code == 400
    assert membre.post("/api/moi/mot-de-passe", json={"actuel": "motdepasse-membre", "nouveau": "nouveau-mdp"},
                       headers=ENTETE).status_code == 200


def test_seul_un_admin_change_la_connexion_nextcloud(membre, nextcloud_configure):
    assert membre.post("/api/config", json={"nextcloud_url": "https://x", "nextcloud_login": "x",
                                            "nextcloud_password": "x"}, headers=ENTETE).status_code == 403
    config = membre.post("/api/config", json={"dossier": "Compta"}, headers=ENTETE).get_json()
    assert config["dossier"] == "Compta" and "nextcloud_password" not in config


def test_adresse_de_page_nextcloud(nextcloud_configure):
    config = nextcloud_configure.get("/api/config").get_json()
    assert config["nextcloud_url"] == "https://cloud.exemple.fr" and config["dossier"] == "2025-2026"
    assert list(config["documents"])[:3] == ["facture", "bilan", "ventes"]


# ---------------------------------------------------------------- préférences partagées

def test_preferences_partagees(admin, membre):
    assert membre.put("/api/preferences", headers=ENTETE, json={
        "marge": "25", "prix:2016699": 1.2, "pieces:2137701": 10, "local:0949040": True,
        "conducteurs": ["Paul", "Inès"]}).status_code == 200
    preferences = admin.get("/api/preferences").get_json()
    assert preferences["prix:2016699"] == 1.2 and preferences["conducteurs"] == ["Paul", "Inès"]
    assert admin.put("/api/preferences", json={"prix:2016699": None}, headers=ENTETE).status_code == 200
    assert "prix:2016699" not in membre.get("/api/preferences").get_json()


@pytest.mark.parametrize("mauvais", [{"autre": 1}, {"pieces:1": 0}, {"prix:1": "abc"}, {"margeType": "x"},
                                     {"local:1": False}, {"conducteurs": ["x" * 61]}])
def test_preferences_invalides(admin, mauvais):
    assert admin.put("/api/preferences", json=mauvais, headers=ENTETE).status_code == 400


# ---------------------------------------------------------------- factures

def analyser(client, chemin):
    reponse = client.post("/api/factures", data={"fichier": (chemin.open("rb"), chemin.name)}, headers=ENTETE)
    assert reponse.status_code == 200, reponse.get_json()
    return reponse.get_json()


def choix(facture):
    """Catégories (1re ligne en cadeau, dernière en event) et prix de vente au coût TTC × 1,2."""
    categories = ["vente"] * len(facture["lignes"])
    categories[0], categories[-1] = "cadeau", "event"
    vente = {"pieces": [], "prix": [], "optimal": [],
             "reglages": {"marge": "20", "margeType": "pct", "taxe": "0", "arrondi": "0"}}
    for ligne, cat in zip(facture["lignes"], categories):
        prix = round(ligne["montant_net_ht"] / ligne["unites"] * (1 + ligne["tva_taux"] / 100) * 1.2, 2) \
            if cat == "vente" else None
        vente["pieces"].append(1)
        vente["prix"].append(prix)
        vente["optimal"].append(prix)
    return categories, vente


def envoyer(client, chemin, nom, conducteur, categories, vente, notes=None):
    return client.post("/api/nextcloud/envoyer", headers=ENTETE, data={
        "fichier": (chemin.open("rb"), chemin.name), "nom": nom, "conducteur": conducteur,
        "categories": json.dumps(categories), "vente": json.dumps(vente), "notes": json.dumps(notes or {})})


@avec_exemples
def test_analyse_et_apercus(membre):
    chemin = factures_exemple()[0]
    facture = analyser(membre, chemin)
    assert facture["controle_ok"] and facture["date"] == date_du_fichier(chemin)
    categories, vente = choix(facture)
    nom = f"{facture['date']}.pdf"
    base = {"nom": nom, "categories": ",".join(categories), "conducteur": "Paul"}
    for url, params in [(f"/api/recap/{facture['id']}/cadeau", base), (f"/api/bilan/{facture['id']}", base),
                        (f"/api/ventes/{facture['id']}", dict(base, vente=json.dumps(vente)))]:
        reponse = membre.get(url, query_string=params)
        assert reponse.status_code == 200 and reponse.mimetype == "application/pdf", url
        assert "Content-Security-Policy" not in reponse.headers  # la visionneuse PDF doit s'ouvrir
    assert membre.get(f"/api/recap/{facture['id']}/hors", query_string=base).status_code == 404
    assert membre.get("/api/bilan/inconnu", query_string=base).status_code == 404


@avec_exemples
def test_envoi_par_type_de_pdf(membre, nextcloud_configure):
    chemin = factures_exemple()[0]
    facture = analyser(membre, chemin)
    categories, vente = choix(facture)
    nom = f"{facture['date']}.pdf"
    assert envoyer(membre, chemin, nom, "  ", categories, vente).status_code == 400  # conducteur obligatoire

    nextcloud_configure.post("/api/config", json={"destinations": {"ventes": "2025-2026/Ventes"}}, headers=ENTETE)
    reponse = envoyer(membre, chemin, nom, "Paul Martin", categories, vente, {"bilan": "note"})
    assert reponse.status_code == 200, reponse.get_json()
    resultat = reponse.get_json()
    base = nom[:-4]
    assert resultat["bilan"]["chemin"] == f"/2025-2026/{base} - BILAN FINAL.pdf"
    assert resultat["ventes"]["chemin"] == f"/2025-2026/Ventes/{base} - BILAN VENTES.pdf"
    assert {r["nom"] for r in resultat["recaps"]} == {f"{base} - VENTE.pdf", f"{base} - CADEAU CONDUCTEUR.pdf",
                                                      f"{base} - EVENT.pdf"}
    assert f"2025-2026/{nom}" in FauxNextcloud.fichiers

    # renvoi sans cadeau : facture déjà présente, récap cadeau supprimé
    categories[0] = "vente"
    vente["prix"][0] = vente["optimal"][0] = 1.0
    resultat = envoyer(membre, chemin, nom, "Paul Martin", categories, vente).get_json()
    assert resultat["deja_present"] and resultat["supprimes"] == [f"{base} - CADEAU CONDUCTEUR.pdf"]


@avec_exemples
def test_envoi_un_dossier_par_facture(membre, nextcloud_configure):
    chemin = factures_exemple()[0]
    facture = analyser(membre, chemin)
    categories, vente = choix(facture)
    nextcloud_configure.post("/api/config", json={"rangement": "facture"}, headers=ENTETE)
    jour, mois, annee = facture["date"].split("-")
    total = f"{facture['total_ttc']:.2f}".replace(".", ",")
    resultat = envoyer(membre, chemin, f"{facture['date']}.pdf", "Inès", categories, vente).get_json()
    dossier = f"/2025-2026/{annee}_{mois}_{jour} - {total} €"
    assert resultat["dossier"] == dossier
    assert all(r["chemin"].startswith(dossier + "/") for r in [resultat["bilan"], resultat["ventes"], *resultat["recaps"]])
