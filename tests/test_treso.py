"""Trésorerie (reprise d'AML Trésorerie) : relevés CSV, classement, compte de résultat, exports,
justificatifs, liens avec les notes de frais et les factures. Données fictives uniquement."""
import io
from decimal import Decimal

import pdfplumber
import pytest
from openpyxl import load_workbook

from conftest import ENTETE, FauxNextcloud
from factures.treso.releve import ReleveIllisible, lire_releve
from test_devis_ndf import DEVIS, NOTE

# Relevé fictif au format de la banque (Débit / Crédit, lignes de suite avec MOTIF:)
RELEVE = """Relevé de compte fictif;;;;
Compte courant ASSO EXEMPLE;;;;
Date;Nature;Libellé;Débit;Crédit
05/11/2026;CARTE X0000;RESTAURANT DU PARC;242,20;
;;MOTIF: Soirée jeux;;
08/11/2026;VIR RECU;BUREAU DES ETUDIANTS;;900,00
08/11/2026;CARTE X0000;BOULANGERIE;12,50;
08/11/2026;CARTE X0000;BOULANGERIE;12,50;
10/11/2026;VIR EMIS;"VIR VERS LIVRET
MOTIF: Épargne";100,00;
"""


def importer(client, mandat, contenu=RELEVE, nom="releve.csv", encodage="utf-8"):
    return client.post("/api/treso/operations/import", headers=ENTETE, content_type="multipart/form-data",
                       data={"mandat": str(mandat), "fichier": (io.BytesIO(contenu.encode(encodage)), nom)})


def texte_pdf(pdf):
    with pdfplumber.open(io.BytesIO(pdf)) as document:
        return " ".join(" ".join((p.extract_text() or "").split()) for p in document.pages).replace("\xa0", " ")


@pytest.fixture
def mandat(membre):
    return membre.get("/api/treso/mandats").get_json()[0]["id"]


def classeur(client, mandat, nom):
    return next(c for c in client.get(f"/api/treso/classeurs?mandat={mandat}").get_json() if c["nom"] == nom)


# ---------------------------------------------------------------- lecture des relevés

def test_lecture_du_releve():
    lignes = lire_releve(RELEVE.encode("utf-8"))
    assert [(l.date, l.libelle, l.nature, l.montant) for l in lignes] == [
        ("2026-11-05", "Soirée jeux", "CARTE X0000", Decimal("-242.20")),
        ("2026-11-08", "BUREAU DES ETUDIANTS", "VIR RECU", Decimal("900.00")),
        ("2026-11-08", "BOULANGERIE", "CARTE X0000", Decimal("-12.50")),
        ("2026-11-08", "BOULANGERIE", "CARTE X0000", Decimal("-12.50")),
        ("2026-11-10", "Épargne", "VIR EMIS", Decimal("-100.00")),
    ]


def test_lecture_autres_formats():
    latin1 = "Date opération,Date valeur,Libellé,Montant\n01/12/26,02/12/26,Cotisation,\"1 234,56\"\n".encode("latin-1")
    lignes = lire_releve(latin1)
    assert len(lignes) == 1 and lignes[0].date == "2026-12-01" and lignes[0].montant == Decimal("1234.56")
    assert lire_releve(b"\xef\xbb\xbfdate;label;montant\n2026-12-03;Don;-1.234,50\n")[0].montant == Decimal("-1234.50")
    with pytest.raises(ReleveIllisible):
        lire_releve(b"ceci;n'est;pas;un;releve\n1;2;3;4;5\n")
    with pytest.raises(ReleveIllisible):
        lire_releve(b"Date;Libelle;Montant\n31/02/2026;Erreur;10\n")


# ---------------------------------------------------------------- transactions et classement

def test_donnees_de_depart(membre, mandat):
    assert [m["nom"] for m in membre.get("/api/treso/mandats").get_json()] == ["2025 - 2026"]
    categories = membre.get("/api/treso/categories").get_json()
    assert len(categories) == 7 and categories[-1] == {"id": 7, "nom": "Hors Compte de Résultats", "hors_cr": True}
    assert len(membre.get(f"/api/treso/classeurs?mandat={mandat}").get_json()) == 23


def test_import_sans_doublon_et_classement(membre, mandat):
    reponse = importer(membre, mandat)
    assert reponse.status_code == 200, reponse.get_json()
    assert reponse.get_json() == {"lues": 5, "ajoutees": 5, "doublons": 0, "hors_mandat": 5}
    assert importer(membre, mandat).get_json()["ajoutees"] == 0  # même fichier : rien en double
    assert importer(membre, mandat, "fichier vide").status_code == 400

    ops = membre.get(f"/api/treso/operations?mandat={mandat}").get_json()
    assert [o["montant"] for o in ops] == [-100.0, -12.5, -12.5, 900.0, -242.2]  # plus récentes d'abord
    assert len(membre.get(f"/api/treso/operations?mandat={mandat}&a_classer=1").get_json()) == 5
    assert len(membre.get(f"/api/treso/operations?mandat={mandat}&mois=2026-12").get_json()) == 0

    resto = next(o for o in ops if o["montant"] == -242.2)
    galette = classeur(membre, mandat, "Galette des Rois")
    reponse = membre.put(f"/api/treso/operations/{resto['id']}", headers=ENTETE,
                         json={"classeur_id": galette["id"], "commentaire": "Soirée", "libelle": ""})
    assert reponse.status_code == 200
    assert reponse.get_json()["classeur"] == "Galette des Rois" and reponse.get_json()["libelle"] == "Soirée jeux"
    assert len(membre.get(f"/api/treso/operations?mandat={mandat}&a_classer=1").get_json()) == 4

    # un classeur d'un autre mandat est refusé
    autre = membre.post("/api/treso/mandats", headers=ENTETE, json={
        "nom": "2026 - 2027", "debut": "2026-09-01", "fin": "2027-08-31", "copier_de": mandat}).get_json()["id"]
    assert len(membre.get(f"/api/treso/classeurs?mandat={autre}").get_json()) == 23  # classeurs repris
    autre_galette = classeur(membre, autre, "Galette des Rois")
    assert membre.put(f"/api/treso/operations/{resto['id']}", headers=ENTETE,
                      json={"classeur_id": autre_galette["id"]}).status_code == 400
    assert membre.post("/api/treso/mandats", headers=ENTETE, json={
        "nom": "2026 - 2027", "debut": "2026-09-01", "fin": "2027-08-31"}).status_code == 400
    assert membre.post("/api/treso/mandats", headers=ENTETE, json={
        "nom": "À l'envers", "debut": "2027-09-01", "fin": "2027-08-31"}).status_code == 400

    # classeurs : ajout, doublon refusé, suppression seulement s'il est vide
    nouveau = membre.post("/api/treso/classeurs", headers=ENTETE,
                          json={"mandat_id": mandat, "categorie_id": 1, "nom": "Soirée jeux de société"})
    assert nouveau.status_code == 200
    assert membre.post("/api/treso/classeurs", headers=ENTETE,
                       json={"mandat_id": mandat, "categorie_id": 1, "nom": "Soirée jeux de société"}).status_code == 400
    assert membre.delete(f"/api/treso/classeurs/{galette['id']}", headers=ENTETE).status_code == 400
    assert membre.delete(f"/api/treso/classeurs/{nouveau.get_json()['id']}", headers=ENTETE).status_code == 200

    assert membre.delete(f"/api/treso/operations/{resto['id']}", headers=ENTETE).status_code == 200
    assert len(membre.get(f"/api/treso/operations?mandat={mandat}").get_json()) == 4


# ---------------------------------------------------------------- compte de résultat et exports

def test_compte_de_resultat_et_exports(membre, mandat):
    importer(membre, mandat)
    ops = {o["montant"]: o for o in membre.get(f"/api/treso/operations?mandat={mandat}").get_json()}
    classer = lambda montant, nom: membre.put(f"/api/treso/operations/{ops[montant]['id']}", headers=ENTETE,  # noqa
                                              json={"classeur_id": classeur(membre, mandat, nom)["id"]})
    classer(-242.2, "Galette des Rois")
    classer(900.0, "Galette des Rois")
    classer(-12.5, "Vente au local")
    classer(-100.0, "Mouvement interne")  # hors compte de résultat

    cr = membre.get(f"/api/treso/compte-resultat?mandat={mandat}").get_json()
    evenements = cr["categories"][0]
    assert evenements["nom"] == "Événements" and evenements["balance"] == 657.8
    galette = next(k for k in evenements["classeurs"] if k["nom"] == "Galette des Rois")
    assert (galette["charges"], galette["produits"], galette["nb"]) == (-242.2, 900.0, 2)
    assert cr["total_cr"] == {"charges": -254.7, "produits": 900.0, "balance": 645.3}
    assert cr["total_hors_cr"]["balance"] == -100.0
    assert cr["non_classe"] == {"charges": -12.5, "produits": 0.0, "balance": -12.5, "nb": 1}
    assert cr["solde_releve"] == 532.8 and cr["ecart"] == 0

    base = f"/api/treso/compte-resultat/export?mandat={mandat}&format="
    csv = membre.get(base + "csv").data.decode("utf-8")
    assert csv.startswith("﻿Catégorie / Classeur;Charges;Produits;Balance")
    assert "Galette des Rois;-242,20;900,00;657,80" in csv and csv.endswith("SOUS-TOTAUX;-254,70;900,00;645,30")
    assert "Mouvement interne" not in csv  # le hors compte de résultat n'est pas exporté
    feuille = load_workbook(io.BytesIO(membre.get(base + "xlsx").data)).active
    assert feuille["A1"].value == "Catégorie / Classeur" and feuille["A1"].font.bold
    assert [feuille.cell(r, 1).value for r in range(2, 4)] == ["Événements", "Escape Game"]
    t = texte_pdf(membre.get(base + "pdf").data)
    for attendu in ("Compte de résultat 2025 - 2026", "Galette des Rois -242,20 € 900,00 € 657,80 €",
                    "SOUS-TOTAUX -254,70 € 900,00 € 645,30 €", "RESTE HORS CR", "Non classé (1 ligne)",
                    "contrôle : tout concorde"):
        assert attendu in t, attendu
    assert membre.get(base + "doc").status_code == 400


# ---------------------------------------------------------------- justificatifs et liens

def test_justificatifs_et_liens_avec_ndf_et_factures(admin, membre, mandat):
    importer(membre, mandat)
    ops = {o["montant"]: o for o in membre.get(f"/api/treso/operations?mandat={mandat}").get_json()}
    debit, credit = ops[-242.2]["id"], ops[900.0]["id"]

    # fichier joint : un PDF s'affiche, une page HTML est seulement proposée au téléchargement
    pdf = membre.post(f"/api/treso/operations/{debit}/justificatifs", headers=ENTETE, content_type="multipart/form-data",
                      data={"fichier": (io.BytesIO(b"%PDF-1.4 faux"), "ticket.pdf")})
    assert pdf.status_code == 200 and pdf.get_json()["nextcloud"] is None
    vu = membre.get(f"/api/treso/justificatifs/{pdf.get_json()['id']}")
    assert vu.mimetype == "application/pdf" and vu.data == b"%PDF-1.4 faux"
    html = membre.post(f"/api/treso/operations/{debit}/justificatifs", headers=ENTETE,
                       content_type="multipart/form-data",
                       data={"fichier": (io.BytesIO(b"<script>alert(1)</script>"), "page.html")}).get_json()
    vu = membre.get(f"/api/treso/justificatifs/{html['id']}")
    assert vu.mimetype == "application/octet-stream" and "attachment" in vu.headers["Content-Disposition"]
    assert membre.delete(f"/api/treso/justificatifs/{html['id']}", headers=ENTETE).status_code == 200

    # note de frais du même montant : proposée en premier, jointe, puis « Remboursée »
    note = membre.post("/api/ndf", headers=ENTETE, json=NOTE).get_json()["id"]
    docs = membre.get(f"/api/treso/operations/{debit}/documents").get_json()
    assert docs["debit"] and docs["ndf"][0]["id"] == note and docs["ndf"][0]["identique"]
    lien = membre.post(f"/api/treso/operations/{debit}/liens", headers=ENTETE, json={"type": "ndf", "id": note})
    assert lien.status_code == 200 and lien.get_json()["statut"] == "Remboursée"
    assert membre.post(f"/api/treso/operations/{debit}/liens", headers=ENTETE,
                       json={"type": "ndf", "id": note}).status_code == 400  # déjà jointe
    assert membre.get(f"/api/ndf/{note}").get_json()["statut"] == "remboursee"
    assert membre.get("/api/ndf").get_json()[0]["rapprochements"] == [{"date": "2026-11-05", "montant": -242.2}]
    vu = membre.get(f"/api/treso/justificatifs/{lien.get_json()['id']}")
    assert vu.mimetype == "application/pdf" and "Attestation sur l’honneur" in texte_pdf(vu.data)
    assert membre.get(f"/api/treso/operations/{debit}/documents").get_json()["ndf"][0]["joint"]

    # facture du même montant jointe au crédit : « Payée »
    piece = {**DEVIS, "type": "facture", "numero": "AML-F-2026-001", "echeance": "2026-12-16"}
    facture = membre.post("/api/devis", headers=ENTETE, json=piece).get_json()["id"]
    docs = membre.get(f"/api/treso/operations/{credit}/documents").get_json()
    assert not docs["debit"] and docs["factures"][0]["identique"]
    lien = membre.post(f"/api/treso/operations/{credit}/liens", headers=ENTETE, json={"type": "facture", "id": facture})
    assert lien.get_json()["statut"] == "Payée" and membre.get(f"/api/devis/{facture}").get_json()["statut"] == "payee"
    assert next(p for p in membre.get("/api/devis").get_json() if p["id"] == facture)["rapprochements"]
    assert membre.post(f"/api/treso/operations/{credit}/liens", headers=ENTETE,
                       json={"type": "devis", "id": facture}).status_code == 400

    ops = {o["id"]: o for o in membre.get(f"/api/treso/operations?mandat={mandat}").get_json()}
    assert [j["lien_type"] for j in ops[debit]["justificatifs"]] == [None, "ndf"]

    # la note supprimée n'est plus jointe à la transaction
    assert membre.delete(f"/api/ndf/{note}", headers=ENTETE).status_code == 200
    ops = {o["id"]: o for o in membre.get(f"/api/treso/operations?mandat={mandat}").get_json()}
    assert [j["lien_type"] for j in ops[debit]["justificatifs"]] == [None]


def test_copie_des_justificatifs_sur_nextcloud(nextcloud_configure, mandat):
    client = nextcloud_configure
    importer(client, mandat)
    op = next(o for o in client.get(f"/api/treso/operations?mandat={mandat}").get_json() if o["montant"] == -242.2)
    client.put(f"/api/treso/operations/{op['id']}", headers=ENTETE,
               json={"classeur_id": classeur(client, mandat, "Galette des Rois")["id"]})
    reponse = client.post(f"/api/treso/operations/{op['id']}/justificatifs", headers=ENTETE,
                          content_type="multipart/form-data",
                          data={"fichier": (io.BytesIO(b"%PDF-1.4 ticket"), "ticket.pdf")}).get_json()
    chemin = f"2025 - 2026/[3] Trésorerie/Événements/Galette des Rois/2026-11-05_op{op['id']}_ticket.pdf"
    assert reponse["nextcloud"] == "/" + chemin and FauxNextcloud.fichiers[chemin] == b"%PDF-1.4 ticket"


def test_reprise_du_referentiel_d_aml_tresorerie(app):
    treso = app.extensions["treso"]
    nombres = treso.reprendre_referentiel({
        "categories": [{"id": 1, "nom": "Événements", "hors_cr": False, "ordre": 1},
                       {"id": 7, "nom": "Hors Compte de Résultats", "hors_cr": True, "ordre": 7}],
        "mandats": [{"id": 1, "nom": "2025 - 2026", "debut": "2025-09-01", "fin": "2026-08-31"},
                    {"id": 2, "nom": "2026 - 2027", "debut": "2026-11-01", "fin": "2027-11-15"}],
        "classeurs": [{"id": 1, "mandat_id": 1, "categorie_id": 1, "nom": "Escape Game"},
                      {"id": 24, "mandat_id": 2, "categorie_id": 7, "nom": "Mouvement interne"}],
    })
    assert nombres == {"mandats": 2, "categories": 2, "classeurs": 2}
    assert [m["nom"] for m in treso.mandats()] == ["2026 - 2027", "2025 - 2026"]
    assert treso.classeurs(2) == [{"id": 24, "nom": "Mouvement interne", "categorie_id": 7,
                                   "categorie_nom": "Hors Compte de Résultats", "nb": 0}]
