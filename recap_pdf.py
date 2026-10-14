"""PDF récapitulatif des dépenses d'une catégorie (VENTE, EVENT…) pour une facture METRO."""
import io
from collections import defaultdict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

# clé -> (nom dans le fichier, libellé affiché)
CATEGORIES = {
    "vente": ("VENTE", "Vente"),
    "event": ("EVENT", "Event"),
    "local": ("LOCAL", "Local"),
    "cadeau": ("CADEAU CONDUCTEUR", "Cadeau conducteur"),
    "hors": ("HORS CATEGORIE", "Hors catégorie"),
}

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
    s = f"{Decimal(str(v)):,.{decimales}f}".replace(",", NBSP).replace(".", ",")
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


def generer_recap(facture, categorie, lignes, nom_facture):
    """Retourne le PDF (bytes) listant `lignes` (lignes de `facture` classées dans `categorie`)."""
    libelle = CATEGORIES[categorie][1]
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm, bottomMargin=15 * mm,
        title=f"{libelle} - facture METRO du {facture['date']}", author="Factures METRO",
    )

    meta = [f"N° {facture['numero']}" if facture.get("numero") else None,
            f"ticket {facture['ticket']}" if facture.get("ticket") else None,
            f"facture : {nom_facture}",
            f"{len(lignes)} ligne{'s' if len(lignes) > 1 else ''} sur {len(facture['lignes'])}"]
    elements = [
        Paragraph(f"Dépenses « {escape(libelle)} »", S_TITRE),
        Paragraph(f"Facture METRO du {escape(facture['date'] or '?')}", S_SOUS),
        Paragraph(escape(" · ".join(m for m in meta if m)), S_META),
        Spacer(1, 6 * mm),
    ]

    # -- détail des lignes
    donnees = [["Article", "Réf.", "Qté", "PU HT", "Total HT", "TVA", "Total TTC"]]
    for l in lignes:
        ht = Decimal(str(l["montant_net_ht"]))
        ttc = _arrondi(ht * (1 + Decimal(str(l["tva_taux"] or 0)) / 100))
        article = [Paragraph(escape(l["designation"]), S_CELL)]
        if l["remise_ht"]:
            article.append(Paragraph(f"remise −{euros(l['remise_ht'])} HT incluse", S_CELL_SUB))
        donnees.append([
            article, l["article"], qte_txt(l["unites"]),
            euros(l["cout_unitaire_ht"], 3), euros(ht), taux_txt(l["tva_taux"]), euros(ttc),
        ])
    table = Table(donnees, colWidths=[72 * mm, 17 * mm, 12 * mm, 21 * mm, 21 * mm, 14 * mm, 23 * mm],
                  repeatRows=1)
    table.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8),
        ("TEXTCOLOR", (0, 0), (-1, 0), GRIS),
        ("FONT", (1, 1), (-1, -1), "Helvetica", 8.5),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, BORDURE),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elements += [table, Spacer(1, 8 * mm)]

    # -- récapitulatif TVA
    recap = [["Taux TVA", "Total HT", "TVA", "Total TTC"]]
    total = [Decimal(0)] * 3
    for taux, montants in totaux_par_taux(lignes).items():
        recap.append([taux_txt(taux), *map(euros, montants)])
        total = [a + b for a, b in zip(total, montants)]
    recap.append(["Total", *map(euros, total)])
    table = Table(recap, colWidths=[30 * mm, 30 * mm, 30 * mm, 30 * mm], hAlign="RIGHT")
    table.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8),
        ("TEXTCOLOR", (0, 0), (-1, 0), GRIS),
        ("FONT", (0, 1), (-1, -1), "Helvetica", 9),
        ("FONT", (0, -1), (-1, -1), "Helvetica-Bold", 9.5),
        ("BACKGROUND", (0, -1), (-1, -1), FOND),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("LINEBELOW", (0, 0), (-1, -2), 0.5, BORDURE),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elements += [
        table,
        Spacer(1, 4 * mm),
        Paragraph(f"Total {escape(libelle)} : {euros(total[2])} TTC", S_TOTAL),
        Spacer(1, 10 * mm),
        Paragraph(
            "Montants calculés à partir des lignes de la facture METRO (remises déduites, TVA arrondie par taux). "
            f"Document généré le {date.today():%d/%m/%Y} par l'application Factures METRO.", S_NOTE),
    ]
    doc.build(elements)
    return buf.getvalue()
