# Factures METRO → prix TTC + marge, archivage Nextcloud

Application web locale qui :

1. lit une facture METRO (PDF) et en extrait chaque ligne : prix unitaire HT, colisage, quantité, remises, code et taux de TVA ;
2. calcule pour chaque article le **coût TTC par pièce** et le **prix de vente** avec la marge saisie (recalcul en direct) ;
3. envoie la facture PDF sur **Nextcloud**, dans le dossier choisi, renommée à la date de la facture : `JJ-MM-AAAA.pdf`.

## Lancer l'application

Double-cliquer sur `start.bat` (Python 3.10 ou plus récent requis).
Au premier lancement, l'environnement Python est créé et les dépendances sont installées,
puis la page http://localhost:5000 s'ouvre.

En ligne de commande :

```bash
.venv\Scripts\python.exe app.py
```

Variables optionnelles : `PORT` (5000 par défaut) et `HOST` (`127.0.0.1` par défaut ;
mettre `0.0.0.0` pour y accéder depuis un autre poste du réseau local).

## Utilisation

- **Marge** : en % (prix de vente = coût TTC × (1 + marge)) ou en € ajoutés par pièce.
- **Arrondi** : arrondit le prix de vente au supérieur (0,05 €, 0,10 €, 0,50 €, 1 €).
- **Prix de vente optimal** : coût TTC + marge + taxe TPE, avec l'arrondi choisi.
- **Prix de vente** : le prix auquel vous vendez. Pré-rempli avec le prix optimal (et le suit tant
  qu'il n'est pas modifié). Un prix saisi est mémorisé par article et repris sur les autres
  factures ; ↺ (ou vider le champ) revient au prix optimal. En rouge si le prix est sous le coût
  TTC + taxe TPE. Le chiffre d'affaires et le bénéfice sont calculés avec ces prix.
- **Taxe TPE** : montant fixe en € ajouté au prix de vente de chaque pièce (tous les articles),
  après la marge (la marge ne s'applique pas dessus) et avant l'arrondi.
  Le bénéfice estimé est calculé hors taxe TPE.
- **Catégorie** (par ligne) : *Vente* (par défaut), *Event*, *Local*, *Cadeau conducteur*,
  *Hors catégorie*. *Local* est mémorisé par article (produits utilisés au local à chaque fois) ;
  les autres ne valent que pour la ligne choisie. Seules les lignes *Vente* ont un prix de vente.
  Sous le tableau, le total de chaque catégorie, avec un lien « aperçu PDF ».
  Le bénéfice affiché est celui des ventes : chiffre d'affaires − coût des lignes Vente − taxe TPE.
  S'il y a des cadeaux conducteur, leur coût est ensuite retiré : « Bénéfice après cadeau conducteur ».
- **Pièces / u.** : pour les packs revendus à l'unité (ex. « PACK DE10 » → 10). La valeur
  est mémorisée par article dans le navigateur.
- Le bandeau vert confirme que la somme des lignes lues correspond au récapitulatif TVA
  imprimé sur la facture ; en cas d'écart, il passe en rouge.
- **Exporter CSV** : la liste de prix (ouvrable dans Excel).

## Nextcloud

Cliquer sur ⚙ et saisir l'adresse du serveur, l'identifiant et un **mot de passe d'application**
(Nextcloud → Paramètres personnels → Sécurité → « Créer un nouveau mot de passe d'application »).
Ces informations sont enregistrées dans `config.json`, à côté de l'application ;
le mot de passe n'est jamais renvoyé au navigateur.

Le nom de fichier ne peut pas contenir de « / » : la date est donc écrite `JJ-MM-AAAA.pdf`.

À chaque envoi, un PDF récapitulatif est aussi créé pour chaque catégorie utilisée, dans le même
dossier : `18-09-2026 - VENTE.pdf`, `18-09-2026 - EVENT.pdf`, `18-09-2026 - LOCAL.pdf`,
`18-09-2026 - CADEAU CONDUCTEUR.pdf`, `18-09-2026 - HORS CATEGORIE.pdf`. Chacun liste les lignes
de la catégorie (HT, TVA, TTC) avec le récapitulatif par taux de TVA.
Renvoyer une facture remplace ses PDF de catégorie ; ceux d'une catégorie qui n'a plus de ligne
sont supprimés (corbeille Nextcloud). La TVA étant arrondie par catégorie, la somme des
récapitulatifs peut différer d'un centime du total de la facture.
Si un fichier de même nom existe déjà :
- même taille → la facture est considérée comme déjà envoyée, rien n'est écrasé ;
- sinon → un suffixe est ajouté : `30-09-2026 (2).pdf`.

## Fichiers

| Fichier | Rôle |
|---|---|
| `app.py` | serveur web Flask et API |
| `metro_parser.py` | lecture des factures METRO (`python metro_parser.py facture.pdf` pour tester) |
| `nextcloud.py` | client WebDAV Nextcloud |
| `recap_pdf.py` | PDF récapitulatif par catégorie |
| `static/` | interface (HTML, CSS, JavaScript) |
