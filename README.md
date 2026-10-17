# Factures METRO

Application web de l'**AML** (Association des Informaticiens Lyonnais) pour l'équipe
**Local Stock** : après les courses, elle lit les factures METRO, calcule les prix de vente TTC
avec marge, classe chaque dépense par catégorie et archive le tout sur **Nextcloud**.

Elle est prévue pour être hébergée sur le site de l'AML, avec un compte par membre :
voir **[DEPLOIEMENT.md](DEPLOIEMENT.md)**.

## Fonctionnalités

- **Lecture des factures METRO (PDF)** : chaque ligne est extraite (prix unitaire HT, colisage,
  quantité, remises, code et taux de TVA). Un bandeau vert confirme que la somme des lignes lues
  correspond au récapitulatif TVA imprimé sur la facture ; en cas d'écart, il passe en rouge.
- **Prix TTC et marge en direct** : coût HT et TTC par pièce, prix de vente optimal, prix de vente
  modifiable, chiffre d'affaires et bénéfice, recalculés à chaque frappe.
- **Catégories de dépense** par ligne : Vente, Event, Local, Cadeau conducteur, Hors catégorie.
- **Conducteur** : chaque facture a une case « Conducteur », obligatoire pour l'envoyer ; son nom
  figure sur les PDF (bilan final, bilan des ventes, récapitulatifs, cadeau conducteur).
- **Archivage Nextcloud** : la facture est envoyée renommée à sa date (`JJ-MM-AAAA.pdf`), avec
  un **bilan final** (toutes les informations de la facture), un **bilan des ventes** (prix de
  vente, résultat de la course) et un PDF récapitulatif par catégorie. Chaque type de PDF peut aller dans son propre dossier, ou tout dans un dossier par facture.
- **Export CSV** de la liste de prix (ouvrable dans Excel).
- **Comptes** : chaque membre se connecte ; les administrateurs gèrent les comptes et la
  connexion Nextcloud. Marge, taxe TPE, arrondi et prix choisis sont **partagés** entre tous.
- Plusieurs factures à la fois (glisser-déposer), thème clair / sombre automatique.

## Mise en ligne

Docker, Python seul ou hébergement « Python App », reverse proxy HTTPS, sous-domaine ou
sous-dossier du site : tout est dans **[DEPLOIEMENT.md](DEPLOIEMENT.md)**.

## Lancement en local (Windows)

Prérequis : **Python 3.10 ou plus récent**.

Double-cliquer sur `start.bat`. Il installe ce qu'il faut, demande au premier lancement
l'identifiant et le mot de passe du premier administrateur, puis ouvre http://localhost:5000.

## Utilisation

1. Se connecter. La première fois, un administrateur clique sur ⚙ pour connecter Nextcloud
   (voir plus bas) ; chacun peut ensuite choisir les dossiers (bouton « Dossiers Nextcloud »).
2. Déposer une ou plusieurs factures METRO (PDF) dans la zone prévue.
3. Régler la **marge**, la **taxe TPE** et l'**arrondi** en haut de la page.
4. Pour chaque facture, indiquer le **conducteur** (obligatoire pour envoyer ; les noms déjà
   utilisés sont proposés), puis ajuster si besoin la **catégorie**, les **pièces par unité** et
   le **prix de vente** de chaque ligne.
5. Vérifier si besoin les bilans (**Aperçu du bilan final**, **Aperçu du bilan des ventes**), puis
   cliquer sur **Envoyer sur Nextcloud**
   (ou **Tout envoyer** s'il y a plusieurs factures).

### Réglages (en haut de la page)

| Réglage | Effet |
|---|---|
| **Marge** | en % du coût TTC, ou en € ajoutés par pièce |
| **Taxe TPE** | montant fixe en € par pièce (frais du terminal de paiement), ajouté après la marge |
| **Arrondi** | arrondit le prix de vente optimal au supérieur (0,05 €, 0,10 €, 0,50 €, 1 €) |

### Colonnes du tableau

| Colonne | Contenu |
|---|---|
| **Catégorie** | Vente (par défaut), Event, Local, Cadeau conducteur, Hors catégorie |
| **Qté** | unités facturées (colisage × quantité) |
| **Pièces / u.** | pour les packs revendus à l'unité (ex. « PACK DE10 » → 10) |
| **Coût HT / TTC par pièce** | remises METRO déduites |
| **Prix de vente optimal** | coût TTC + marge + taxe TPE, avec l'arrondi choisi |
| **Prix de vente** | le prix réellement pratiqué ; pré-rempli avec le prix optimal, modifiable |
| **Total TTC** | coût TTC de la ligne |

Le **prix de vente** suit le prix optimal tant qu'il n'est pas modifié. Un prix saisi est
encadré en jaune ; ↺ (ou vider le champ) revient au prix optimal. Il passe en rouge s'il est
inférieur au coût TTC + taxe TPE (vente à perte).

### Calculs

```
Prix optimal       = coût TTC par pièce × (1 + marge %)  + taxe TPE   (puis arrondi)
                     ou coût TTC par pièce + marge €      + taxe TPE
Chiffre d'affaires = Σ prix de vente × pièces              (lignes Vente)
Bénéfice ventes    = chiffre d'affaires − coût TTC des lignes Vente − taxe TPE
Bénéfice final     = bénéfice ventes − coût TTC des cadeaux conducteur
```

Seules les lignes **Vente** ont un prix de vente. Les autres catégories apparaissent sous le
tableau avec leur total et un lien « aperçu PDF ». Les **cadeaux conducteur** sont une perte
sur la course : ils sont retirés du bénéfice (« Bénéfice après cadeau conducteur »).

### Ce qui est mémorisé (sur le serveur, commun à tous les membres)

- marge, taxe TPE et arrondi ;
- par article : pièces par unité, prix de vente saisi, catégorie *Local* (produits utilisés au
  local à chaque fois). Ces choix sont repris sur les autres factures et les suivantes.

Les autres catégories (Event, Cadeau conducteur, Hors catégorie) ne valent que pour la ligne choisie.

### Comptes

- **Membre** : traite les factures et les envoie sur Nextcloud.
- **Administrateur** : en plus, gère les comptes (« Comptes » en haut de la page) et la
  connexion Nextcloud (⚙).
- Chacun peut changer son mot de passe (« Mot de passe » en haut de la page).

## Nextcloud

Cliquer sur ⚙ et saisir l'adresse du serveur, l'identifiant et un **mot de passe d'application**
(Nextcloud → Paramètres personnels → Sécurité → « Créer un nouveau mot de passe d'application » ;
utiliser l'identifiant affiché à ce moment-là). Pour l'adresse, on peut aussi coller celle d'un
dossier ouvert dans Nextcloud (`…/apps/files/…?dir=/2025-2026`) : ce dossier devient le dossier
principal. Ces informations sont enregistrées dans la base de l'application (`data/`, exclu de
git) ; le mot de passe n'est jamais renvoyé au navigateur. Seul un administrateur peut les modifier.

### Fichiers envoyés

```
18-09-2026.pdf                       ← la facture METRO d'origine
18-09-2026 - BILAN FINAL.pdf         ← bilan final (infos de la facture)
18-09-2026 - BILAN VENTES.pdf        ← bilan des ventes
18-09-2026 - VENTE.pdf               ← un récapitulatif par catégorie utilisée
18-09-2026 - EVENT.pdf
18-09-2026 - LOCAL.pdf
18-09-2026 - CADEAU CONDUCTEUR.pdf
18-09-2026 - HORS CATEGORIE.pdf
```

- **Bilan final** : toutes les informations de la facture, sans prix de vente — date, n° de
  facture, ticket, conducteur, nombre de lignes et d'unités, remises METRO, contrôle des lignes ;
  montants du récapitulatif TVA de METRO et total à payer ; répartition par catégorie ; détail de
  chaque ligne (article, réf., catégorie, quantité, PU HT, total HT, TVA, total TTC).
- **Bilan des ventes** : conducteur ; pour chaque article en Vente, pièces, coût TTC par
  pièce, prix optimal, prix de vente choisi, marge par pièce (en rouge si vendu à perte) et
  chiffre d'affaires prévu ; puis le résultat de la course (total par catégorie, chiffre
  d'affaires, taxe TPE, bénéfice, cadeau conducteur, bénéfice final) et les réglages utilisés.
- **Conducteur** : obligatoire pour envoyer ; il figure sur le bilan, en en-tête de chaque
  récapitulatif et dans le titre du récapitulatif « Cadeau conducteur ».
- **Dossiers** : bouton « Dossiers Nextcloud » → un dossier principal et deux rangements au choix :
  - **un dossier par facture**, créé dans le dossier principal et nommé `AAAA_MM_DD - total TTC`
    (ex. `2026_10_03 - 959,74 €`), qui contient la facture (duplicata), le bilan et tous les
    récapitulatifs ;
  - **un dossier par type de PDF** (facture, bilan final, bilan des ventes, récapitulatif de chaque catégorie) ; un type
    sans dossier choisi va dans le dossier principal.

  Les dossiers manquants sont créés à l'envoi.
- **Notes** : « ajouter une note » à côté de chaque « aperçu PDF » (récapitulatifs) et de
  « Aperçu du bilan final » et « Aperçu du bilan des ventes ». La note est imprimée dans un encadré en haut du PDF correspondant ;
  elle vaut pour la facture en cours et n'est pas conservée après l'avoir retirée.
- Un nom de fichier ne peut pas contenir « / » : la date est écrite `JJ-MM-AAAA`.
- Facture déjà présente (même nom, même taille) : elle n'est pas renvoyée.
  Autre facture le même jour : `30-09-2026 (2).pdf`, et les autres PDF suivent ce nom.
- Renvoyer une facture remplace son bilan et ses récapitulatifs ; celui d'une catégorie qui n'a
  plus de ligne est supprimé (il part dans la corbeille Nextcloud).
- Chaque récapitulatif liste les lignes de la catégorie (HT, TVA, TTC) et le total par taux de
  TVA. La TVA étant arrondie par catégorie, la somme des récapitulatifs peut différer d'un
  centime du total de la facture.

## Structure du projet

| Fichier | Rôle |
|---|---|
| `app.py` | serveur web Flask et API (connexion, sécurité, factures, Nextcloud) |
| `stockage.py` | base SQLite : comptes, réglages Nextcloud, préférences partagées |
| `manage.py` | gestion des comptes en ligne de commande |
| `metro_parser.py` | lecture des factures METRO (`python metro_parser.py facture.pdf` pour tester) |
| `nextcloud.py` | client WebDAV Nextcloud |
| `recap_pdf.py` | PDF : récapitulatif par catégorie, bilan final, bilan des ventes |
| `static/` | interface (HTML, CSS, JavaScript), page de connexion |
| `wsgi.py`, `passenger_wsgi.py` | points d'entrée pour les serveurs WSGI et les hébergeurs « Python App » |
| `Dockerfile`, `docker-compose.yml`, `.env.example` | déploiement Docker |
| `start.bat` | installation et lancement sous Windows |
| `requirements.txt` | dépendances Python (Flask, pdfplumber, reportlab, requests, waitress) |
| `DEPLOIEMENT.md` | guide de mise en ligne |

## Auteur

Fait par **[Sofiane Abichou](https://github.com/SofianeGh)** — Local Stock, mandat 2025/2026.

## Licence

Distribué sous licence MIT : voir [LICENSE](LICENSE).
