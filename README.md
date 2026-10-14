# Factures METRO

Application web locale pour l'**AML** (Association des Informaticiens Lyonnais) :
elle lit les factures METRO, calcule les prix de vente TTC avec marge, classe chaque
dépense par catégorie et archive le tout sur **Nextcloud**.

## Fonctionnalités

- **Lecture des factures METRO (PDF)** : chaque ligne est extraite (prix unitaire HT, colisage,
  quantité, remises, code et taux de TVA). Un bandeau vert confirme que la somme des lignes lues
  correspond au récapitulatif TVA imprimé sur la facture ; en cas d'écart, il passe en rouge.
- **Prix TTC et marge en direct** : coût HT et TTC par pièce, prix de vente optimal, prix de vente
  modifiable, chiffre d'affaires et bénéfice, recalculés à chaque frappe.
- **Catégories de dépense** par ligne : Vente, Event, Local, Cadeau conducteur, Hors catégorie.
- **Archivage Nextcloud** : la facture est envoyée dans le dossier choisi, renommée à sa date
  (`JJ-MM-AAAA.pdf`), avec un PDF récapitulatif par catégorie.
- **Export CSV** de la liste de prix (ouvrable dans Excel).
- Plusieurs factures à la fois (glisser-déposer), thème clair / sombre automatique.

## Installation et lancement

Prérequis : Windows avec **Python 3.10 ou plus récent**.

Double-cliquer sur `start.bat`. Au premier lancement, l'environnement Python (`.venv`) est créé
et les dépendances sont installées, puis la page http://localhost:5000 s'ouvre.

En ligne de commande :

```bash
.venv\Scripts\python.exe app.py
```

Variables d'environnement optionnelles :

| Variable | Défaut | Rôle |
|---|---|---|
| `PORT` | `5000` | port du serveur |
| `HOST` | `127.0.0.1` | mettre `0.0.0.0` pour y accéder depuis un autre poste du réseau local |

## Utilisation

1. Cliquer sur ⚙ pour connecter Nextcloud (voir plus bas), puis choisir le dossier de destination.
2. Déposer une ou plusieurs factures METRO (PDF) dans la zone prévue.
3. Régler la **marge**, la **taxe TPE** et l'**arrondi** en haut de la page.
4. Pour chaque ligne, ajuster si besoin la **catégorie**, les **pièces par unité** et le **prix de vente**.
5. Cliquer sur **Envoyer sur Nextcloud** (ou **Tout envoyer** s'il y a plusieurs factures).

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

### Ce qui est mémorisé (dans le navigateur)

- marge, taxe TPE et arrondi ;
- par article : pièces par unité, prix de vente saisi, catégorie *Local* (produits utilisés au
  local à chaque fois). Ces choix sont repris sur les autres factures et les suivantes.

Les autres catégories (Event, Cadeau conducteur, Hors catégorie) ne valent que pour la ligne choisie.

## Nextcloud

Cliquer sur ⚙ et saisir l'adresse du serveur, l'identifiant et un **mot de passe d'application**
(Nextcloud → Paramètres personnels → Sécurité → « Créer un nouveau mot de passe d'application »).
Ces informations sont enregistrées dans `config.json`, à côté de l'application (fichier exclu de
git) ; le mot de passe n'est jamais renvoyé au navigateur.

### Fichiers envoyés

```
18-09-2026.pdf                       ← la facture METRO d'origine
18-09-2026 - VENTE.pdf               ← un récapitulatif par catégorie utilisée
18-09-2026 - EVENT.pdf
18-09-2026 - LOCAL.pdf
18-09-2026 - CADEAU CONDUCTEUR.pdf
18-09-2026 - HORS CATEGORIE.pdf
```

- Un nom de fichier ne peut pas contenir « / » : la date est écrite `JJ-MM-AAAA`.
- Facture déjà présente (même nom, même taille) : elle n'est pas renvoyée.
  Autre facture le même jour : `30-09-2026 (2).pdf`, et ses récapitulatifs suivent ce nom.
- Renvoyer une facture remplace ses récapitulatifs ; celui d'une catégorie qui n'a plus de
  ligne est supprimé (il part dans la corbeille Nextcloud).
- Chaque récapitulatif liste les lignes de la catégorie (HT, TVA, TTC) et le total par taux de
  TVA. La TVA étant arrondie par catégorie, la somme des récapitulatifs peut différer d'un
  centime du total de la facture.

## Structure du projet

| Fichier | Rôle |
|---|---|
| `app.py` | serveur web Flask et API |
| `metro_parser.py` | lecture des factures METRO (`python metro_parser.py facture.pdf` pour tester) |
| `nextcloud.py` | client WebDAV Nextcloud |
| `recap_pdf.py` | PDF récapitulatif par catégorie |
| `static/` | interface (HTML, CSS, JavaScript) |
| `start.bat` | installation et lancement sous Windows |
| `requirements.txt` | dépendances Python (Flask, pdfplumber, reportlab, requests) |

## Auteur

Fait par **[Sofiane Abichou](https://github.com/SofianeGh)** — Local Stock, mandat 2025/2026.

## Licence

Distribué sous licence MIT : voir [LICENSE](LICENSE).
