"""PDF « récapitulatif » : les lignes d'une facture classées dans une catégorie (VENTE, EVENT…)."""
import io
from datetime import date
from decimal import Decimal
from xml.sax.saxutils import escape

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .commun import (BORDURE, CATEGORIES, FOND, GRIS, S_CELL, S_CELL_SUB, S_META, S_NOTE, S_SOUS, S_TITRE, S_TOTAL,
                     bloc_note, euros, qte_txt, taux_txt, totaux_par_taux, _arrondi)


def generer_recap(facture, categorie, lignes, nom_facture, note=None, conducteur=None):
    """Retourne le PDF (bytes) listant `lignes` (lignes de `facture` classées dans `categorie`)."""
    libelle = CATEGORIES[categorie][1]
    if categorie == "cadeau" and conducteur:
        libelle = f"{libelle} : {conducteur}"
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm, bottomMargin=15 * mm,
        title=f"{libelle} - facture METRO du {facture['date']}", author="Factures METRO",
    )

    meta = [f"N° {facture['numero']}" if facture.get("numero") else None,
            f"ticket {facture['ticket']}" if facture.get("ticket") else None,
            f"facture : {nom_facture}",
            f"conducteur : {conducteur}" if conducteur else None,
            f"{len(lignes)} ligne{'s' if len(lignes) > 1 else ''} sur {len(facture['lignes'])}"]
    elements = [
        Paragraph(f"Dépenses « {escape(libelle)} »", S_TITRE),
        Paragraph(f"Facture METRO du {escape(facture['date'] or '?')}", S_SOUS),
        Paragraph(escape(" · ".join(m for m in meta if m)), S_META),
        *bloc_note(note),
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
