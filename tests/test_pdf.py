"""PDF générés : récapitulatif d'une catégorie, bilan final, bilan des ventes."""
import io

import pdfplumber
import pytest

from conftest import avec_exemples, factures_exemple
from factures.metro import parse_pdf
from factures.pdf import generer_bilan, generer_recap, generer_ventes
from factures.pdf.commun import euros, texte_reglages


def texte(pdf):
    """Texte du PDF ; les espaces insécables sont relus comme des espaces simples."""
    with pdfplumber.open(io.BytesIO(pdf)) as document:
        return "\n".join(page.extract_text() for page in document.pages).replace("\xa0", " ")


def test_mise_en_forme_des_montants():
    assert euros(1234.565) == "1\xa0234,57\xa0€"
    assert euros(0.4253, 3) == "0,425\xa0€"
    assert texte_reglages({"marge": "20", "margeType": "pct", "taxe": "0.05", "arrondi": "0.10"}) == \
        "Marge 20\xa0% · Taxe TPE 0,05\xa0€ / pièce · Arrondi 0,10\xa0€ supérieur"


@pytest.fixture(scope="module")
def facture():
    if not factures_exemple():
        pytest.skip("aucune facture dans tests/factures_exemple/")
    return parse_pdf(factures_exemple()[0])


def vente_au_prix(facture, categories, marge=1.2):
    """Prix de vente = coût TTC par pièce × marge (une pièce par unité)."""
    vente = {"pieces": [], "prix": [], "optimal": [],
             "reglages": {"marge": "20", "margeType": "pct", "taxe": "0", "arrondi": "0"}}
    for ligne, cat in zip(facture["lignes"], categories):
        prix = round(ligne["montant_net_ht"] / ligne["unites"] * (1 + ligne["tva_taux"] / 100) * marge, 2) \
            if cat == "vente" else None
        vente["pieces"].append(1)
        vente["prix"].append(prix)
        vente["optimal"].append(prix)
    return vente


@avec_exemples
def test_recap_cadeau_porte_le_nom_du_conducteur(facture):
    lignes = facture["lignes"][:2]
    t = texte(generer_recap(facture, "cadeau", lignes, "05-10-2026.pdf", "pour le trajet", "Paul Martin"))
    assert "Dépenses « Cadeau conducteur : Paul Martin »" in t
    assert "conducteur : Paul Martin" in t and "Note : pour le trajet" in t
    assert lignes[0]["designation"] in t


@avec_exemples
def test_bilan_final_contient_toutes_les_infos_sans_prix_de_vente(facture):
    categories = ["vente"] * len(facture["lignes"])
    t = texte(generer_bilan(facture, categories, "05-10-2026.pdf", "admin", None, "Inès"))
    assert t.startswith("Bilan final")
    for attendu in ("conducteur : Inès", "Informations", "Montants (récapitulatif METRO)",
                    "Répartition par catégorie", "Détail des lignes", facture["ticket"],
                    f"Total à payer : {euros(facture['total_ttc'])}".replace("\xa0", " ")):
        assert attendu in t
    assert all(l["designation"] in t for l in facture["lignes"])
    assert "Prix de vente" not in t


@avec_exemples
def test_bilan_des_ventes_calcule_le_benefice(facture):
    categories = ["vente"] * len(facture["lignes"])
    categories[0] = "cadeau"
    t = texte(generer_ventes(facture, categories, vente_au_prix(facture, categories), "05-10-2026.pdf",
                             "admin", "note des ventes", "Paul"))
    assert t.startswith("Bilan des ventes")
    assert "conducteur : Paul" in t and "Note : note des ventes" in t
    assert "Cadeau conducteur (Paul)" in t and "Bénéfice après cadeau conducteur" in t
