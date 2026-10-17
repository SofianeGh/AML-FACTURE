"""PDF générés pour une facture METRO : récapitulatif des dépenses d'une catégorie
(VENTE, EVENT…), bilan des ventes (prix de vente, résultat) et bilan final (infos de la facture)."""
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
