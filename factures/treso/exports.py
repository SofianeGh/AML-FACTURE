"""Exports du compte de résultat : CSV (Excel en français), Excel avec couleurs, PDF au style de l'AML.

Comme dans AML Trésorerie, on n'exporte que l'essentiel : les catégories du compte de résultat,
leurs classeurs et la ligne des sous-totaux (pas le bloc « hors compte de résultat »).
"""
import io
from datetime import date
from xml.sax.saxutils import escape

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from ..pdf.aml_commun import LOGO, date_longue, montant_fr
from ..pdf.commun import euros as euros_txt

TITRES = ["Catégorie / Classeur", "Charges", "Produits", "Balance"]


def lignes_export(cr):
    """[(type, nom, charges, produits, balance)] : catégories du CR, leurs classeurs, puis les sous-totaux."""
    lignes = []
    for c in cr["categories"]:
        if c["hors_cr"]:
            continue
        lignes.append(("categorie", c["nom"], c["charges"], c["produits"], c["balance"]))
        lignes += [("classeur", k["nom"], k["charges"], k["produits"], k["balance"]) for k in c["classeurs"]]
    t = cr["total_cr"]
    lignes.append(("total", "SOUS-TOTAUX", t["charges"], t["produits"], t["balance"]))
    return lignes


def export_csv(cr):
    """Séparateur « ; », virgule décimale et BOM : s'ouvre correctement dans Excel en français."""
    def cellule(v):
        v = str(v)
        return f'"{v.replace(chr(34), chr(34) * 2)}"' if any(c in v for c in ';"\n') else v

    nombre = lambda v: f"{v:.2f}".replace(".", ",")  # noqa: E731
    lignes = [TITRES] + [[nom, nombre(ch), nombre(pr), nombre(ba)] for _, nom, ch, pr, ba in lignes_export(cr)]
    return ("﻿" + "\r\n".join(";".join(cellule(v) for v in l) for l in lignes)).encode("utf-8")


def export_excel(cr, mandat):
    """Classeur Excel : en-tête bleu foncé, catégories sur fond gris, montants en vert ou en rouge."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Compte de résultat"
    for lettre, largeur in zip("ABCD", (42, 18, 18, 18)):
        ws.column_dimensions[lettre].width = largeur
    bord = Side(style="thin", color="FFCCD3DD")
    bordure = Border(top=bord, bottom=bord, left=bord, right=bord)
    fond_entete = PatternFill("solid", fgColor="FF1F3A5F")
    fond_categorie = PatternFill("solid", fgColor="FFEEF1F6")
    format_ = '#,##0.00 "€";-#,##0.00 "€";0.00 "€"'

    ws.append(TITRES)
    for i, cellule in enumerate(ws[1], 1):
        cellule.font = Font(bold=True, color="FFFFFFFF")
        cellule.fill = fond_entete
        cellule.alignment = Alignment(horizontal="left" if i == 1 else "right", vertical="center")
    ws.row_dimensions[1].height = 22

    for type_, nom, *montants in lignes_export(cr):
        ws.append([nom, *montants])
        total, gras = type_ == "total", type_ != "classeur"
        for i, cellule in enumerate(ws[ws.max_row], 1):
            cellule.border = bordure
            if i == 1:
                cellule.alignment = Alignment(indent=2 if type_ == "classeur" else 0)
                cellule.font = Font(bold=gras, color="FFFFFFFF" if total else "FF000000")
            else:
                v = cellule.value
                couleur = ("FFFFB4B4" if total else "FFC62828") if v < 0 else \
                          ("FFB9F6CA" if total else "FF2E7D32") if v > 0 else ("FFFFFFFF" if total else "FF000000")
                cellule.number_format = format_
                cellule.alignment = Alignment(horizontal="right")
                cellule.font = Font(bold=gras, color=couleur)
            if type_ == "categorie":
                cellule.fill = fond_categorie
            if total:
                cellule.fill = fond_entete
    ws.append([])
    ws.append([f"Mandat {mandat['nom']} · exporté le {date.today():%d/%m/%Y}"])
    tampon = io.BytesIO()
    wb.save(tampon)
    return tampon.getvalue()


def export_pdf(cr, mandat, asso):
    """Compte de résultat en PDF : logo, titre, tableau complet (avec le hors CR et le non classé)."""
    rouge, vert, gris = colors.HexColor("#b3261e"), colors.HexColor("#1d7a43"), colors.HexColor("#5d6878")
    fond, bordure, bleu = colors.HexColor("#eef1f6"), colors.HexColor("#ccd3dd"), colors.HexColor("#1f3a5f")
    s_titre = ParagraphStyle("t", fontName="Helvetica-Bold", fontSize=16, leading=20)
    s_meta = ParagraphStyle("m", fontName="Helvetica", fontSize=8.5, leading=11, textColor=gris)

    donnees, styles = [TITRES], []

    def ligne(nom, m, type_):
        i = len(donnees)
        donnees.append([nom, *(montant_fr(m[k]) + "\xa0€" for k in ("charges", "produits", "balance"))])
        for col, k in enumerate(("charges", "produits", "balance"), 1):
            if m[k]:
                styles.append(("TEXTCOLOR", (col, i), (col, i), rouge if m[k] < 0 else vert))
        if type_ == "categorie":
            styles.extend([("BACKGROUND", (0, i), (-1, i), fond), ("FONT", (0, i), (-1, i), "Helvetica-Bold", 8.5)])
        elif type_ == "classeur":
            styles.append(("LEFTPADDING", (0, i), (0, i), 16))
        elif type_ == "total":
            styles.extend([("BACKGROUND", (0, i), (-1, i), bleu), ("FONT", (0, i), (-1, i), "Helvetica-Bold", 9),
                           ("TEXTCOLOR", (0, i), (0, i), colors.white)])
            for col, k in enumerate(("charges", "produits", "balance"), 1):
                couleur = colors.HexColor("#ffb4b4") if m[k] < 0 else colors.HexColor("#b9f6ca") if m[k] > 0 \
                    else colors.white
                styles.append(("TEXTCOLOR", (col, i), (col, i), couleur))
        elif type_ == "non-classe":
            styles.append(("TEXTCOLOR", (0, i), (0, i), gris))

    def bloc(hors):
        for c in cr["categories"]:
            if c["hors_cr"] == hors:
                ligne(c["nom"], c, "categorie")
                for k in c["classeurs"]:
                    ligne(k["nom"], k, "classeur")

    bloc(False)
    ligne("SOUS-TOTAUX", cr["total_cr"], "total")
    bloc(True)
    if any(c["hors_cr"] for c in cr["categories"]):
        ligne("RESTE HORS CR", cr["total_hors_cr"], "total")
    nc = cr["non_classe"]
    ligne(f"Non classé ({nc['nb']} ligne{'s' if nc['nb'] > 1 else ''})", nc, "non-classe")

    table = Table(donnees, colWidths=[86 * mm, 30 * mm, 30 * mm, 30 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), "Helvetica", 8.5),
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8.5),
        ("BACKGROUND", (0, 0), (-1, 0), bleu),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -1), 0.4, bordure),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
        *styles,
    ]))
    controle = "tout concorde" if not cr["ecart"] else f"écart de {euros_txt(cr['ecart'])}"
    debut, fin = date_longue(mandat["debut"]), date_longue(mandat["fin"])

    tampon = io.BytesIO()
    doc = SimpleDocTemplate(tampon, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=38 * mm,
                            bottomMargin=15 * mm, title=f"Compte de résultat {mandat['nom']}",
                            author=f"{asso['sigle']} - {asso['nom']}", creator="AML Factures")
    logo = ImageReader(str(LOGO))

    def page(c, d):
        c.saveState()
        c.drawImage(logo, 15 * mm, A4[1] - 33 * mm, 22 * mm, 22 * mm, mask="auto")
        c.setFont("Helvetica-Bold", 9.5)
        c.setFillColor(colors.HexColor("#1f5aa6"))
        c.drawString(41 * mm, A4[1] - 21 * mm, asso["nom"])
        c.setFont("Helvetica", 7)
        c.setFillColor(gris)
        c.drawRightString(A4[0] - 15 * mm, 9 * mm, f"Page {d.page}")
        c.restoreState()

    doc.build([
        Paragraph(f"Compte de résultat {escape(mandat['nom'])}", s_titre),
        Paragraph(escape(f"Mandat du {debut} au {fin} · solde total du relevé : {euros_txt(cr['solde_releve'])}"
                         f" · contrôle : {controle} · édité le {date.today():%d/%m/%Y}"), s_meta),
        Spacer(1, 6 * mm),
        table,
    ], onFirstPage=page, onLaterPages=page)
    return tampon.getvalue()
