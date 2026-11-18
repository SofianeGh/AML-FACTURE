"""PDF des devis et des factures de l'association, mis en page comme le modèle de devis de l'AML.

En-tête (logo, nom de l'association, numéro et date), coordonnées de l'association et cadre
du client, objet et lieu, tableau des lignes à bandeau gris, récapitulatif par taux de TVA et
totaux, puis la date de validité et la mention « Lu et approuvé » (devis) ou l'échéance et les
conditions de paiement (factures). Pied de page : SIRET, adresse, mention TVA et contacts.

Les positions sont en points comptés depuis le haut de la page (A4 : 595 × 842). Quand les
lignes ne tiennent pas sur une page, le tableau continue sur la suivante.
"""
import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas

from .aml_commun import LOGO, date_courte, date_longue, montant_fr, quantite_fr, taux_fr
from .commun import euros

HAUTEUR = A4[1]
GAUCHE, DROITE = 28, 570
NORMAL, GRAS = "Helvetica", "Helvetica-Bold"
BLEU = colors.HexColor("#1f5aa6")
NOIR = colors.HexColor("#1a1a1a")
GRIS = colors.HexColor("#555555")
FOND = colors.HexColor("#d9d9d9")
TRAIT = colors.HexColor("#c4c4c4")
CADRE = colors.HexColor("#9a9a9a")

TITRES = {"devis": "Devis", "facture": "Facture"}
# colonnes chiffrées : (titre, bord gauche, bord droit) ; la désignation occupe la gauche
COLONNES = [("Prix HT", 277, 343), ("Prix TTC", 343, 391), ("Quantité", 391, 438),
            ("Total HT", 438, 487), ("Total TTC", 487, 540), ("TVA", 540, DROITE)]
LARGEUR_DESIGNATION = COLONNES[0][1] - GAUCHE - 20
HAUT_BANDEAU = 13.5     # bandeau gris des titres de colonnes
CORPS_MIN = 159         # hauteur minimale du corps du tableau (comme sur le modèle)
PAS_LIGNE = 14.2        # hauteur d'une ligne d'article
INTERLIGNE = 9          # par ligne de texte en plus quand la désignation est longue
HAUT_TABLEAU_SUITE = 122  # haut du tableau sur les pages suivantes


class Page:
    """Dessin avec des ordonnées comptées depuis le haut ; sans canvas, rien n'est dessiné (mesure)."""

    def __init__(self, canvas=None):
        self.c = canvas

    def texte(self, x, y, s, police=NORMAL, taille=9.0, couleur=NOIR, align="g"):
        if not self.c or not s:
            return
        self.c.setFont(police, taille)
        self.c.setFillColor(couleur)
        dessin = {"g": self.c.drawString, "d": self.c.drawRightString, "c": self.c.drawCentredString}[align]
        dessin(x, HAUTEUR - y, s)

    def rect(self, x, y, largeur, hauteur, fond=None, bord=None, epaisseur=0.5):
        if not self.c:
            return
        self.c.saveState()
        if fond:
            self.c.setFillColor(fond)
        if bord:
            self.c.setStrokeColor(bord)
            self.c.setLineWidth(epaisseur)
        self.c.rect(x, HAUTEUR - y - hauteur, largeur, hauteur, fill=int(bool(fond)), stroke=int(bool(bord)))
        self.c.restoreState()

    def trait(self, x1, y1, x2, y2, couleur=TRAIT, epaisseur=0.5):
        if not self.c:
            return
        self.c.saveState()
        self.c.setStrokeColor(couleur)
        self.c.setLineWidth(epaisseur)
        self.c.line(x1, HAUTEUR - y1, x2, HAUTEUR - y2)
        self.c.restoreState()

    def image(self, image, x, y, largeur, hauteur):
        if self.c and image:
            self.c.drawImage(image, x, HAUTEUR - y - hauteur, largeur, hauteur, mask="auto")


def couper(texte, police, taille, largeur):
    """Lignes du texte coupées à la largeur donnée (les retours à la ligne saisis sont gardés)."""
    lignes = []
    for morceau in (texte or "").split("\n"):
        lignes += simpleSplit(morceau, police, taille, largeur) or [""]
    return lignes if texte else []


def deux_lignes(nom, police, taille):
    """« Association des Informaticiens Lyonnais » -> [« Association des », « Informaticiens Lyonnais »]"""
    mots = nom.split()
    if len(mots) < 2:
        return [nom]
    largeur = lambda mots_: stringWidth(" ".join(mots_), police, taille)  # noqa: E731
    coupure = min(range(1, len(mots)), key=lambda i: max(largeur(mots[:i]), largeur(mots[i:])))
    return [" ".join(mots[:coupure]), " ".join(mots[coupure:])]


# ---------------------------------------------------------------- en-tête

def entete(p, piece, asso, logo, premiere):
    """Logo, nom de l'association, numéro, date ; sur la 1re page aussi les adresses et l'objet.
    Renvoie le haut du tableau."""
    p.image(logo, GAUCHE, 28, 68, 68)
    for i, ligne in enumerate(deux_lignes(asso["nom"], GRAS, 9.5)):
        p.texte(106, 58.5 + 12.5 * i, ligne, GRAS, 9.5, BLEU)
    p.texte(289, 67.5, f"{TITRES[piece['type']]} {piece['numero']}", GRAS, 13)
    p.texte(289, 80, f"le {date_longue(piece['date'], avec_jour=True)}", taille=7.5)
    if piece.get("devis_numero"):
        p.texte(289, 90, f"Suivant devis {piece['devis_numero']}", taille=7.5)
    if not premiere:
        return HAUT_TABLEAU_SUITE

    p.texte(GAUCHE, 107.5, asso["sigle"], GRAS, 10)
    p.texte(GAUCHE, 125, asso["adresse"].upper(), taille=9.5)
    p.texte(GAUCHE, 140, " - ".join(filter(None, [asso["ville"], asso["pays"]])).upper(), taille=9.5)
    bas_client = cadre_client(p, piece)
    bas_objet = bloc_objet(p, piece)
    return max(240, bas_client + 7, bas_objet + 14)


def cadre_client(p, piece):
    """Cadre du client à droite : nom en gras, adresse, téléphone et e-mail. Renvoie son bas."""
    x, haut, largeur = 286, 134, 258
    xt, lt = x + 11, largeur - 22
    y = haut + 14
    noms = couper(piece["client_nom"], GRAS, 9.5, lt)
    for i, s in enumerate(noms):
        p.texte(xt, y + 10.5 * i, s, GRAS, 9.5)
    y += 10.5 * (len(noms) - 1)
    adresse = couper(piece.get("client_adresse"), NORMAL, 9.5, lt)
    if adresse:
        y += 16
        for i, s in enumerate(adresse):
            p.texte(xt, y + 12.3 * i, s, taille=9.5)
        y += 12.3 * (len(adresse) - 1)
    contacts = [f"Téléphone : {piece['client_telephone']}" if piece.get("client_telephone") else None,
                f"E-mail : {piece['client_email']}" if piece.get("client_email") else None]
    contacts = [c for c in contacts if c]
    if contacts:
        y += 17
        for i, s in enumerate(contacts):
            p.texte(xt, y + 9 * i, s, taille=7)
        y += 9 * (len(contacts) - 1)
    bas = max(haut + 99, y + 6)
    p.rect(x, haut, largeur, bas - haut, bord=CADRE, epaisseur=0.6)
    return bas


def bloc_objet(p, piece):
    """Objet et lieu en gras, puis la description, à gauche du cadre client. Renvoie la dernière ligne."""
    largeur = 246
    y, derniere = 173, 150
    if piece.get("objet"):
        for s in simpleSplit(f"Objet : {piece['objet']}", GRAS, 9, largeur):
            p.texte(GAUCHE, y, s, GRAS, 9)
            derniere, y = y, y + 11
        y = derniere + 13
    if piece.get("lieu"):
        retrait = stringWidth("Lieu : ", GRAS, 9)
        premiere = True
        for morceau in piece["lieu"].split("\n"):
            for s in simpleSplit(morceau, GRAS, 9, largeur - retrait) or [""]:
                if premiere:
                    p.texte(GAUCHE, y, f"Lieu : {s}", GRAS, 9)
                else:  # lignes suivantes alignées après « Lieu : », comme sur le modèle
                    p.texte(GAUCHE + retrait, y, s, GRAS, 9)
                premiere = False
                derniere, y = y, y + 10.5
        y = derniere + 21
    if piece.get("description"):
        for s in couper(piece["description"], NORMAL, 9.5, largeur):
            p.texte(GAUCHE, y, s, taille=9.5)
            derniere, y = y, y + 12
    return derniere


# ---------------------------------------------------------------- tableau

def bandeau(p, haut, nb_lignes, nature):
    p.rect(GAUCHE, haut, DROITE - GAUCHE, HAUT_BANDEAU, fond=FOND)
    y = haut + 9.5
    p.texte(GAUCHE + 3, y, f"Désignation - Nombre de lignes : {nb_lignes} - {nature}", GRAS, 7.5)
    for titre, _, droite in COLONNES:
        p.texte(droite - 4, y, titre, GRAS, 7.5, align="d")


def mesurer(ligne):
    textes = couper(ligne["designation"], NORMAL, 7.5, LARGEUR_DESIGNATION)
    return textes, PAS_LIGNE + INTERLIGNE * (len(textes) - 1)


def dessiner_ligne(p, haut, ligne, textes):
    y = haut + 9.6
    for i, s in enumerate(textes):
        p.texte(GAUCHE + 12, y + INTERLIGNE * i, s, taille=7.5)
    valeurs = [montant_fr(ligne["prix_ht"], 4), montant_fr(ligne["prix_ttc"]), quantite_fr(ligne["quantite"]),
               montant_fr(ligne["total_ht"]), montant_fr(ligne["total_ttc"]),
               "-" if ligne["tva"] is None else taux_fr(ligne["tva"])]
    for (titre, _, droite), valeur in zip(COLONNES, valeurs):
        p.texte(droite - 5, y, valeur, GRAS if titre == "Total TTC" else NORMAL, 7.5, align="d")


# ---------------------------------------------------------------- sous le tableau

def bloc_final(p, piece, calcul, asso, haut):
    """Totaux, récapitulatif par taux, puis les mentions du devis ou de la facture.
    Renvoie la hauteur occupée sous le tableau."""
    # totaux, à droite
    p.rect(354, haut + 42, DROITE - 354, 22, fond=FOND)
    p.trait(354, haut, 354, haut + 64, NOIR, 0.6)
    p.texte(497, haut + 17, "Total HT :", taille=9.5, align="d")
    p.texte(DROITE - 3, haut + 17, euros(calcul["total_ht"]), GRAS, 9.5, align="d")
    p.texte(497, haut + 35, "Total TVA :", taille=9.5, align="d")
    p.texte(DROITE - 3, haut + 35, euros(calcul["total_tva"]), GRAS, 9.5, align="d")
    p.texte(497, haut + 57, "Total TTC :", GRAS, 11, align="d")
    p.texte(DROITE - 3, haut + 57, euros(calcul["total_ttc"]), GRAS, 11, align="d")

    # récapitulatif par taux de TVA, à gauche
    xs = [GAUCHE, 113, 160, 203, 246]
    p.rect(GAUCHE, haut + 10.5, xs[-1] - GAUCHE, 10.5, fond=FOND)
    for titre, g, d in zip(["Taux", "HT", "TVA", "TTC"], xs, xs[1:]):
        p.texte((g + d) / 2, haut + 18.3, titre, GRAS, 7, align="c")
    for i, t in enumerate(calcul["taux"]):
        y = haut + 21 + 14 * i
        valeurs = [taux_fr(t["taux"]), montant_fr(t["ht"]), montant_fr(t["tva"]), montant_fr(t["ttc"])]
        for valeur, g, d in zip(valeurs, xs, xs[1:]):
            p.texte((g + d) / 2, y + 12.5, valeur, taille=7, align="c")
        for x in xs[1:-1]:
            p.trait(x, y + 2, x, y + 15.5)
    y0 = haut + max(64, 25 + 14 * len(calcul["taux"])) + 16

    if piece["type"] == "devis":
        if piece.get("validite"):
            p.texte(GAUCHE, y0, f"Date de validité : {date_courte(piece['validite'])}", GRAS, 7.5)
        p.texte(506, y0 + 10, "Signature précédée de la mention", GRAS, 7.5, align="c")
        p.texte(506, y0 + 19.5, "\"Lu et approuvé, bon pour accord\"", GRAS, 7.5, align="c")
        notes = couper(piece.get("notes"), NORMAL, 7.5, 380)
        for i, s in enumerate(notes):
            p.texte(GAUCHE, y0 + 14 + 9.5 * i, s, taille=7.5)
        return (y0 - haut) + max(19.5 + 60, 14 + 9.5 * len(notes))

    largeur = DROITE - GAUCHE
    lignes = []  # (texte, police, taille, couleur)
    if piece.get("echeance"):
        lignes.append((f"Date d'échéance : {date_courte(piece['echeance'])}", GRAS, 7.5, NOIR))
    if piece.get("conditions"):
        lignes += [(s, NORMAL, 7.5, NOIR) for s in couper(f"Conditions de paiement : {piece['conditions']}",
                                                        NORMAL, 7.5, largeur)]
    if asso.get("iban"):
        rib = f"Règlement par virement - IBAN : {asso['iban']}" + (f" - BIC : {asso['bic']}" if asso.get("bic") else "")
        lignes.append((rib, NORMAL, 7.5, NOIR))
    lignes += [(s, NORMAL, 7.5, NOIR) for s in couper(piece.get("notes"), NORMAL, 7.5, largeur)]
    lignes += [(s, NORMAL, 7, GRIS) for s in couper(asso.get("mention_retard"), NORMAL, 7, largeur)]
    for i, (s, police, taille, couleur) in enumerate(lignes):
        p.texte(GAUCHE, y0 + 10 * i, s, police, taille, couleur)
    return (y0 - haut) + 10 * max(0, len(lignes) - 1) + 12


# ---------------------------------------------------------------- pied de page

def lignes_pied(asso):
    fixes = [
        " - ".join(filter(None, [asso["sigle"], asso["nom"], f"Siret {asso['siret']}" if asso["siret"] else ""])),
        " - ".join(filter(None, [", ".join(filter(None, [asso["adresse"], asso["ville"]])), asso["mention_tva"]])),
    ]
    contacts = [c for c in (asso.get("contacts") or "").split("\n") if c.strip()]
    return [s for s in fixes if s], contacts


def haut_pied(pied):
    fixes, contacts = pied
    n = len(fixes) + len(contacts)
    return HAUTEUR - 27.5 - (9 + 8 * max(0, n - 1) + (1 if contacts else 0))


def dessiner_pied(p, pied, haut, page, nb_pages):
    p.trait(117, haut, 573, haut, CADRE, 0.5)
    fixes, contacts = pied
    y = haut + 9
    for s in fixes:
        p.texte(345, y, s, taille=7, align="c")
        y += 8
    y += 1
    for s in contacts:
        p.texte(345, y, s, taille=7, align="c")
        y += 8
    p.texte(DROITE, haut + 17, f"Page {page} / {nb_pages}", taille=7, align="d")


# ---------------------------------------------------------------- document

def paginer(hauteurs, haut_premiere, limite, limite_finale):
    """Répartit les lignes sur les pages : [(haut du tableau, première ligne, fin), …].
    La dernière page doit garder la place des totaux ; une page suivante reçoit au moins une ligne."""
    debut = lambda haut: haut + HAUT_BANDEAU + 8  # noqa: E731
    pages, i, haut, n = [], 0, haut_premiere, len(hauteurs)
    while True:
        y, j = debut(haut), i
        while j < n and y + hauteurs[j] <= limite_finale:
            y, j = y + hauteurs[j], j + 1
        if j == n:
            pages.append((haut, i, n))
            return pages
        y, j = debut(haut), i
        while j < n - 1 and y + hauteurs[j] <= limite:
            y, j = y + hauteurs[j], j + 1
        j = max(j, i + 1)
        pages.append((haut, i, j))
        i, haut = j, HAUT_TABLEAU_SUITE


def generer_piece(piece, calcul, asso):
    """PDF (bytes) d'un devis ou d'une facture. `calcul` : résultat de aml.devis.calculer(piece)."""
    titre = f"{TITRES[piece['type']]} {piece['numero']}"
    mesures = [mesurer(l) for l in calcul["lignes"]]
    pied = lignes_pied(asso)
    y_pied = haut_pied(pied)
    mesure = Page()
    haut_premiere = entete(mesure, piece, asso, None, premiere=True)
    h_final = bloc_final(mesure, piece, calcul, asso, 0)
    pages = paginer([h for _, h in mesures], haut_premiere, y_pied - 14, y_pied - 18 - h_final)

    tampon = io.BytesIO()
    c = Canvas(tampon, pagesize=A4)
    c.setTitle(titre)
    c.setAuthor(f"{asso['sigle']} - {asso['nom']}")
    c.setSubject(piece.get("objet") or titre)
    c.setCreator("AML Factures")
    logo = ImageReader(str(LOGO))
    for numero_page, (haut, i, j) in enumerate(pages, 1):
        p = Page(c)
        derniere = numero_page == len(pages)
        entete(p, piece, asso, logo, premiere=numero_page == 1)
        bandeau(p, haut, len(calcul["lignes"]), piece["nature"])
        haut_corps = haut + HAUT_BANDEAU
        y = haut_corps + 8
        for k in range(i, j):
            dessiner_ligne(p, y, calcul["lignes"][k], mesures[k][0])
            y += mesures[k][1]
        bas = max(y + 6, min(haut_corps + CORPS_MIN, y_pied - 10 - h_final)) if derniere else y + 6
        for _, gauche, _ in COLONNES:
            p.trait(gauche, haut_corps, gauche, bas)
        p.trait(GAUCHE, bas, DROITE, bas, NOIR, 0.9)
        if derniere:
            bloc_final(p, piece, calcul, asso, bas)
        else:
            p.texte(DROITE, bas + 12, "Suite page suivante", taille=7, couleur=GRIS, align="d")
        dessiner_pied(p, pied, y_pied, numero_page, len(pages))
        c.showPage()
    c.save()
    return tampon.getvalue()
