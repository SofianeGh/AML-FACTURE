"""Éléments communs aux PDF de l'association (devis, factures, notes de frais) : logo, dates, nombres."""
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

LOGO = Path(__file__).resolve().parent.parent / "static" / "logo-aml.png"
NBSP = "\xa0"
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
        "novembre", "décembre"]


def date_longue(iso, avec_jour=False):
    """« 2026-11-16 » -> « 16 novembre 2026 » (ou « lundi 16 novembre 2026 ») ; « 1er » le premier du mois."""
    jour = date.fromisoformat(iso)
    texte = f"{'1er' if jour.day == 1 else jour.day} {MOIS[jour.month - 1]} {jour.year}"
    return f"{JOURS[jour.weekday()]} {texte}" if avec_jour else texte


def date_courte(iso):
    """« 2026-12-16 » -> « 16/12/2026 »"""
    return f"{date.fromisoformat(iso):%d/%m/%Y}"


def montant_fr(valeur, decimales_max=2):
    """8 -> « 8,00 » ; 1234.5 -> « 1 234,50 » ; 0.125 avec decimales_max=4 -> « 0,125 »."""
    arrondi = Decimal(str(valeur)).quantize(Decimal(1).scaleb(-decimales_max), rounding=ROUND_HALF_UP)
    entier, _, decimales = f"{arrondi:,.{decimales_max}f}".partition(".")
    decimales = decimales.rstrip("0").ljust(2, "0")
    return f"{entier.replace(',', NBSP)},{decimales}"


def quantite_fr(valeur):
    """100 -> « 100 » ; 1.5 -> « 1,5 » ; 1000 -> « 1 000 »."""
    texte = f"{Decimal(str(valeur)).normalize():,f}"
    return texte.replace(",", NBSP).replace(".", ",")


def taux_fr(taux):
    """None -> « Non applicable » ; 5.5 -> « 5,5 % »."""
    return "Non applicable" if taux is None else f"{taux:g}".replace(".", ",") + NBSP + "%"
