"""Devis et factures de l'association : lecture du formulaire, numéros, calcul des totaux.

Un numéro s'écrit « préfixe-année-rang » (AML-D-2026-001, AML-F-2026-001) ; le rang repart à 1
chaque année, séparément pour les devis et pour les factures. Les montants sont calculés ici
(jamais repris du navigateur) : total HT par ligne, TVA arrondie une fois par taux.
"""
import re
from decimal import ROUND_HALF_UP, Decimal

from ..commun import RequeteInvalide
from .champs import date_iso, nombre, slug, texte

TYPES = {"devis": "Devis", "facture": "Facture"}
STATUTS = {
    "devis": {"en_attente": "En attente", "accepte": "Accepté", "refuse": "Refusé"},
    "facture": {"a_payer": "À payer", "payee": "Payée"},
}
NATURES = ("Prestation de services", "Vente de marchandises", "Prestation de services et vente")
TAUX_TVA = (0.0, 5.5, 10.0, 20.0)  # None = TVA non applicable (art. 293 B du CGI)
LIGNES_MAX = 60
RE_NUMERO = re.compile(r"(?P<prefixe>[A-Z0-9]+(?:-[A-Z0-9]+)*)-(?P<annee>\d{4})-(?P<rang>\d{1,6})")
CENT = Decimal("0.01")


def _dec(valeur):
    return Decimal(str(valeur))


def _arrondi(valeur):
    return valeur.quantize(CENT, rounding=ROUND_HALF_UP)


def lire_piece(data):
    """Devis ou facture saisi dans le formulaire (sans le numéro, lu à part)."""
    if not isinstance(data, dict):
        raise RequeteInvalide("Données illisibles.")
    type_ = data.get("type")
    if type_ not in TYPES:
        raise RequeteInvalide("Type de document invalide.")
    statut = data.get("statut") or next(iter(STATUTS[type_]))
    if statut not in STATUTS[type_]:
        raise RequeteInvalide("Suivi invalide.")
    nature = data.get("nature") or NATURES[0]
    if nature not in NATURES:
        raise RequeteInvalide("Nature invalide.")
    piece = {
        "type": type_,
        "date": date_iso(data, "date", "Date"),
        "statut": statut,
        "nature": nature,
        "client_nom": texte(data, "client_nom", 200, "Nom du client", obligatoire=True, lignes=3),
        "client_adresse": texte(data, "client_adresse", 300, "Adresse du client", lignes=6),
        "client_telephone": texte(data, "client_telephone", 40, "Téléphone du client"),
        "client_email": texte(data, "client_email", 120, "E-mail du client"),
        "objet": texte(data, "objet", 200, "Objet"),
        "lieu": texte(data, "lieu", 300, "Lieu", lignes=4),
        "description": texte(data, "description", 600, "Description", lignes=6),
        "notes": texte(data, "notes", 800, "Note", lignes=8),
    }
    if type_ == "devis":
        piece["validite"] = date_iso(data, "validite", "Date de validité", obligatoire=False)
    else:
        piece["echeance"] = date_iso(data, "echeance", "Date d'échéance", obligatoire=False)
        piece["conditions"] = texte(data, "conditions", 400, "Conditions de paiement", lignes=4)

    lignes = data.get("lignes")
    if not isinstance(lignes, list) or not lignes:
        raise RequeteInvalide("Ajoutez au moins une ligne.")
    if len(lignes) > LIGNES_MAX:
        raise RequeteInvalide(f"{LIGNES_MAX} lignes au maximum.")
    piece["lignes"] = []
    for i, ligne in enumerate(lignes, 1):
        if not isinstance(ligne, dict):
            raise RequeteInvalide(f"Ligne {i} illisible.")
        tva = ligne.get("tva")
        if tva in (None, ""):
            tva = None
        else:
            tva = nombre(tva, f"Ligne {i} : TVA", 0, 100)
            if tva not in TAUX_TVA:
                raise RequeteInvalide(f"Ligne {i} : taux de TVA invalide.")
        piece["lignes"].append({
            "designation": texte(ligne, "designation", 300, f"Ligne {i} : désignation", obligatoire=True, lignes=3),
            "prix_ht": round(nombre(ligne.get("prix_ht"), f"Ligne {i} : prix HT", -1_000_000, 1_000_000), 4),
            "quantite": round(nombre(ligne.get("quantite"), f"Ligne {i} : quantité", 0, 1_000_000), 3),
            "tva": tva,
        })
    return piece


def lire_numero(valeur, prefixe):
    """« aml-d-2026-1 » -> (« AML-D-2026-001 », 2026, 1) ; le préfixe doit être celui du type."""
    numero = "".join(str(valeur or "").split()).upper()
    m = RE_NUMERO.fullmatch(numero)
    if not m or m["prefixe"] != prefixe:
        raise RequeteInvalide(f"Numéro attendu sous la forme {prefixe}-AAAA-001.")
    annee, rang = int(m["annee"]), int(m["rang"])
    if not 1900 <= annee <= 2100 or rang < 1:
        raise RequeteInvalide(f"Numéro attendu sous la forme {prefixe}-AAAA-001.")
    return numero_de(prefixe, annee, rang), annee, rang


def numero_de(prefixe, annee, rang):
    return f"{prefixe}-{annee}-{rang:03d}"


def calculer(piece):
    """Totaux du document : par ligne, par taux de TVA (TVA arrondie une fois par taux) et en tout."""
    lignes, bases = [], {}
    for ligne in piece["lignes"]:
        taux = ligne["tva"]
        coef = 1 + _dec(taux or 0) / 100
        total_ht = _arrondi(_dec(ligne["prix_ht"]) * _dec(ligne["quantite"]))
        lignes.append({**ligne, "prix_ttc": _arrondi(_dec(ligne["prix_ht"]) * coef), "total_ht": total_ht,
                       "total_ttc": _arrondi(total_ht * coef)})
        bases[taux] = bases.get(taux, Decimal(0)) + total_ht
    taux_liste = []
    for taux in sorted(bases, key=lambda t: (t is not None, t or 0)):  # « non applicable » en premier
        ht = bases[taux]
        tva = _arrondi(ht * _dec(taux or 0) / 100)
        taux_liste.append({"taux": taux, "ht": ht, "tva": tva, "ttc": ht + tva})
    total_ht = sum((t["ht"] for t in taux_liste), Decimal(0))
    total_tva = sum((t["tva"] for t in taux_liste), Decimal(0))
    return {"lignes": lignes, "taux": taux_liste, "total_ht": total_ht, "total_tva": total_tva,
            "total_ttc": total_ht + total_tva}


def nom_fichier(piece):
    """« Devis_AML-D-2026-001_EXEMPLEASSO.pdf » (dernière ligne du nom du client, sans « Association »)."""
    client = piece["client_nom"].split("\n")[-1]
    client = re.sub(r"^(association|asso)\s+", "", client, flags=re.IGNORECASE)
    return "_".join(filter(None, [TYPES[piece["type"]], piece["numero"], slug(client).upper()[:30]])) + ".pdf"
