"""Devis, factures et notes de frais de l'association : API, numérotation, justificatifs, signature, PDF."""
import base64
import io

import pdfplumber
from PIL import Image, ImageDraw
from reportlab.pdfgen.canvas import Canvas

from conftest import ENTETE
from factures.aml.ndf import lire_signature


def texte_pdf(pdf):
    """Texte du PDF sur une seule ligne (espaces insécables et retours à la ligne -> espaces)."""
    with pdfplumber.open(io.BytesIO(pdf)) as document:
        texte = " ".join(page.extract_text() or "" for page in document.pages)
    return " ".join(texte.replace("\xa0", " ").split())


def nb_pages(pdf):
    with pdfplumber.open(io.BytesIO(pdf)) as document:
        return len(document.pages)


# Données fictives (aucune vraie personne, association ni adresse)
DEVIS = {
    "type": "devis", "numero": "AML-D-2026-001", "date": "2026-11-16", "validite": "2026-12-16",
    "nature": "Prestation de services",
    "client_nom": "Bureau des étudiants\nAssociation EXEMPLE'ASSO",
    "client_adresse": "Maison des associations\n10 rue de l'Exemple\n69003 Lyon\nFrance",
    "client_telephone": "01 23 45 67 89",
    "objet": "Prestation du samedi 12 décembre 2026",
    "lieu": "Salle polyvalente, Campus Exemple\n69100 Villeurbanne",
    "description": "Buffet - 100 formules sandwich et 100 cafés",
    "lignes": [{"designation": "Formule sandwich", "prix_ht": 8, "quantite": 100, "tva": None},
               {"designation": "Café", "prix_ht": "1,00", "quantite": 100, "tva": None}],
}
ASSOCIATION = {
    "adresse": "1 place de l'Exemple", "ville": "69000 Lyon", "pays": "France", "siret": "000 000 000 00000",
    "contacts": "Présidente : Alice Exemple - presidence@exemple.fr\nTrésorier : Bruno Exemple - tresorerie@exemple.fr",
}


def coordonnees_fictives(admin):
    a = admin.get("/api/association").get_json()
    assert admin.put("/api/association", json={**a, **ASSOCIATION}, headers=ENTETE).status_code == 200


# ---------------------------------------------------------------- association

def test_coordonnees_par_defaut_et_droits(admin, membre):
    a = membre.get("/api/association").get_json()
    assert a["sigle"] == "AML" and a["siret"] == "" and a["contacts"] == "" and a["prefixe_devis"] == "AML-D"
    assert membre.put("/api/association", json={**a, "sigle": "X"}, headers=ENTETE).status_code == 403
    reponse = admin.put("/api/association", json={**a, "iban": "FR76 3000 4000"}, headers=ENTETE)
    assert reponse.status_code == 200 and reponse.get_json()["iban"] == "FR76 3000 4000"
    assert membre.get("/api/association").get_json()["iban"] == "FR76 3000 4000"
    assert admin.put("/api/association", json={**a, "prefixe_facture": "AML-D"}, headers=ENTETE).status_code == 400
    assert admin.put("/api/association", json={**a, "nom": ""}, headers=ENTETE).status_code == 400


# ---------------------------------------------------------------- devis et factures

def test_devis_numerotation_et_pdf(admin, membre):
    coordonnees_fictives(admin)
    proposition = membre.get("/api/devis/nouveau?type=devis&date=2026-11-16").get_json()
    assert proposition["numero"] == "AML-D-2026-001" and proposition["validite"] == "2026-12-16"
    reponse = membre.post("/api/devis", json=DEVIS, headers=ENTETE)
    assert reponse.status_code == 200, reponse.get_json()
    devis = reponse.get_json()
    assert devis["numero"] == "AML-D-2026-001" and devis["statut"] == "en_attente"
    assert membre.post("/api/devis", json=DEVIS, headers=ENTETE).status_code == 400  # numéro déjà pris
    assert membre.get("/api/devis/nouveau?type=devis&date=2026-12-01").get_json()["numero"] == "AML-D-2026-002"
    assert membre.get("/api/devis/nouveau?type=devis&date=2027-01-05").get_json()["numero"] == "AML-D-2027-001"
    assert membre.get("/api/devis").get_json()[0]["total_ttc"] == 900
    assert membre.get("/api/devis/clients").get_json()[0]["telephone"] == "01 23 45 67 89"

    pdf = membre.get(f"/api/devis/{devis['id']}/pdf")
    assert pdf.mimetype == "application/pdf"
    assert "Devis_AML-D-2026-001_EXEMPLEASSO.pdf" in pdf.headers["Content-Disposition"]
    t = texte_pdf(pdf.data)
    for attendu in ("Informaticiens Lyonnais", "Devis AML-D-2026-001", "le lundi 16 novembre 2026",
                    "1 PLACE DE L'EXEMPLE", "69000 LYON - FRANCE", "Association EXEMPLE'ASSO",
                    "Téléphone : 01 23 45 67 89", "Objet : Prestation du samedi 12 décembre 2026",
                    "Lieu : Salle polyvalente, Campus Exemple", "Nombre de lignes : 2 - Prestation de services",
                    "Formule sandwich 8,00 8,00 100 800,00 800,00 -", "Non applicable 900,00 0,00 900,00",
                    "Total TTC : 900,00 €", "Date de validité : 16/12/2026", "Lu et approuvé, bon pour accord",
                    "Siret 000 000 000 00000", "TVA non applicable, art. 293 B du CGI",
                    "Trésorier : Bruno Exemple", "Page 1 / 1"):
        assert attendu in t, attendu


def test_devis_transforme_en_facture(membre):
    devis = membre.post("/api/devis", json=DEVIS, headers=ENTETE).get_json()
    proposition = membre.get("/api/devis/nouveau?type=facture&date=2026-11-22").get_json()
    assert proposition["numero"] == "AML-F-2026-001" and proposition["echeance"] == "2026-12-22"
    facture = {**DEVIS, "type": "facture", "numero": proposition["numero"], "date": "2026-11-22",
               "echeance": proposition["echeance"], "conditions": proposition["conditions"], "devis_id": devis["id"]}
    reponse = membre.post("/api/devis", json=facture, headers=ENTETE)
    assert reponse.status_code == 200, reponse.get_json()
    f1 = reponse.get_json()
    assert f1["devis_numero"] == "AML-D-2026-001" and f1["statut"] == "a_payer"
    liste = {p["numero"]: p for p in membre.get("/api/devis").get_json()}
    assert liste["AML-D-2026-001"]["statut"] == "accepte" and liste["AML-D-2026-001"]["facture"] == "AML-F-2026-001"

    t = texte_pdf(membre.get(f"/api/devis/{f1['id']}/pdf").data)
    for attendu in ("Facture AML-F-2026-001", "Suivant devis AML-D-2026-001", "Date d'échéance : 22/12/2026",
                    "Conditions de paiement : Paiement par virement", "indemnité forfaitaire de 40 €"):
        assert attendu in t, attendu
    assert "Lu et approuvé" not in t

    # les numéros de facture se suivent : seule la dernière de l'année peut être supprimée
    f2 = membre.post("/api/devis", json={**facture, "numero": "aml-f-2026-2", "devis_id": None},
                     headers=ENTETE).get_json()
    assert f2["numero"] == "AML-F-2026-002"
    assert membre.delete(f"/api/devis/{f1['id']}", headers=ENTETE).status_code == 400
    assert membre.delete(f"/api/devis/{f2['id']}", headers=ENTETE).status_code == 200
    assert membre.post(f"/api/devis/{f1['id']}/statut", json={"statut": "payee"}, headers=ENTETE).status_code == 200
    assert membre.post(f"/api/devis/{f1['id']}/statut", json={"statut": "accepte"}, headers=ENTETE).status_code == 400
    assert membre.get(f"/api/devis/{f1['id']}").get_json()["statut"] == "payee"

    # modifier sans changer le numéro, puis refuser un type qui change
    modif = {**facture, "numero": "AML-F-2026-001", "objet": "Prestation corrigée"}
    assert membre.put(f"/api/devis/{f1['id']}", json=modif, headers=ENTETE).get_json()["objet"] == "Prestation corrigée"
    assert membre.put(f"/api/devis/{f1['id']}", json={**modif, "type": "devis"}, headers=ENTETE).status_code == 400


def test_tva_et_document_sur_plusieurs_pages(membre):
    lignes = [{"designation": f"Article {i}", "prix_ht": 10, "quantite": 1, "tva": 20} for i in range(45)]
    lignes.append({"designation": "Livre", "prix_ht": 10, "quantite": 2, "tva": 5.5})
    devis = membre.post("/api/devis", json={**DEVIS, "lignes": lignes}, headers=ENTETE).get_json()
    assert membre.get("/api/devis").get_json()[0]["total_ttc"] == 561.1  # 450 + 90 de TVA + 20 + 1,10
    pdf = membre.get(f"/api/devis/{devis['id']}/pdf").data
    t = texte_pdf(pdf)
    assert nb_pages(pdf) == 2 and "Page 2 / 2" in t and "Suite page suivante" in t
    for attendu in ("Article 44", "20 % 450,00 90,00 540,00", "5,5 % 20,00 1,10 21,10", "Total TVA : 91,10 €",
                    "Total TTC : 561,10 €"):
        assert attendu in t, attendu


def test_devis_invalides(membre):
    for erreur in ({"lignes": []}, {"numero": "AML-F-2026-001"}, {"numero": "n'importe quoi"},
                   {"date": "16/11/2026"}, {"client_nom": ""}, {"lignes": [{"designation": "x", "prix_ht": "abc",
                                                                             "quantite": 1}]},
                   {"lignes": [{"designation": "x", "prix_ht": 1, "quantite": 1, "tva": 7}]}):
        assert membre.post("/api/devis", json={**DEVIS, **erreur}, headers=ENTETE).status_code == 400, erreur
    assert membre.get("/api/devis/999").status_code == 404


# ---------------------------------------------------------------- notes de frais

def image(format_="PNG", taille=(300, 400)):
    tampon = io.BytesIO()
    Image.new("RGB", taille, "white").save(tampon, format_)
    return tampon.getvalue()


def signature_dessinee():
    trait = Image.new("RGBA", (700, 240), (0, 0, 0, 0))
    ImageDraw.Draw(trait).line((40, 200, 660, 40), fill=(17, 17, 17, 255), width=5)
    tampon = io.BytesIO()
    trait.save(tampon, "PNG")
    return "data:image/png;base64," + base64.b64encode(tampon.getvalue()).decode()


def televerser(client, data, nom="recu.png"):
    return client.post("/api/ndf/justificatifs", data={"fichier": (io.BytesIO(data), nom)}, headers=ENTETE,
                       content_type="multipart/form-data")


NOTE = {
    "civilite": "M.", "prenom": "Jean", "nom": "Dupont", "naissance_date": "1999-05-21",
    "naissance_lieu": "Lyon 7e arrondissement (69007)", "qualite": "membre", "association": "ASSOEX",
    "adresse": "12 rue des Lilas, 69007 Lyon", "nature": "10 repas complets",
    "liaison": "réglés à l’occasion de l’", "evenement": "afterwork commun entre l’ASSOEX et l’AML",
    "fait_a": "Lyon", "fait_le": "2026-11-11",
    "depenses": [{"fournisseur": "Restaurant du Parc, 5 avenue des Tilleuls, 69100 Villeurbanne", "date": "2026-11-10",
                  "recu": "12345", "montant": "242,20", "justificatifs": []}],
}


def test_note_de_frais_complete(membre):
    reponse = televerser(membre, image("JPEG"), "ticket.jpg")
    assert reponse.status_code == 200, reponse.get_json()
    j = reponse.get_json()[0]["id"]
    assert membre.get(f"/api/ndf/justificatifs/{j}").mimetype == "image/jpeg"
    note = {**NOTE, "signature": signature_dessinee(),
            "depenses": [{**NOTE["depenses"][0], "justificatifs": [j]}]}
    reponse = membre.post("/api/ndf", json=note, headers=ENTETE)
    assert reponse.status_code == 200, reponse.get_json()
    id_ = reponse.get_json()["id"]

    resume = membre.get("/api/ndf").get_json()[0]
    assert resume["personne"] == "Jean DUPONT" and resume["total_ttc"] == 242.2 and resume["nb_justificatifs"] == 1
    lue = membre.get(f"/api/ndf/{id_}").get_json()
    assert lue["signature"].startswith("data:image/png;base64,") and lue["depenses"][0]["justificatifs"] == [j]
    assert lue["statut"] == "a_rembourser"

    pdf = membre.get(f"/api/ndf/{id_}/pdf")
    assert "NDF_AML_Jean_DUPONT_2026-11-11.pdf" in pdf.headers["Content-Disposition"]
    assert nb_pages(pdf.data) == 2  # attestation + 1 page d'annexe
    t = texte_pdf(pdf.data)
    for attendu in ("Objet : Attestation sur l’honneur pour note de frais.",
                    "Je soussigné, M. Jean DUPONT, né le 21 mai 1999 à",
                    "membre de l’association ASSOEX, résidant 12 rue des Lilas, 69007 Lyon,",
                    "pour le compte de l’Association des Informaticiens Lyonnais (AML), les dépenses suivantes : "
                    "10 repas complets réglés à l’occasion de l’afterwork commun entre l’ASSOEX et l’AML.",
                    "d’un montant total de 242,20 € TTC, ont été réalisés le 10 novembre 2026 :",
                    "A. Restaurant du Parc, 5 avenue des Tilleuls, 69100 Villeurbanne (reçu n° 12345)",
                    "Fait à Lyon, le 11 novembre 2026.",
                    "Pièce(s) jointe(s) : 1 facture (justificatif de paiement Restaurant du Parc n° 12345, "
                    "joint en annexe).",
                    "Signature de M. Jean DUPONT",
                    "Annexe – Pièce jointe n° 1 : justificatif de paiement, Restaurant du Parc, 5 avenue des "
                    "Tilleuls, 69100 Villeurbanne, reçu n° 12345 du 10 novembre 2026, 242,20 € TTC."):
        assert attendu in t, attendu

    # deux dépenses à des dates différentes, sans justificatif : montants sur chaque ligne
    deux = {**note, "civilite": "Mme", "prenom": "Jeanne", "depenses": [
        {**NOTE["depenses"][0], "justificatifs": []},
        {"fournisseur": "Boulangerie", "date": "2026-11-12", "recu": "", "montant": 10, "justificatifs": []}]}
    assert membre.put(f"/api/ndf/{id_}", json=deux, headers=ENTETE).status_code == 200
    assert membre.get(f"/api/ndf/justificatifs/{j}").status_code == 404  # retiré de la note : supprimé
    t = texte_pdf(membre.get(f"/api/ndf/{id_}/pdf").data)
    for attendu in ("Je soussignée, Mme Jeanne DUPONT, née le", "252,20 € TTC, ont été réalisés aux dates suivantes :",
                    "A. Restaurant du Parc, 5 avenue des Tilleuls, 69100 Villeurbanne, le 10 novembre 2026 (reçu n° 12345) "
                    ": 242,20 € TTC", "B. Boulangerie, le 12 novembre 2026 : 10,00 € TTC",
                    "Pièce(s) jointe(s) : aucune."):
        assert attendu in t, attendu

    assert membre.post(f"/api/ndf/{id_}/statut", json={"statut": "remboursee"}, headers=ENTETE).status_code == 200
    assert membre.get("/api/ndf").get_json()[0]["statut"] == "remboursee"
    assert membre.delete(f"/api/ndf/{id_}", headers=ENTETE).status_code == 200
    assert membre.get("/api/ndf").get_json() == []


def test_justificatif_pdf_et_formats_refuses(membre):
    tampon = io.BytesIO()
    c = Canvas(tampon)
    for page in ("Ticket page 1", "Ticket page 2"):
        c.drawString(100, 700, page)
        c.showPage()
    c.save()
    reponse = televerser(membre, tampon.getvalue(), "facture.pdf")
    assert reponse.status_code == 200 and len(reponse.get_json()) == 2  # une image par page
    ids = [p["id"] for p in reponse.get_json()]
    note = {**NOTE, "depenses": [{**NOTE["depenses"][0], "justificatifs": ids}]}
    id_ = membre.post("/api/ndf", json=note, headers=ENTETE).get_json()["id"]
    pdf = membre.get(f"/api/ndf/{id_}/pdf").data
    assert nb_pages(pdf) == 3 and "Pièce jointe n° 1 (page 2/2)" in texte_pdf(pdf)
    # un justificatif déjà rattaché ne peut pas servir à une autre note
    assert membre.post("/api/ndf", json=note, headers=ENTETE).status_code == 400

    assert televerser(membre, b"ftypheic pas une image", "photo.heic").status_code == 400
    assert televerser(membre, b"", "vide.png").status_code == 400
    for erreur in ({"prenom": ""}, {"civilite": "Dr"}, {"depenses": []}, {"fait_le": "hier"},
                   {"depenses": [{**NOTE["depenses"][0], "montant": 0}]},
                   {"signature": "data:image/png;base64,pas-du-png"}):
        assert membre.post("/api/ndf", json={**NOTE, **erreur}, headers=ENTETE).status_code == 400, erreur


def test_signature_photographiee_rendue_transparente():
    papier = Image.new("RGB", (600, 200), (235, 232, 225))  # papier un peu gris
    ImageDraw.Draw(papier).line((50, 150, 550, 50), fill=(30, 40, 90), width=6)
    tampon = io.BytesIO()
    papier.save(tampon, "PNG")
    png = lire_signature("data:image/png;base64," + base64.b64encode(tampon.getvalue()).decode())
    resultat = Image.open(io.BytesIO(png))
    assert resultat.mode == "RGBA" and resultat.width < 600  # recadrée autour du trait
    assert resultat.getpixel((0, 0))[3] == 0  # papier transparent
    assert lire_signature("data:image/png;base64," + base64.b64encode(image()).decode()) is None  # page blanche
