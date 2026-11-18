# AML Factures

Application web de gestion de l'**AML** (Association des Informaticiens Lyonnais), en quatre onglets :

| Onglet | À quoi il sert |
|---|---|
| **Factures METRO** | lire les factures METRO après les courses de Local Stock, calculer les prix de vente avec marge, classer les dépenses et tout archiver sur Nextcloud |
| **Notes de frais** | faire l'attestation sur l'honneur d'un membre qui a payé pour l'AML, signée, avec les justificatifs en annexe |
| **Devis et factures** | faire les devis et les factures de l'association, numérotés, au modèle de l'AML |
| **Trésorerie** | importer les relevés bancaires, classer chaque transaction par mandat et sortir le compte de résultat |

Les quatre onglets partagent la même base (SQLite) : une transaction de la trésorerie peut recevoir
comme justificatif une note de frais ou une facture faite dans l'application.

Elle est prévue pour être hébergée sur le site de l'AML, avec un compte par membre :
voir **[docs/DEPLOIEMENT.md](docs/DEPLOIEMENT.md)**. Thème clair / sombre automatique.

**Sommaire** : [Factures METRO](#factures-metro) · [Notes de frais](#notes-de-frais) ·
[Devis et factures](#devis-et-factures) · [Trésorerie](#trésorerie) ·
[Infos de l'association](#infos-de-lassociation) · [Comptes](#comptes) · [Nextcloud](#nextcloud) ·
[Mise en ligne](#mise-en-ligne) · [Structure du projet](#structure-du-projet) · [Tests](#tests) ·
[Auteurs](#auteurs)

## Factures METRO

### Fonctionnalités

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
  vente, résultat de la course) et un PDF récapitulatif par catégorie. Chaque type de PDF peut
  aller dans son propre dossier, ou tout dans un dossier par facture.
- **Export CSV** de la liste de prix (ouvrable dans Excel).
- Plusieurs factures à la fois (glisser-déposer). Marge, taxe TPE, arrondi et prix choisis sont
  **partagés** entre tous les membres.

### Utilisation

1. Déposer une ou plusieurs factures METRO (PDF) dans la zone prévue.
2. Régler la **marge**, la **taxe TPE** et l'**arrondi** en haut de la page.
3. Pour chaque facture, indiquer le **conducteur** (obligatoire pour envoyer ; les noms déjà
   utilisés sont proposés), puis ajuster si besoin la **catégorie**, les **pièces par unité** et
   le **prix de vente** de chaque ligne.
4. Vérifier si besoin les bilans (**Aperçu du bilan final**, **Aperçu du bilan des ventes**), puis
   cliquer sur **Envoyer sur Nextcloud** (ou **Tout envoyer** s'il y a plusieurs factures).

| Réglage | Effet |
|---|---|
| **Marge** | en % du coût TTC, ou en € ajoutés par pièce |
| **Taxe TPE** | montant fixe en € par pièce (frais du terminal de paiement), ajouté après la marge |
| **Arrondi** | arrondit le prix de vente optimal au supérieur (0,05 €, 0,10 €, 0,50 €, 1 €) |

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

Ce qui est mémorisé (sur le serveur, commun à tous) : marge, taxe TPE et arrondi ; par article,
les pièces par unité, le prix de vente saisi et la catégorie *Local* (produits utilisés au local à
chaque fois). Les autres catégories ne valent que pour la ligne choisie.

### Fichiers envoyés sur Nextcloud

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
- **Dossiers** : bouton « Dossiers Nextcloud » → un dossier principal et deux rangements au choix :
  **un dossier par facture**, nommé `AAAA_MM_DD - total TTC` (ex. `2026_10_03 - 959,74 €`), qui
  contient la facture (duplicata), le bilan et tous les récapitulatifs ; ou **un dossier par type
  de PDF** (un type sans dossier choisi va dans le dossier principal). Les dossiers manquants sont
  créés à l'envoi.
- **Notes** : « ajouter une note » à côté de chaque aperçu PDF. La note est imprimée dans un
  encadré en haut du PDF correspondant ; elle vaut pour la facture en cours.
- Facture déjà présente (même nom, même taille) : elle n'est pas renvoyée. Autre facture le même
  jour : `30-09-2026 (2).pdf`, et les autres PDF suivent ce nom. Renvoyer une facture remplace son
  bilan et ses récapitulatifs ; celui d'une catégorie qui n'a plus de ligne est supprimé.
- La TVA étant arrondie par catégorie, la somme des récapitulatifs peut différer d'un centime du
  total de la facture.

## Notes de frais

Attestation sur l'honneur au modèle de l'AML (logo, texte de l'attestation, cadre de signature),
puis **une page d'annexe par justificatif**.

1. **Nouvelle note de frais** : la personne qui a payé (civilité, nom, naissance, qualité,
   association, adresse).
2. Les **dépenses** : ce qui a été acheté et à quelle occasion (un aperçu montre la phrase qui
   sera imprimée), puis une ligne par fournisseur avec la date, le n° de reçu et le montant TTC.
3. Les **justificatifs** de chaque dépense : photo du ticket (JPEG, PNG) ou PDF de la facture, par
   le bouton « Ajouter » ou en les glissant sur la ligne. Les photos sont réduites et redressées.
4. La **signature** : à la souris ou au doigt, ou image importée (le papier blanc d'une signature
   photographiée devient transparent). Sans signature, le cadre reste vide pour signer à la main.
5. **Enregistrer et voir le PDF**.

Suivi « À rembourser / Remboursée » dans la liste. « Dupliquer » reprend la personne et sa
signature pour une nouvelle note.

## Devis et factures

- Numérotés `AML-D-AAAA-001` (devis) et `AML-F-AAAA-001` (factures) : le rang repart à 1 chaque
  année ; le numéro proposé reste modifiable.
- Client (les clients déjà utilisés sont proposés), objet, lieu, description, lignes avec
  **TVA « non applicable »** par défaut (ou 0 / 5,5 / 10 / 20 % par ligne) ; totaux en direct.
- **Devis** : date de validité et mention « Lu et approuvé, bon pour accord ».
  **Factures** : échéance, conditions de paiement, IBAN et mention en cas de retard.
- **Transformer en facture** : la facture reprend le devis, qui passe à « Accepté ».
- Suivi dans la liste (en attente / accepté / refusé ; à payer / payée). Seule la dernière facture
  de l'année peut être supprimée, pour que les numéros se suivent sans trou.
- PDF sur plusieurs pages si besoin, au modèle du devis de l'AML.

## Trésorerie

Onglet repris de l'application [AML Trésorerie](https://github.com/AILANE-AMAR/AML-TRESO)
(Java + PostgreSQL), refait en Python dans la même base. On choisit d'abord le **mandat**
(ex. 2026 - 2027), puis :

### Transactions

- **Importer un relevé CSV** du mois. Réimporter un fichier ne crée pas de doublon (deux lignes
  identiques le même jour restent deux transactions). Un avertissement signale les lignes en
  dehors des dates du mandat.
- **Modifier** une transaction : motif, **dossier** (catégorie), **étiquette** (classeur),
  commentaire et justificatifs.
- **Classer plusieurs transactions d'un coup** : cocher les lignes (Maj + clic coche toutes les
  lignes entre deux cases, la case du haut coche tout), puis choisir le dossier et l'étiquette dans
  la barre qui apparaît et cliquer sur **Classer**. « À classer » retire le classement.
- **Répartir une transaction sur plusieurs classeurs** (« Répartir sur plusieurs classeurs » dans
  la fenêtre Modifier) : chaque part a son classeur, son montant et une note ; la somme des parts
  doit faire le montant de la transaction (le reste à répartir est affiché, et « Mettre le reste
  sur la dernière part » le complète). Exemples :
  - versement **HelloAsso** qui regroupe plusieurs billetteries : une part par événement ;
  - versement du **TPE** qui mélange un événement du midi et les ventes habituelles du local ;
  - **frais retenus** sur un versement : part négative (ex. 100 € de ventes − 3 € de frais = 97 €).

  Une transaction répartie n'est pas modifiée par le classement groupé.

Format du fichier CSV : séparateur `;` ou `,`, encodage UTF-8 ou Latin-1 ; une ligne d'en-tête
avec une colonne **Date** (`jj/mm/aaaa`, `jj/mm/aa` ou `aaaa-mm-jj`) et une colonne **Montant**, ou
**Débit** + **Crédit** ; colonnes **Libellé** (ou Motif) et **Nature**. Le texte après `MOTIF:` des
lignes de suite devient le libellé.

### Justificatifs

- **Fichier** (photo, PDF…) gardé dans la base ; si Nextcloud est configuré, il est aussi copié
  dans `<mandat>/[3] Trésorerie/<catégorie>/<classeur>/` (comme dans AML Trésorerie).
- **Note de frais ou facture de l'application** (« Joindre ») : celles du **même montant** sont
  proposées en premier. La note jointe à un débit passe à « Remboursée », la facture jointe à un
  crédit passe à « Payée » ; les listes de ces onglets affichent alors « En trésorerie : date ».
  Le PDF joint est refait à chaque ouverture, donc toujours à jour.

### Compte de résultat

Par mandat : catégorie › classeur avec **charges**, **produits** et **balance**, sous-totaux, bloc
« hors compte de résultat », lignes non classées et **contrôle** avec le solde du relevé. Une
transaction répartie compte pour chacune de ses parts, dans le classeur de la part. Un clic sur un
classeur montre ses transactions (avec « part de … » pour une transaction répartie).
Export **PDF**, **Excel** (avec couleurs) et **CSV** (s'ouvre dans Excel en français).

### Mandats et classeurs

Nouveau mandat (avec reprise des classeurs du mandat choisi), ajout d'un classeur, suppression d'un
classeur vide. Les catégories sont communes à tous les mandats.

Reprise des mandats, catégories et classeurs d'AML Trésorerie (export JSON de sa base) :
`python manage.py reprendre-tresorerie fichier.json` (refusée s'il y a déjà des transactions).

## Infos de l'association

Bouton « Infos de l'association » (onglets Notes de frais et Devis et factures) : sigle, nom,
adresse, SIRET, mention TVA, contacts du pied de page, IBAN, ville de signature, préfixes des
numéros, validité des devis, échéance et conditions des factures, mention en cas de retard.
Ces valeurs sont **enregistrées dans la base** (jamais dans le code) et imprimées sur les PDF.
Seul un administrateur peut les modifier.

## Comptes

- **Membre** : utilise tous les onglets.
- **Administrateur** : en plus, gère les comptes (« Comptes » en haut de la page), la connexion
  Nextcloud (⚙) et les infos de l'association.
- Chacun peut changer son mot de passe (« Mot de passe » en haut de la page).

Pour un serveur privé (réseau local, VPN), `CONNEXION=0` ouvre l'application sans écran de
connexion (tout le monde a alors les droits d'administrateur).

En ligne de commande (`DATA_DIR` = dossier des données, `./data` par défaut) :

```bash
python manage.py ajouter-utilisateur NOM [--admin]
python manage.py mot-de-passe NOM
python manage.py admin NOM oui|non
python manage.py supprimer-utilisateur NOM
python manage.py lister-utilisateurs
python manage.py initialiser                      # premier administrateur si aucun compte
python manage.py reprendre-tresorerie FICHIER.json # référentiel d'AML Trésorerie
```

## Nextcloud

Cliquer sur ⚙ (onglet Factures METRO) et saisir l'adresse du serveur, l'identifiant et un **mot
de passe d'application** (Nextcloud → Paramètres personnels → Sécurité → « Créer un nouveau mot de
passe d'application » ; utiliser l'identifiant affiché à ce moment-là). Pour l'adresse, on peut
aussi coller celle d'un dossier ouvert dans Nextcloud (`…/apps/files/…?dir=/2025-2026`) : ce
dossier devient le dossier principal. Ces informations sont enregistrées dans la base (`data/`,
exclu de git) ; le mot de passe n'est jamais renvoyé au navigateur.

Nextcloud sert aux factures METRO et à la copie des justificatifs de la trésorerie. Les notes de
frais, devis et factures se téléchargent en PDF.

## Mise en ligne

Docker, Python seul ou hébergement « Python App », reverse proxy HTTPS, sous-domaine ou
sous-dossier du site : tout est dans **[docs/DEPLOIEMENT.md](docs/DEPLOIEMENT.md)**.

### Lancement en local (Windows)

Prérequis : **Python 3.10 ou plus récent**. Double-cliquer sur `start.bat` : il installe ce qu'il
faut, demande au premier lancement l'identifiant et le mot de passe du premier administrateur,
puis ouvre http://localhost:5000.

## Structure du projet

```
AML-FACTURE/
├── factures/                  ← le code de l'application (paquet Python)
│   ├── __init__.py            ← crée l'application Flask (create_app)
│   ├── __main__.py            ← lance le serveur : python -m factures
│   ├── config.py              ← variables d'environnement, dossier de données, clé secrète
│   ├── securite.py            ← connexion, anti-CSRF, en-têtes, blocage des essais
│   ├── commun.py              ← erreurs, journal, réglages Nextcloud, accès à la base
│   ├── stockage.py            ← base SQLite : comptes, réglages, préférences, NDF, devis et factures
│   ├── aml/                   ← lecture des formulaires : association, devis/factures, notes de frais
│   ├── treso/                 ← trésorerie : releve (CSV), stockage (tables, compte de résultat), exports
│   ├── metro/lecture.py       ← lecture des factures METRO
│   ├── nextcloud/client.py    ← client WebDAV Nextcloud
│   ├── pdf/                   ← PDF METRO (recap, bilan_final, bilan_ventes), devis, ndf, aml_commun
│   ├── routes/                ← comptes, reglages, factures (METRO), ndf, devis, treso
│   ├── templates/             ← index.html (les quatre onglets), connexion.html
│   └── static/
│       ├── css/style.css, fonts/, logo-aml.png
│       └── js/                ← main, onglets, outils, api ; METRO : calculs, facture, nextcloud,
│                                 dossiers ; comptes, connexion ; association, ndf, signature, devis, treso
├── tests/                     ← tests pytest (factures METRO d'exemple dans tests/factures_exemple/, hors git)
├── docs/DEPLOIEMENT.md        ← guide de mise en ligne
├── manage.py                  ← comptes et reprise de la trésorerie en ligne de commande
├── wsgi.py, passenger_wsgi.py ← points d'entrée WSGI et hébergeurs « Python App »
├── Dockerfile, docker-compose.yml, .env.example
├── start.bat                  ← installation et lancement sous Windows
├── requirements.txt           ← dépendances (Flask, pdfplumber, reportlab, requests, waitress, openpyxl)
└── requirements-dev.txt       ← + pytest, pyflakes
```

Pour tester la lecture d'une facture METRO en ligne de commande :

```bash
.venv\Scripts\python.exe -m factures.metro.lecture facture.pdf
```

## Tests

Les tests (comptes, sécurité, METRO, notes de frais, devis et factures, trésorerie : relevés,
classement groupé, répartition, compte de résultat, exports, justificatifs) n'utilisent que des
**données fictives** et un faux Nextcloud en mémoire. Les tests qui lisent de vraies factures
METRO ont besoin de PDF dans `tests/factures_exemple/` (non versionnés) ; sans eux, ils sont ignorés.

```bash
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

```bash
.venv\Scripts\python.exe -m pytest
```

## Auteurs

Fait par **[Sofiane Abichou](https://github.com/SofianeGh)** — Local Stock, mandat 2025/2026 · Trésorerie, mandat 2026/2027.

Co-auteur : **[Amar Ailane](https://github.com/AILANE-AMAR)** — Trésorerie, mandat 2025/2026. L'onglet Trésorerie reprend
son application [AML Trésorerie](https://github.com/AILANE-AMAR/AML-TRESO).

Réalisé avec l'aide et sur la base de l'ancien projet de **[Mathieu Flouret](https://github.com/megat69)** — Local Stock, mandat 2024/2026.

## Licence

Distribué sous licence MIT : voir [LICENSE](LICENSE).
