"""Gestion des comptes en ligne de commande.

    python manage.py ajouter-utilisateur NOM [--admin]
    python manage.py mot-de-passe NOM
    python manage.py admin NOM oui|non
    python manage.py supprimer-utilisateur NOM
    python manage.py lister-utilisateurs
    python manage.py initialiser          (crée le premier administrateur si aucun compte n'existe)

Le mot de passe est demandé au clavier (ou lu dans la variable MOT_DE_PASSE).
Les données sont dans DATA_DIR (./data par défaut), comme pour l'application.
"""
import argparse
import getpass
import os
import sys
from pathlib import Path

from stockage import ErreurCompte, Stockage

ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("DATA_DIR", ROOT / "data")).resolve()


def demander_mot_de_passe():
    if os.environ.get("MOT_DE_PASSE"):
        return os.environ["MOT_DE_PASSE"]
    mdp = getpass.getpass("Mot de passe (8 caractères minimum) : ")
    if mdp != getpass.getpass("Confirmez le mot de passe : "):
        raise ErreurCompte("Les deux mots de passe ne correspondent pas.")
    return mdp


def main(argv=None):
    parser = argparse.ArgumentParser(description="Comptes de l'application Factures METRO")
    sous = parser.add_subparsers(dest="commande", required=True)
    p = sous.add_parser("ajouter-utilisateur", help="créer un compte")
    p.add_argument("nom")
    p.add_argument("--admin", action="store_true", help="peut gérer les comptes et la connexion Nextcloud")
    sous.add_parser("mot-de-passe", help="changer un mot de passe").add_argument("nom")
    p = sous.add_parser("admin", help="donner ou retirer le rôle administrateur")
    p.add_argument("nom")
    p.add_argument("valeur", choices=["oui", "non"])
    sous.add_parser("supprimer-utilisateur", help="supprimer un compte").add_argument("nom")
    sous.add_parser("lister-utilisateurs", help="lister les comptes")
    sous.add_parser("initialiser", help="créer le premier administrateur si besoin")
    args = parser.parse_args(argv)

    stockage = Stockage(DATA_DIR / "aml-factures.db")
    try:
        if args.commande == "ajouter-utilisateur":
            nom = stockage.ajouter_utilisateur(args.nom, demander_mot_de_passe(), args.admin)
            print(f"Compte « {nom} » créé{' (administrateur)' if args.admin else ''}.")
        elif args.commande == "mot-de-passe":
            stockage.changer_mot_de_passe(args.nom, demander_mot_de_passe())
            print("Mot de passe modifié.")
        elif args.commande == "admin":
            stockage.definir_admin(args.nom, args.valeur == "oui")
            print("Rôle mis à jour.")
        elif args.commande == "supprimer-utilisateur":
            stockage.supprimer_utilisateur(args.nom)
            print("Compte supprimé.")
        elif args.commande == "lister-utilisateurs":
            comptes = stockage.utilisateurs()
            if not comptes:
                print("Aucun compte.")
            for c in comptes:
                print(f"{c['nom']:<24} {'admin' if c['admin'] else 'membre':<7} créé le {c['cree_le']}")
        elif args.commande == "initialiser":
            if stockage.nb_utilisateurs():
                return 0
            print("Aucun compte n'existe encore : création du premier administrateur.")
            nom = input("Nom du compte (ex. sofiane) : ")
            nom = stockage.ajouter_utilisateur(nom, demander_mot_de_passe(), admin=True)
            print(f"Compte administrateur « {nom} » créé.")
    except ErreurCompte as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
