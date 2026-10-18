"""Lecture des factures METRO et normalisation des adresses Nextcloud."""
import pytest

from conftest import avec_exemples, date_du_fichier, factures_exemple
from factures.metro import FactureIllisible, parse_pdf
from factures.metro.lecture import RE_ARTICLE, parse_lines
from factures.nextcloud import base_url, clean_path, dossier_dans_url


@avec_exemples
@pytest.mark.parametrize("chemin", factures_exemple(), ids=lambda p: p.name[:20])
def test_les_lignes_lues_tombent_juste_avec_le_recapitulatif_tva(chemin):
    facture = parse_pdf(chemin)
    assert facture["lignes"], "aucune ligne lue"
    assert facture["controle_ok"], facture["controles"]
    assert facture["date"] == date_du_fichier(chemin)
    assert facture["total_ttc"] and facture["total_ht"]
    assert set(facture["tva"]) <= {"A", "B", "C", "D", "E", "F"}


def test_ligne_avec_repere_dans_la_colonne_mm():
    ligne = ("M  3439495406320  2612679 RIOBA NECTAR BANANE TO 25CL"
             "                                        0,634     12  3     22,83    B")
    m = RE_ARTICLE.match(ligne)
    assert m and m["mm"] == "M" and m["art"] == "2612679" and m["montant"] == "22,83"


def test_remise_rattachee_a_la_ligne_precedente():
    lignes = [
        "   3439495406320  2612679 RIOBA NECTAR BANANE TO 25CL"
        "                                        0,634     12  3     22,83    B",
        "                          Offre Achetez Plus Payez Moins"
        "                                                          1,83-",
        "*** BRASSERIE Total: 21,00",
        "   21,00   B =    5,50%                    1,16        22,16",
    ]
    facture = parse_lines(lignes)
    assert facture["lignes"][0]["remise_ht"] == 1.83
    assert facture["lignes"][0]["montant_net_ht"] == 21.0
    assert facture["lignes"][0]["categorie"] == "Brasserie"
    assert facture["controle_ok"]


def test_pdf_illisible():
    with pytest.raises(FactureIllisible):
        parse_lines(["rien qui ressemble à une facture METRO"])


@pytest.mark.parametrize("adresse, serveur, dossier", [
    ("https://drive.aml-lyon1.fr/apps/files/files/10372?dir=/2025-2026/Factures%20METRO",
     "https://drive.aml-lyon1.fr", "2025-2026/Factures METRO"),
    ("drive.aml-lyon1.fr", "https://drive.aml-lyon1.fr", None),
    ("https://drive.aml-lyon1.fr/remote.php/dav/files/sofiane/", "https://drive.aml-lyon1.fr", None),
    ("https://exemple.fr/nextcloud/index.php/apps/files/?dir=/Compta", "https://exemple.fr/nextcloud", "Compta"),
    ("https://exemple.fr/nextcloud/s/AbCdEf", "https://exemple.fr/nextcloud", None),
])
def test_adresse_nextcloud_copiee_depuis_le_navigateur(adresse, serveur, dossier):
    assert base_url(adresse) == serveur
    assert dossier_dans_url(adresse) == dossier


def test_chemin_de_dossier():
    assert clean_path("/Factures//Metro/") == "Factures/Metro"
    with pytest.raises(Exception):
        clean_path("../secret")
