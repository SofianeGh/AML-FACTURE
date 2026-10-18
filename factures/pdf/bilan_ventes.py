"""PDF « Bilan des ventes » : prix de vente de chaque article et résultat de la course."""
import io
from datetime import date
from decimal import Decimal
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .commun import (BORDURE, CATEGORIES, FOND, GRIS, ROUGE, S_CELL, S_META, S_NOTE, S_SOUS, S_TITRE, VERT,
                     bloc_note, euros, qte_txt, texte_reglages, _decimal)


def generer_ventes(facture, categories, vente, nom_facture, auteur=None, note=None, conducteur=None):
    """PDF « Bilan des ventes » : prix de vente de chaque article et résultat de la course.

    `categories` : la catégorie de chaque ligne ; `vente` : choix faits dans l'application,
    {"pieces": [...], "prix": [...], "optimal": [...], "reglages": {...}} (une valeur par ligne).
    Calculs identiques à ceux de l'interface.
    """
    taxe = _decimal(vente["reglages"].get("taxe"))
    par_cat = {cle: Decimal(0) for cle in CATEGORIES}
    nb_par_cat = {cle: categories.count(cle) for cle in CATEGORIES}
    ca = tpe = Decimal(0)

    articles = [["Article", "Pièces", "Coût TTC\n/ pièce", "Prix\noptimal", "Prix de\nvente", "Marge\n/ pièce", "CA prévu"]]
    a_perte = []
    for i, (ligne, cat) in enumerate(zip(facture["lignes"], categories)):
        ttc = Decimal(str(ligne["montant_net_ht"])) * (1 + Decimal(str(ligne["tva_taux"] or 0)) / 100)
        par_cat[cat] += ttc
        if cat != "vente":
            continue
        nb = Decimal(str(ligne["unites"])) * vente["pieces"][i]
        cout = ttc / nb if nb else Decimal(0)
        pv = _decimal(vente["prix"][i])
        marge = pv - cout - taxe
        ca += pv * nb
        tpe += taxe * nb
        if marge < 0:
            a_perte.append(len(articles))
        articles.append([
            Paragraph(escape(ligne["designation"]), S_CELL), qte_txt(float(nb)), euros(cout, 3),
            euros(_decimal(vente["optimal"][i])), euros(pv), euros(marge), euros(pv * nb),
        ])

    total = sum(par_cat.values())
    benefice = ca - par_cat["vente"] - tpe
    cadeau = par_cat["cadeau"]

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm, bottomMargin=15 * mm,
        title=f"Bilan des ventes - facture METRO du {facture['date']}", author="Factures METRO",
    )
    meta = [f"N° {facture['numero']}" if facture.get("numero") else None,
            f"ticket {facture['ticket']}" if facture.get("ticket") else None,
            f"facture : {nom_facture}",
            f"établi par {auteur}" if auteur else None]
    sous_titre = f"Facture METRO du {escape(facture['date'] or '?')}"
    if conducteur:
        sous_titre += f" · conducteur : {escape(conducteur)}"
    elements = [
        Paragraph("Bilan des ventes", S_TITRE),
        Paragraph(sous_titre, S_SOUS),
        Paragraph(escape(" · ".join(m for m in meta if m)), S_META),
        Paragraph(escape(texte_reglages(vente["reglages"])), S_META),
        *bloc_note(note),
        Spacer(1, 6 * mm),
        Paragraph("Prix de vente", S_SOUS),
        Spacer(1, 2 * mm),
    ]

    if len(articles) > 1:
        table = Table(articles, colWidths=[64 * mm, 14 * mm, 20 * mm, 19 * mm, 19 * mm, 20 * mm, 24 * mm],
                      repeatRows=1)
        style = [
            ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 7.5),
            ("TEXTCOLOR", (0, 0), (-1, 0), GRIS),
            ("FONT", (1, 1), (-1, -1), "Helvetica", 8.5),
            ("FONT", (4, 1), (4, -1), "Helvetica-Bold", 9),
            ("BACKGROUND", (4, 0), (4, -1), colors.HexColor("#fff6d6")),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LINEBELOW", (0, 0), (-1, -1), 0.5, BORDURE),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]
        style += [("TEXTCOLOR", (4, r), (5, r), ROUGE) for r in a_perte]
        table.setStyle(TableStyle(style))
        elements.append(table)
        if a_perte:
            elements += [Spacer(1, 2 * mm),
                         Paragraph(f"En rouge : vendu à perte ({len(a_perte)} article{'s' if len(a_perte) > 1 else ''}).",
                                   S_NOTE)]
    else:
        elements.append(Paragraph("Aucun article de cette facture n'est dans la catégorie Vente.", S_META))

    # -- résultat de la course
    resume = [["Total de la facture (TTC)", euros(total)]]
    resume += [[f"dont {libelle} ({nb_par_cat[cle]} ligne{'s' if nb_par_cat[cle] > 1 else ''})", euros(par_cat[cle])]
               for cle, (_, libelle) in CATEGORIES.items() if nb_par_cat[cle]]
    debut_ventes = len(resume)
    resume += [
        ["Chiffre d'affaires si tout est vendu (prix de vente)", euros(ca)],
        ["dont taxe TPE", euros(tpe)],
        ["Bénéfice sur les ventes (hors taxe TPE)", euros(benefice)],
    ]
    if cadeau:
        resume += [[f"Cadeau conducteur ({conducteur})" if conducteur else "Cadeau conducteur", euros(-cadeau)],
                   ["Bénéfice après cadeau conducteur", euros(benefice - cadeau)]]
    final = benefice - cadeau
    style = [
        ("FONT", (0, 0), (-1, -1), "Helvetica", 9.5),
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9.5),
        ("TEXTCOLOR", (0, 1), (0, debut_ventes - 1), GRIS),
        ("LEFTPADDING", (0, 1), (0, debut_ventes - 1), 14),
        ("LINEABOVE", (0, debut_ventes), (-1, debut_ventes), 0.5, BORDURE),
        ("FONT", (0, -1), (-1, -1), "Helvetica-Bold", 11),
        ("BACKGROUND", (0, -1), (-1, -1), FOND),
        ("TEXTCOLOR", (1, -1), (1, -1), ROUGE if final < 0 else VERT),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    if cadeau:
        style.append(("TEXTCOLOR", (1, -2), (1, -2), ROUGE))
    table = Table(resume, colWidths=[110 * mm, 35 * mm], hAlign="RIGHT")
    table.setStyle(TableStyle(style))
    elements += [
        Spacer(1, 8 * mm),
        Paragraph("Résultat de la course", S_SOUS),
        Spacer(1, 2 * mm),
        table,
        Spacer(1, 10 * mm),
        Paragraph(
            "Prix de vente et pièces par unité tels que choisis dans l'application au moment de l'envoi. "
            "Coûts calculés à partir des lignes de la facture METRO (remises déduites). "
            f"Document généré le {date.today():%d/%m/%Y} par l'application Factures METRO.", S_NOTE),
    ]
    doc.build(elements)
    return buf.getvalue()
