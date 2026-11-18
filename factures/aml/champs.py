"""Lecture des champs envoyés par les formulaires (devis, factures, notes de frais, association)."""
import math
import re
import unicodedata
from datetime import date

from ..commun import RequeteInvalide


def texte(donnees, cle, maxi, libelle, obligatoire=False, lignes=1):
    """Texte nettoyé (espaces en trop retirés). `lignes` > 1 : retours à la ligne gardés."""
    valeur = donnees.get(cle)
    if valeur is None:
        valeur = ""
    if isinstance(valeur, bool) or not isinstance(valeur, (str, int, float)):
        raise RequeteInvalide(f"{libelle} : valeur invalide.")
    valeur = str(valeur)
    if lignes > 1:
        morceaux = [" ".join(l.split()) for l in valeur.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
        while morceaux and not morceaux[0]:
            morceaux.pop(0)
        while morceaux and not morceaux[-1]:
            morceaux.pop()
        if len(morceaux) > lignes:
            raise RequeteInvalide(f"{libelle} : {lignes} lignes au maximum.")
        valeur = "\n".join(morceaux)
    else:
        valeur = " ".join(valeur.split())
    if obligatoire and not valeur:
        raise RequeteInvalide(f"{libelle} : à remplir.")
    if len(valeur) > maxi:
        raise RequeteInvalide(f"{libelle} : {maxi} caractères au maximum.")
    return valeur


def date_iso(donnees, cle, libelle, obligatoire=True):
    """Date « AAAA-MM-JJ » (celle des champs date du navigateur), ou None si vide et facultative."""
    valeur = donnees.get(cle) or ""
    if not valeur:
        if obligatoire:
            raise RequeteInvalide(f"{libelle} : à remplir.")
        return None
    if not isinstance(valeur, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", valeur):
        raise RequeteInvalide(f"{libelle} : date invalide.")
    try:
        jour = date.fromisoformat(valeur)
    except ValueError as exc:
        raise RequeteInvalide(f"{libelle} : date invalide.") from exc
    if not 1900 <= jour.year <= 2100:
        raise RequeteInvalide(f"{libelle} : date invalide.")
    return jour.isoformat()


def nombre(valeur, libelle, mini, maxi):
    """Nombre saisi (« 8,50 » accepté) compris entre mini et maxi."""
    if isinstance(valeur, str):
        valeur = valeur.replace("\xa0", "").replace(" ", "").replace(",", ".")
    if isinstance(valeur, bool) or valeur in (None, ""):
        raise RequeteInvalide(f"{libelle} : à remplir.")
    try:
        valeur = float(valeur)
    except (TypeError, ValueError) as exc:
        raise RequeteInvalide(f"{libelle} : nombre invalide.") from exc
    if not math.isfinite(valeur) or not mini <= valeur <= maxi:
        raise RequeteInvalide(f"{libelle} : nombre invalide.")
    return valeur


def slug(texte_libre, separateur=""):
    """« EXEMPLE'ASSO » -> « EXEMPLEASSO » : lettres et chiffres sans accents, pour les noms de fichiers."""
    ascii_ = unicodedata.normalize("NFKD", texte_libre).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9]+", separateur, ascii_).strip(separateur)
