"""Éléments communs aux PDF : catégories, types de documents, styles, mise en forme des montants."""
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

# clé -> (nom dans le fichier, libellé affiché)
CATEGORIES = {
    "vente": ("VENTE", "Vente"),
    "event": ("EVENT", "Event"),
    "local": ("LOCAL", "Local"),
    "cadeau": ("CADEAU CONDUCTEUR", "Cadeau conducteur"),
    "hors": ("HORS CATEGORIE", "Hors catégorie"),
}

# Documents envoyés sur Nextcloud (chaque type peut avoir son propre dossier) : clé -> libellé
DOCUMENTS = {
    "facture": "Facture METRO (original)",
    "bilan": "Bilan final",
    "ventes": "Bilan des ventes",
    **{cle: f"Récap {libelle}" for cle, (_, libelle) in CATEGORIES.items()},
}
NOM_BILAN = "BILAN FINAL"
NOM_VENTES = "BILAN VENTES"

CENT = Decimal("0.01")
NBSP = "\xa0"
GRIS = colors.HexColor("#5d6878")
BORDURE = colors.HexColor("#dde1e7")
FOND = colors.HexColor("#f0f2f5")

S_TITRE = ParagraphStyle("titre", fontName="Helvetica-Bold", fontSize=18, leading=22)
S_SOUS = ParagraphStyle("sous", fontName="Helvetica-Bold", fontSize=12, leading=16, spaceBefore=4)
S_META = ParagraphStyle("meta", fontName="Helvetica", fontSize=8.5, leading=11, textColor=GRIS)
S_CELL = ParagraphStyle("cell", fontName="Helvetica", fontSize=8.5, leading=10.5)
S_CELL_SUB = ParagraphStyle("cellsub", parent=S_CELL, fontSize=7, leading=9, textColor=GRIS)
S_NOTE = ParagraphStyle("note", fontName="Helvetica", fontSize=7.5, leading=10, textColor=GRIS)
S_TOTAL = ParagraphStyle("total", fontName="Helvetica-Bold", fontSize=12, leading=16, alignment=TA_RIGHT)


def _arrondi(v):
    return Decimal(v).quantize(CENT, rounding=ROUND_HALF_UP)


def euros(v, decimales=2):
    v = Decimal(str(v)).quantize(Decimal(1).scaleb(-decimales), rounding=ROUND_HALF_UP)
    s = f"{v:,.{decimales}f}".replace(",", NBSP).replace(".", ",")
    return f"{s}{NBSP}€"


def taux_txt(taux):
    return "?" if taux is None else f"{taux:g}".replace(".", ",") + NBSP + "%"


def qte_txt(v):
    return f"{v:g}".replace(".", ",")


def totaux_par_taux(lignes):
    """{taux: (HT, TVA, TTC)} : TVA arrondie une fois par taux, comme sur la facture METRO."""
    ht = defaultdict(Decimal)
    for l in lignes:
        ht[l["tva_taux"]] += Decimal(str(l["montant_net_ht"]))
    resultat = {}
    for taux, montant in sorted(ht.items(), key=lambda kv: (kv[0] is None, kv[0] or 0)):
        tva = _arrondi(montant * Decimal(str(taux or 0)) / 100)
        resultat[taux] = (_arrondi(montant), tva, _arrondi(montant) + tva)
    return resultat


S_NOTE_TEXTE = ParagraphStyle("note_texte", fontName="Helvetica", fontSize=9.5, leading=13)
ACCENT = colors.HexColor("#7a5600")


def bloc_note(note):
    """Encadré « Note » saisi dans l'application (rien si la note est vide)."""
    note = (note or "").strip()
    if not note:
        return []
    texte = "<br/>".join(escape(ligne) for ligne in note.splitlines())
    cadre = Table([[Paragraph(f"<b>Note :</b> {texte}", S_NOTE_TEXTE)]], colWidths=[180 * mm])
    cadre.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fff6d6")),
        ("LINEBEFORE", (0, 0), (0, -1), 3, ACCENT),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return [Spacer(1, 4 * mm), cadre]


ROUGE = colors.HexColor("#b3261e")
VERT = colors.HexColor("#1d7a43")


def _decimal(valeur, defaut="0"):
    try:
        return Decimal(str(valeur).replace(",", ".")) if valeur not in (None, "") else Decimal(defaut)
    except ArithmeticError:
        return Decimal(defaut)


def texte_reglages(reglages):
    """« Marge 20 % · Taxe TPE 0,05 € / pièce · Arrondi 0,10 € supérieur »"""
    marge = _decimal(reglages.get("marge"))
    if reglages.get("margeType") == "eur":
        marge_txt = f"{euros(marge)} / pièce"
    else:
        marge_txt = f"{marge.normalize():f}".replace(".", ",") + f"{NBSP}%"
    pas = _decimal(reglages.get("arrondi"))
    arrondi = f"{euros(pas)} supérieur" if pas > 0 else "aucun"
    return f"Marge {marge_txt} · Taxe TPE {euros(_decimal(reglages.get('taxe')))} / pièce · Arrondi {arrondi}"
