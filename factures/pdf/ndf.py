"""PDF « Note de frais » sur le modèle de l'AML : attestation sur l'honneur, cadre de signature,
puis une page d'annexe par justificatif (photo du ticket ou page du PDF).
"""
import io
import re
from collections import Counter
from decimal import Decimal
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Flowable, Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer

from .aml_commun import LOGO, date_longue
from .commun import euros

MARGE = 12 * mm
LOGO_TAILLE = 25 * mm
LOGO_HAUT = 11 * mm      # distance entre le haut de la page et le logo
HAUT_TEXTE = LOGO_HAUT + LOGO_TAILLE + 4 * mm
S_TEXTE = ParagraphStyle("ndf", fontName="Helvetica", fontSize=10, leading=13.5)
BLANC = 11               # une ligne vide entre deux paragraphes, comme sur le modèle
ACCORDS = {"M.": ("soussigné", "né"), "Mme": ("soussignée", "née")}
LETTRES = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _gras(texte):
    return f"<b>{escape(texte)}</b>"


def _ordinaux(texte_echappe):
    """« Lyon 7e arrondissement » -> 7<super>e</super>, comme sur le modèle."""
    return re.sub(r"\b(\d+)(er|re|e|ème)\b", r"\1<super>\2</super>", texte_echappe)


def _de(nom):
    return "de l’" if nom[:1].lower() in "aeiouyhéèêàâîôû" else "de "


def justificatif_court(depense):
    """« justificatif de paiement Restaurant du Parc n° 12345 » (liste des pièces jointes)."""
    nom = depense["fournisseur"].split(",")[0].strip()
    return f"justificatif de paiement {nom}" + (f" n° {depense['recu']}" if depense["recu"] else "")


def justificatif_detail(depense):
    """Description complète, en tête de la page d'annexe."""
    recu = f", reçu n° {depense['recu']}" if depense["recu"] else ""
    return (f"justificatif de paiement, {depense['fournisseur']}{recu} du {date_longue(depense['date'])}, "
            f"{euros(depense['montant'])} TTC.")


class CadreSignature(Flowable):
    """Cadre pointillé avec la signature dessinée, ou vide pour signer à la main."""

    def __init__(self, png=None, largeur=78 * mm, hauteur=27 * mm):
        super().__init__()
        self.png, self.largeur, self.hauteur = png, largeur, hauteur

    def wrap(self, *_):
        return self.largeur, self.hauteur

    def draw(self):
        c = self.canv
        c.saveState()
        c.setStrokeColor(colors.HexColor("#9a9a9a"))
        c.setLineWidth(0.6)
        c.setDash(2, 2)
        c.rect(0, 0, self.largeur, self.hauteur)
        c.restoreState()
        if self.png:
            image = ImageReader(io.BytesIO(self.png))
            largeur, hauteur = image.getSize()
            echelle = min((self.largeur - 10) / largeur, (self.hauteur - 8) / hauteur)
            l, h = largeur * echelle, hauteur * echelle
            c.drawImage(image, (self.largeur - l) / 2, (self.hauteur - h) / 2, l, h, mask="auto")


def generer_ndf(note, asso, signature=None, annexes=()):
    """PDF (bytes) de la note de frais.

    `signature` : PNG ou None. `annexes` : [(index de la dépense, (jpeg, largeur, hauteur)), …]
    dans l'ordre des dépenses ; chaque image fait une page d'annexe.
    """
    soussigne, ne = ACCORDS[note["civilite"]]
    personne = f"{note['civilite']} {note['prenom']} {note['nom'].upper()}"
    depenses = note["depenses"]
    total = sum((Decimal(str(d["montant"])) for d in depenses), Decimal(0))
    une_date = len({d["date"] for d in depenses}) == 1

    identite = "<br/>".join([
        "<b>Objet :</b> Attestation sur l’honneur pour note de frais.",
        f"Je {soussigne}, {_gras(personne)}, {ne} le {_gras(date_longue(note['naissance_date']))} à",
        f"<b>{_ordinaux(escape(note['naissance_lieu']))}</b>,",
        f"{_gras(note['qualite'])} de l’association {_gras(note['association'])}, "
        f"résidant {_gras(note['adresse'])},",
    ])
    liaison = note["liaison"]
    liaison = (escape(liaison) + ("" if liaison.endswith(("'", "’")) else " ")) if liaison else ""
    nom_asso = f"{asso['nom']} ({asso['sigle']})"
    attestation = (f"Atteste sur l’honneur avoir réalisé, pour le compte {_de(asso['nom'])}{_gras(nom_asso)}, "
                   f"les dépenses suivantes : {_gras(note['nature'])} {liaison}{_gras(note['evenement'])}.")
    achats = [f"Ces achats, d’un montant total de {_gras(euros(total) + ' TTC')}, ont été réalisés "
              + (f"le {_gras(date_longue(depenses[0]['date']))} :" if une_date else "aux dates suivantes :")]
    for i, d in enumerate(depenses):
        ligne = f"<b>{LETTRES[i]}. {escape(d['fournisseur'])}</b>"
        if not une_date:
            ligne += f", le {escape(date_longue(d['date']))}"
        if d["recu"]:
            ligne += f" (reçu n° {escape(d['recu'])})"
        if len(depenses) > 1:
            ligne += f" : {escape(euros(d['montant']))} TTC"
        achats.append(ligne)

    numeros = sorted({i for i, _ in annexes})  # dépenses qui ont un justificatif
    if numeros:
        n = len(numeros)
        liste = " ; ".join(escape(justificatif_court(depenses[i])) for i in numeros)
        pieces = f"{n} facture{'s' if n > 1 else ''} ({liste}, joint{'s' if n > 1 else ''} en annexe)."
    else:
        pieces = "aucune."

    elements = [
        Paragraph(identite, S_TEXTE), Spacer(1, BLANC),
        Paragraph(attestation, S_TEXTE), Spacer(1, BLANC),
        Paragraph("<br/>".join(achats), S_TEXTE), Spacer(1, BLANC),
        Paragraph("À titre exceptionnel, je vous prie de bien vouloir me rembourser l’intégralité de ces dépenses "
                  "sur la base des factures que je joins à ce courrier.", S_TEXTE), Spacer(1, BLANC),
        Paragraph("Aussi, j’ai pris connaissance des sanctions pénales auxquelles je m’expose en cas de fausse "
                  "déclaration. Fait pour servir et valoir ce que de droit.", S_TEXTE), Spacer(1, BLANC),
        Paragraph(f"Fait à {_gras(note['fait_a'])}, le {_gras(date_longue(note['fait_le']))}.", S_TEXTE),
        Spacer(1, 4),
        Paragraph(f"<b>Pièce(s) jointe(s) :</b> {pieces}", S_TEXTE), Spacer(1, BLANC + 2),
        KeepTogether([Paragraph(f"<b>Signature de<br/>{escape(personne)}</b>", S_TEXTE), Spacer(1, 3),
                      CadreSignature(signature)]),
    ]

    # une page par justificatif : titre de l'annexe puis l'image, aussi grande que possible
    largeur_cadre = A4[0] - 2 * MARGE - 12
    hauteur_cadre = A4[1] - HAUT_TEXTE - MARGE - 12 - 60
    rang = {i: k for k, i in enumerate(numeros, 1)}
    nb_pages, vues = Counter(i for i, _ in annexes), Counter()
    for i, (jpeg, largeur, hauteur) in annexes:
        vues[i] += 1
        titre = f"Annexe – Pièce jointe n° {rang[i]}"
        if nb_pages[i] > 1:
            titre += f" (page {vues[i]}/{nb_pages[i]})"
        echelle = min(largeur_cadre / largeur, hauteur_cadre / hauteur)
        elements += [PageBreak(),
                     Paragraph(f"<b>{titre} :</b> {escape(justificatif_detail(depenses[i]))}", S_TEXTE),
                     Spacer(1, 10),
                     Image(io.BytesIO(jpeg), width=largeur * echelle, height=hauteur * echelle)]

    tampon = io.BytesIO()
    doc = SimpleDocTemplate(
        tampon, pagesize=A4, leftMargin=MARGE, rightMargin=MARGE, topMargin=HAUT_TEXTE, bottomMargin=MARGE,
        title=f"Note de frais - {personne}", author=f"{asso['sigle']} - {asso['nom']}",
        subject=note["evenement"], creator="AML Factures",
    )
    logo = ImageReader(str(LOGO))

    def dessiner_logo(c, _doc):
        c.saveState()
        c.drawImage(logo, MARGE, A4[1] - LOGO_HAUT - LOGO_TAILLE, LOGO_TAILLE, LOGO_TAILLE, mask="auto")
        c.restoreState()

    doc.build(elements, onFirstPage=dessiner_logo, onLaterPages=dessiner_logo)
    return tampon.getvalue()
