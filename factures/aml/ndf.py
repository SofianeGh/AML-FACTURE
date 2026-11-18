"""Notes de frais : lecture du formulaire, justificatifs (photos ou PDF) et signature.

Les justificatifs sont envoyés un par un dès qu'on les choisit, convertis en JPEG (une image
par page pour un PDF) et gardés dans la base ; la note les rattache à ses dépenses quand elle
est enregistrée. La signature arrive en PNG depuis la zone de dessin du navigateur.
"""
import base64
import binascii
import io
from decimal import Decimal

import pypdfium2 as pdfium
from PIL import Image, ImageChops, ImageOps, UnidentifiedImageError

from ..commun import RequeteInvalide
from .champs import date_iso, nombre, slug, texte

CIVILITES = ("M.", "Mme")
STATUTS = {"a_rembourser": "À rembourser", "remboursee": "Remboursée"}
DEPENSES_MAX = 20
JUSTIFICATIFS_MAX = 30
PAGES_MAX = 10          # pages lues dans un justificatif PDF
COTE_MAX = 2000         # plus grand côté d'une image gardée (pixels)
SIGNATURE_MAX = 1_500_000  # taille maximale de la signature reçue (data URL)

Image.MAX_IMAGE_PIXELS = 80_000_000


def lire_note(data):
    if not isinstance(data, dict):
        raise RequeteInvalide("Données illisibles.")
    if data.get("civilite") not in CIVILITES:
        raise RequeteInvalide("Civilité invalide.")
    statut = data.get("statut") or "a_rembourser"
    if statut not in STATUTS:
        raise RequeteInvalide("Suivi invalide.")
    note = {
        "civilite": data["civilite"],
        "prenom": texte(data, "prenom", 60, "Prénom", obligatoire=True),
        "nom": texte(data, "nom", 60, "Nom", obligatoire=True),
        "naissance_date": date_iso(data, "naissance_date", "Date de naissance"),
        "naissance_lieu": texte(data, "naissance_lieu", 120, "Lieu de naissance", obligatoire=True),
        "qualite": texte(data, "qualite", 60, "Qualité", obligatoire=True),
        "association": texte(data, "association", 80, "Association", obligatoire=True),
        "adresse": texte(data, "adresse", 200, "Adresse", obligatoire=True),
        "nature": texte(data, "nature", 150, "Dépenses", obligatoire=True),
        "liaison": texte(data, "liaison", 80, "Liaison"),
        "evenement": texte(data, "evenement", 200, "Événement", obligatoire=True),
        "fait_a": texte(data, "fait_a", 60, "Fait à", obligatoire=True),
        "fait_le": date_iso(data, "fait_le", "Date de signature"),
        "statut": statut,
    }
    depenses = data.get("depenses")
    if not isinstance(depenses, list) or not depenses:
        raise RequeteInvalide("Ajoutez au moins une dépense.")
    if len(depenses) > DEPENSES_MAX:
        raise RequeteInvalide(f"{DEPENSES_MAX} dépenses au maximum.")
    note["depenses"], vus = [], set()
    for i, d in enumerate(depenses, 1):
        if not isinstance(d, dict):
            raise RequeteInvalide(f"Dépense {i} illisible.")
        justificatifs = d.get("justificatifs") or []
        if not isinstance(justificatifs, list) or not all(
                isinstance(j, int) and not isinstance(j, bool) and j > 0 for j in justificatifs):
            raise RequeteInvalide(f"Dépense {i} : justificatifs invalides.")
        if vus & set(justificatifs) or len(set(justificatifs)) != len(justificatifs):
            raise RequeteInvalide("Un même justificatif est joint deux fois.")
        vus |= set(justificatifs)
        note["depenses"].append({
            "fournisseur": texte(d, "fournisseur", 200, f"Dépense {i} : fournisseur", obligatoire=True),
            "date": date_iso(d, "date", f"Dépense {i} : date"),
            "recu": texte(d, "recu", 40, f"Dépense {i} : n° de reçu"),
            "montant": round(nombre(d.get("montant"), f"Dépense {i} : montant", 0.01, 1_000_000), 2),
            "justificatifs": justificatifs,
        })
    if len(vus) > JUSTIFICATIFS_MAX:
        raise RequeteInvalide(f"{JUSTIFICATIFS_MAX} justificatifs au maximum par note de frais.")
    return note


def total(note):
    return sum((Decimal(str(d["montant"])) for d in note["depenses"]), Decimal(0))


def personne(note):
    return f"{note['prenom']} {note['nom'].upper()}"


def resume(note):
    """Colonnes de la liste : (date de signature, personne, objet, total TTC)."""
    return note["fait_le"], personne(note), note["evenement"], float(total(note))


def nom_fichier(note, sigle):
    """« NDF_AML_Jean_DUPONT_2026-11-11.pdf »"""
    morceaux = ["NDF", slug(sigle), slug(note["prenom"], "-"), slug(note["nom"], "-").upper(), note["fait_le"]]
    return "_".join(m for m in morceaux if m) + ".pdf"


# ---------------------------------------------------------------- justificatifs

def _en_jpeg(image):
    """Image redressée (EXIF), sur fond blanc, réduite à COTE_MAX -> (JPEG, largeur, hauteur)."""
    image = ImageOps.exif_transpose(image)
    if image.mode in ("RGBA", "LA", "PA") or (image.mode == "P" and "transparency" in image.info):
        image = image.convert("RGBA")
        fond = Image.new("RGB", image.size, "white")
        fond.paste(image, mask=image.getchannel("A"))
        image = fond
    else:
        image = image.convert("RGB")
    image.thumbnail((COTE_MAX, COTE_MAX))
    tampon = io.BytesIO()
    image.save(tampon, "JPEG", quality=82, optimize=True)
    return tampon.getvalue(), image.width, image.height


def preparer_justificatif(data):
    """Photo (JPEG, PNG…) ou PDF -> liste de (JPEG, largeur, hauteur), une par page."""
    if data[:5] == b"%PDF-":
        try:
            pdf = pdfium.PdfDocument(data)
        except pdfium.PdfiumError as exc:
            raise RequeteInvalide("PDF illisible (ou protégé par un mot de passe).") from exc
        try:
            if len(pdf) > PAGES_MAX:
                raise RequeteInvalide(f"PDF trop long : {PAGES_MAX} pages au maximum.")
            pages = []
            for i in range(len(pdf)):
                page = pdf[i]
                largeur, hauteur = page.get_size()
                echelle = min(150 / 72, COTE_MAX / max(largeur, hauteur, 1))
                pages.append(_en_jpeg(page.render(scale=echelle).to_pil()))
                page.close()
            return pages
        finally:
            pdf.close()
    try:
        image = Image.open(io.BytesIO(data))
        if image.format == "JPEG":
            image.draft("RGB", (COTE_MAX, COTE_MAX))  # lecture réduite : plus rapide pour les grosses photos
        image.load()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise RequeteInvalide("Format non reconnu : envoyez une photo (JPEG, PNG) ou un PDF. Les photos HEIC "
                              "d'iPhone ne sont pas lues : choisissez « Le plus compatible » dans Réglages → "
                              "Appareil photo → Formats, ou faites une capture d'écran.") from exc
    return [_en_jpeg(image)]


# ---------------------------------------------------------------- signature

def lire_signature(valeur):
    """Signature dessinée ou importée (data URL PNG) -> PNG à fond transparent recadré, ou None.

    Le papier blanc d'une signature photographiée devient transparent et le trait est passé
    en noir, pour qu'elle s'imprime proprement dans le cadre du PDF.
    """
    if valeur in (None, ""):
        return None
    if not isinstance(valeur, str) or not valeur.startswith("data:image/png;base64,"):
        raise RequeteInvalide("Signature illisible.")
    if len(valeur) > SIGNATURE_MAX:
        raise RequeteInvalide("Signature trop lourde : effacez-la et signez à nouveau.")
    try:
        image = Image.open(io.BytesIO(base64.b64decode(valeur.split(",", 1)[1], validate=True)))
        if image.width * image.height > 6_000_000:
            raise RequeteInvalide("Signature trop grande.")
        image.load()
    except (binascii.Error, UnidentifiedImageError, OSError, ValueError) as exc:
        raise RequeteInvalide("Signature illisible.") from exc
    image = image.convert("RGBA")
    # encre = pixels foncés ; le blanc et le gris clair deviennent transparents
    encre = image.convert("L").point(lambda v: 255 if v <= 110 else 0 if v >= 200 else int((200 - v) * 255 / 90))
    alpha = ImageChops.darker(image.getchannel("A"), encre)
    boite = alpha.getbbox()
    if not boite:
        return None  # zone vide
    sortie = Image.new("RGBA", image.size, (20, 20, 20, 255))
    sortie.putalpha(alpha)
    marge = 6
    sortie = sortie.crop((max(0, boite[0] - marge), max(0, boite[1] - marge),
                          min(image.width, boite[2] + marge), min(image.height, boite[3] + marge)))
    sortie.thumbnail((1200, 400))
    tampon = io.BytesIO()
    sortie.save(tampon, "PNG", optimize=True)
    return tampon.getvalue()
