"""Lecture d'un relevé bancaire CSV (séparateur « ; » ou « , », UTF-8 ou Latin-1).

Tolérant, comme dans AML Trésorerie : la ligne d'en-tête est cherchée toute seule, puis les colonnes
Date, Libellé (ou Motif), Nature et Montant (ou Débit + Crédit). Les lignes de suite sans date
(« POUR: », « REF: », « MOTIF: »…) complètent la transaction précédente : le texte après « MOTIF: »
devient son libellé.
"""
import csv
import io
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation

FORMATS_DATE = ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y")
RE_MOTIF = re.compile(r"^motif\s*:\s*(.*)$", re.IGNORECASE)


class ReleveIllisible(ValueError):
    """Le fichier n'est pas un relevé lisible : le message est montré à l'utilisateur."""


@dataclass
class Ligne:
    date: str        # AAAA-MM-JJ
    libelle: str
    nature: str
    montant: Decimal  # négatif = débit (charge), positif = crédit (produit)


def normaliser(texte):
    """« Débit » -> « debit » : sans accents, en minuscules."""
    texte = unicodedata.normalize("NFD", texte or "")
    return "".join(c for c in texte if not unicodedata.combining(c)).lower().strip()


def _decoder(data):
    try:
        texte = data.decode("utf-8")
    except UnicodeDecodeError:
        texte = data.decode("latin-1")  # beaucoup de banques exportent en Latin-1
    return texte.removeprefix("﻿")


def _colonne(noms, cle, prefere=None):
    """Première colonne dont le nom contient `cle` (celle qui contient aussi `prefere` d'abord)."""
    premiere = None
    for nom in noms:
        n = normaliser(nom)
        if cle in n:
            if prefere and prefere in n:
                return nom
            premiere = premiere or nom
    return premiere


def _colonne_parmi(noms, *cles):
    for cle in cles:
        trouvee = _colonne(noms, cle)
        if trouvee:
            return trouvee
    return None


def montant(texte):
    """« -1 234,56 € » -> Decimal("-1234.56") (« 1.234,56 » accepté)."""
    t = texte.replace("\xa0", "").replace(" ", "").replace(" ", "").replace("€", "")
    if "," in t and "." in t:
        t = t.replace(".", "")  # point des milliers
    try:
        return Decimal(t.replace(",", "."))
    except InvalidOperation as exc:
        raise ReleveIllisible(f"Montant illisible : {texte}") from exc


def date(texte):
    for format_ in FORMATS_DATE:
        try:
            return datetime.strptime(texte.strip(), format_).date().isoformat()
        except ValueError:
            pass
    raise ReleveIllisible(f"Date non reconnue : {texte}")


def motif(texte):
    """Dans une cellule sur plusieurs lignes, garde ce qui suit « MOTIF: » ; sinon la première ligne."""
    premiere = None
    for ligne in texte.splitlines():
        t = ligne.strip()
        if not t:
            continue
        premiere = premiere or t
        m = RE_MOTIF.match(t)
        if m and m[1].strip():
            return m[1].strip()
    return premiere or ""


def lire_releve(data):
    """Contenu du fichier CSV -> liste de Ligne, dans l'ordre du relevé."""
    lignes = _decoder(data).splitlines()
    debut = next((i for i, l in enumerate(lignes)
                  if "date" in normaliser(l) and any(m in normaliser(l) for m in ("montant", "debit", "credit"))),
                 None)
    if debut is None:
        raise ReleveIllisible("En-tête introuvable : le CSV doit avoir une colonne Date et une colonne Montant "
                              "(ou Débit / Crédit).")
    entete = lignes[debut]
    separateur = ";" if entete.count(";") >= entete.count(",") else ","
    lecteur = csv.reader(io.StringIO("\n".join(lignes[debut:])), delimiter=separateur)
    noms = [n.strip() for n in next(lecteur)]
    c_date = _colonne(noms, "date", "operation")
    c_libelle = _colonne_parmi(noms, "motif", "libelle", "label", "detail", "description")
    c_montant, c_nature = _colonne(noms, "montant"), _colonne(noms, "nature")
    c_debit, c_credit = _colonne(noms, "debit"), _colonne(noms, "credit")
    if c_date is None or c_libelle is None:
        raise ReleveIllisible("Colonnes Date et Libellé introuvables.")
    index = {nom: i for i, nom in reversed(list(enumerate(noms)))}  # premier nom en cas de doublon

    resultat = []
    for cellules in lecteur:
        if not any(c.strip() for c in cellules):
            continue
        valeur = lambda nom: cellules[index[nom]].strip() if nom and index[nom] < len(cellules) else ""  # noqa: E731
        if not valeur(c_date):
            # ligne de suite (POUR:, REF:, MOTIF:…) : le motif complète la transaction précédente
            for cellule in cellules:
                m = RE_MOTIF.match(cellule.strip())
                if resultat and m and m[1].strip():
                    resultat[-1].libelle = m[1].strip()
            continue
        somme = None
        if valeur(c_montant):
            somme = montant(valeur(c_montant))
        else:
            if valeur(c_debit):
                somme = -abs(montant(valeur(c_debit)))
            if valeur(c_credit):
                somme = abs(montant(valeur(c_credit)))
        if somme is None:
            continue
        resultat.append(Ligne(date(valeur(c_date)), motif(valeur(c_libelle)), valeur(c_nature), somme))
    return resultat
