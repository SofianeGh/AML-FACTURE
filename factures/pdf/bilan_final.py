"""PDF « Bilan final » : toutes les informations d'une facture, sans prix de vente."""
import io
from datetime import date
from decimal import Decimal
from xml.sax.saxutils import escape

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .commun import (BORDURE, CATEGORIES, FOND, GRIS, S_CELL, S_CELL_SUB, S_NOTE, S_META, S_SOUS, S_TITRE, S_TOTAL,
                     bloc_note, euros, qte_txt, taux_txt)


def _style_tableau(entete=True, total=False, droite_depuis=1):
    style = [
        ("FONT", (0, 0), (-1, -1), "Helvetica", 8.5),
        ("ALIGN", (droite_depuis, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, BORDURE),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    if entete:
        style += [("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 7.5), ("TEXTCOLOR", (0, 0), (-1, 0), GRIS)]
    if total:
        style += [("FONT", (0, -1), (-1, -1), "Helvetica-Bold", 9), ("BACKGROUND", (0, -1), (-1, -1), FOND)]
    return TableStyle(style)


def generer_bilan(facture, categories, nom_facture, auteur=None, note=None, conducteur=None):
    """PDF « Bilan final » : toutes les informations de la facture, sans prix de vente.

    Identité de la facture et conducteur, montants imprimés par METRO (récapitulatif TVA, total à
    payer), répartition par catégorie, puis le détail de chaque ligne avec sa catégorie.
    """
    lignes = facture["lignes"]
    ttc_ligne = [Decimal(str(l["montant_net_ht"])) * (1 + Decimal(str(l["tva_taux"] or 0)) / 100) for l in lignes]
    remises = sum(Decimal(str(l["remise_ht"])) for l in lignes)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm, bottomMargin=15 * mm,
        title=f"Bilan final - facture METRO du {facture['date']}", author="Factures METRO",
    )
    sous_titre = f"Facture METRO du {escape(facture['date'] or '?')}"
    if conducteur:
        sous_titre += f" · conducteur : {escape(conducteur)}"
    elements = [
        Paragraph("Bilan final", S_TITRE),
        Paragraph(sous_titre, S_SOUS),
        Paragraph(escape(" · ".join(filter(None, [f"facture : {nom_facture}",
                                                   f"établi par {auteur}" if auteur else None]))), S_META),
        *bloc_note(note),
        Spacer(1, 6 * mm),
    ]

    # -- informations
    infos = [
        ["Date de la facture", facture["date"] or "?"],
        ["N° de facture", facture.get("numero") or "?"],
        ["Ticket de caisse", facture.get("ticket") or "?"],
        ["Conducteur", conducteur or "—"],
        ["Lignes articles", str(len(lignes))],
        ["Unités achetées", qte_txt(sum(l["unites"] for l in lignes))],
    ]
    if remises:
        infos.append(["Remises METRO (HT)", f"−{euros(remises)}"])
    infos.append(["Contrôle des lignes",
                  "conforme au récapitulatif TVA de METRO" if facture.get("controle_ok") else "écart avec le récapitulatif TVA"])
    table = Table(infos, colWidths=[55 * mm, 125 * mm], hAlign="LEFT")
    table.setStyle(_style_tableau(entete=False, droite_depuis=2))
    table.setStyle(TableStyle([("TEXTCOLOR", (0, 0), (0, -1), GRIS),
                               ("FONT", (1, 0), (1, -1), "Helvetica-Bold", 9)]))
    elements += [Paragraph("Informations", S_SOUS), Spacer(1, 2 * mm), table, Spacer(1, 7 * mm)]

    # -- montants imprimés par METRO
    montants = [["Code TVA", "Taux", "Total HT", "TVA", "Total TTC"]]
    for code, t in sorted(facture.get("tva", {}).items()):
        montants.append([code, taux_txt(t["taux"]), euros(t["ht"]), euros(t["tva"]), euros(t["ttc"])])
    total_tva = sum(Decimal(str(t["tva"])) for t in facture.get("tva", {}).values())
    montants.append(["Total", "",
                     euros(facture["total_ht"]) if facture.get("total_ht") is not None else "?",
                     euros(total_tva),
                     euros(facture["total_ttc"]) if facture.get("total_ttc") is not None else "?"])
    table = Table(montants, colWidths=[25 * mm, 25 * mm, 35 * mm, 30 * mm, 35 * mm], hAlign="LEFT")
    table.setStyle(_style_tableau(total=True))
    elements += [Paragraph("Montants (récapitulatif METRO)", S_SOUS), Spacer(1, 2 * mm), table]
    if facture.get("total_ttc") is not None:
        elements += [Spacer(1, 3 * mm),
                     Paragraph(f"Total à payer : {euros(facture['total_ttc'])}", S_TOTAL)]
    elements.append(Spacer(1, 7 * mm))

    # -- répartition par catégorie
    repartition = [["Catégorie", "Lignes", "Total HT", "Total TTC"]]
    for cle, (_, libelle) in CATEGORIES.items():
        idx = [i for i, c in enumerate(categories) if c == cle]
        if idx:
            repartition.append([libelle, str(len(idx)),
                                euros(sum(Decimal(str(lignes[i]["montant_net_ht"])) for i in idx)),
                                euros(sum(ttc_ligne[i] for i in idx))])
    repartition.append(["Total", str(len(lignes)),
                        euros(sum(Decimal(str(l["montant_net_ht"])) for l in lignes)), euros(sum(ttc_ligne))])
    table = Table(repartition, colWidths=[50 * mm, 20 * mm, 35 * mm, 35 * mm], hAlign="LEFT")
    table.setStyle(_style_tableau(total=True))
    elements += [Paragraph("Répartition par catégorie", S_SOUS), Spacer(1, 2 * mm), table, Spacer(1, 7 * mm)]

    # -- détail des lignes
    detail = [["Article", "Réf.", "Catégorie", "Qté", "PU HT", "Total HT", "TVA", "Total TTC"]]
    for l, cat, ttc in zip(lignes, categories, ttc_ligne):
        article = [Paragraph(escape(l["designation"]), S_CELL)]
        sous = [l["categorie"]] + ([f"remise −{euros(l['remise_ht'])} HT incluse"] if l["remise_ht"] else [])
        article.append(Paragraph(escape(" · ".join(sous)), S_CELL_SUB))
        detail.append([article, l["article"], CATEGORIES[cat][1], qte_txt(l["unites"]),
                       euros(l["cout_unitaire_ht"], 3), euros(l["montant_net_ht"]), taux_txt(l["tva_taux"]),
                       euros(ttc)])
    table = Table(detail, colWidths=[60 * mm, 16 * mm, 25 * mm, 11 * mm, 18 * mm, 18 * mm, 13 * mm, 19 * mm],
                  repeatRows=1)
    table.setStyle(_style_tableau(droite_depuis=3))
    table.setStyle(TableStyle([("FONT", (2, 1), (2, -1), "Helvetica", 7.5)]))
    elements += [
        Paragraph("Détail des lignes", S_SOUS),
        Spacer(1, 2 * mm),
        table,
        Spacer(1, 10 * mm),
        Paragraph(
            "Montants repris de la facture METRO ; totaux par catégorie et par ligne calculés à partir de ses "
            "lignes (remises déduites). Les prix de vente sont dans le « Bilan des ventes ». "
            f"Document généré le {date.today():%d/%m/%Y} par l'application Factures METRO.", S_NOTE),
    ]
    doc.build(elements)
    return buf.getvalue()
