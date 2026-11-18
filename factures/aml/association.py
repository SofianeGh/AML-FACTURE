"""Coordonnées de l'association, imprimées sur les devis, factures et notes de frais.

Réglage partagé entre les membres (table « reglages », clé « association ») ; seul un
administrateur peut le modifier (bouton « Infos de l'association »). Les vraies valeurs
(adresse, SIRET, contacts…) sont saisies dans l'application et gardées dans la base : le code
ne contient que des valeurs neutres.
"""
import re

from ..commun import RequeteInvalide, stockage
from .champs import nombre, texte

DEFAUT = {
    "sigle": "AML",
    "nom": "Association des Informaticiens Lyonnais",
    "adresse": "",
    "ville": "",
    "pays": "France",
    "siret": "",
    "mention_tva": "TVA non applicable, art. 293 B du CGI",
    "contacts": "",
    "iban": "",
    "bic": "",
    "ville_signature": "Lyon",
    "validite_jours": 30,
    "echeance_jours": 30,
    "conditions_facture": "Paiement par virement bancaire à réception de la facture.",
    "mention_retard": "En cas de retard de paiement : pénalités au taux de la BCE majoré de 10 points et indemnité "
                      "forfaitaire de 40 € pour frais de recouvrement (clients professionnels). "
                      "Pas d'escompte pour paiement anticipé.",
    "prefixe_devis": "AML-D",
    "prefixe_facture": "AML-F",
}

# clé -> (libellé, longueur maximale, nombre de lignes)
TEXTES = {
    "sigle": ("Sigle", 20, 1),
    "nom": ("Nom complet", 120, 1),
    "adresse": ("Adresse", 150, 1),
    "ville": ("Code postal et ville", 80, 1),
    "pays": ("Pays", 40, 1),
    "siret": ("SIRET", 30, 1),
    "mention_tva": ("Mention TVA", 150, 1),
    "contacts": ("Contacts", 400, 4),
    "iban": ("IBAN", 50, 1),
    "bic": ("BIC", 15, 1),
    "ville_signature": ("Ville de signature", 60, 1),
    "conditions_facture": ("Conditions de paiement", 400, 4),
    "mention_retard": ("Mention en cas de retard", 500, 4),
}
JOURS = {"validite_jours": "Validité d'un devis", "echeance_jours": "Échéance d'une facture"}
PREFIXES = {"prefixe_devis": "Préfixe des devis", "prefixe_facture": "Préfixe des factures"}
RE_PREFIXE = re.compile(r"[A-Z0-9]+(?:-[A-Z0-9]+)*")


def association():
    """Coordonnées enregistrées, complétées par les valeurs par défaut."""
    return {**DEFAUT, **(stockage().reglage("association") or {})}


def lire_association(data):
    if not isinstance(data, dict):
        raise RequeteInvalide("Données illisibles.")
    valeurs = {}
    for cle, (libelle, maxi, lignes) in TEXTES.items():
        valeurs[cle] = texte(data, cle, maxi, libelle, obligatoire=cle in ("sigle", "nom"), lignes=lignes)
    for cle, libelle in JOURS.items():
        valeurs[cle] = int(nombre(data.get(cle, DEFAUT[cle]), libelle, 0, 365))
    for cle, libelle in PREFIXES.items():
        prefixe = texte(data, cle, 20, libelle, obligatoire=True).upper()
        if not RE_PREFIXE.fullmatch(prefixe):
            raise RequeteInvalide(f"{libelle} : lettres, chiffres et tirets seulement (ex. AML-D).")
        valeurs[cle] = prefixe
    if valeurs["prefixe_devis"] == valeurs["prefixe_facture"]:
        raise RequeteInvalide("Les préfixes des devis et des factures doivent être différents.")
    return valeurs
