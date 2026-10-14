# Mise en ligne sur le site de l'AML

L'application est un serveur web Python (Flask, servi par waitress). Elle doit tourner sur une
machine qui accepte Python ou Docker, derrière le serveur web du site (nginx, Apache…) qui
s'occupe du **HTTPS**.

> Un hébergement mutualisé « PHP seulement » (sans Python ni Docker) ne peut pas la faire
> tourner. Dans ce cas, il faut un petit VPS ou une machine de l'association.

## Ce qui protège l'application

- **Accès par compte** : toutes les pages et l'API demandent une connexion. Rôles *membre*
  (traiter et envoyer les factures) et *administrateur* (en plus : comptes et connexion Nextcloud).
- **Mots de passe** hachés (scrypt), 8 caractères minimum ; 5 essais ratés en 10 minutes
  bloquent l'adresse IP.
- **Session** dans un cookie signé, `HttpOnly`, `Secure`, `SameSite=Lax`, valable 12 heures.
- **Anti-CSRF** : toute modification exige l'en-tête `X-Requested-With: fetch`, envoyé par l'interface.
- **En-têtes** : Content-Security-Policy, X-Frame-Options, nosniff, Referrer-Policy, HSTS (en HTTPS).
- **Mot de passe Nextcloud** gardé côté serveur (base SQLite), jamais renvoyé au navigateur.
  Utilisez un **mot de passe d'application** Nextcloud dédié, révocable à tout moment.

## Données

Tout est dans le dossier `DATA_DIR` (`./data` par défaut, `/data` dans Docker) :

| Fichier | Contenu |
|---|---|
| `aml-factures.db` | comptes, connexion Nextcloud, préférences partagées (marge, taxe TPE, prix…) |
| `secret_key` | clé de signature des sessions (générée au premier lancement) |

Sauvegardez ce dossier. Les factures, elles, ne sont pas conservées sur le serveur :
elles partent sur Nextcloud.

## Variables d'environnement

| Variable | Défaut | Rôle |
|---|---|---|
| `HOST` | `127.0.0.1` | adresse d'écoute (`0.0.0.0` dans Docker) |
| `PORT` | `5000` | port d'écoute (`8000` dans Docker) |
| `THREADS` | `8` | requêtes traitées en parallèle |
| `DATA_DIR` | `./data` | dossier des données |
| `TRUST_PROXY` | `0` | nombre de reverse proxys devant l'appli (mettre `1` derrière nginx/Apache) |
| `COOKIE_SECURE` | `1` | `0` uniquement pour un usage local en http |
| `SECRET_KEY` | générée | clé de session fixe (facultative) |
| `ADMIN_UTILISATEUR` / `ADMIN_MOT_DE_PASSE` | — | crée le premier administrateur si aucun compte n'existe |

Lancer **un seul processus** (avec plusieurs threads, ce que fait `python app.py`) :
l'aperçu des PDF par catégorie garde les factures analysées en mémoire.

## Option A — Docker (recommandé)

Sur le serveur :

```bash
git clone https://github.com/SofianeGh/AML-FACTURE.git aml-factures
```

```bash
cd aml-factures && cp .env.example .env && nano .env
```

Dans `.env`, choisissez l'identifiant et un mot de passe provisoire du premier administrateur, puis :

```bash
docker compose up -d --build
```

L'application écoute sur `127.0.0.1:8000` (pas directement accessible depuis Internet).
Connectez-vous, changez le mot de passe (« Mot de passe » en haut de la page), puis videz
`ADMIN_MOT_DE_PASSE` dans `.env`.

Mise à jour :

```bash
git pull && docker compose up -d --build
```

## Option B — Python sans Docker (VPS Linux)

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

```bash
.venv/bin/python manage.py ajouter-utilisateur sofiane --admin
```

Service systemd `/etc/systemd/system/aml-factures.service` :

```ini
[Unit]
Description=Factures METRO (AML)
After=network.target

[Service]
User=aml
WorkingDirectory=/opt/aml-factures
Environment=TRUST_PROXY=1 PORT=8000 DATA_DIR=/opt/aml-factures/data
ExecStart=/opt/aml-factures/.venv/bin/python app.py
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now aml-factures
```

## Option C — Hébergement avec « Setup Python App » (cPanel, Plesk, o2switch…)

Créer une application Python pointant sur ce dossier : le fichier d'entrée est
`passenger_wsgi.py` (objet `application`). Installer `requirements.txt` depuis l'interface,
définir `TRUST_PROXY=1` et `DATA_DIR` (dossier hors du répertoire public), puis créer le
premier compte avec `python manage.py ajouter-utilisateur NOM --admin` dans le terminal de l'hébergeur.
L'hébergeur doit lancer un seul processus pour l'application.

## Reverse proxy et HTTPS

### Sous-domaine, ex. `https://factures.aml-exemple.fr`

```nginx
server {
    listen 443 ssl;
    server_name factures.aml-exemple.fr;
    # certificats : certbot --nginx -d factures.aml-exemple.fr

    client_max_body_size 25m;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### Sous-dossier du site, ex. `https://aml-exemple.fr/factures/`

```nginx
location = /factures { return 301 /factures/; }

location /factures/ {
    proxy_pass http://127.0.0.1:8000/;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-Prefix /factures;
    client_max_body_size 25m;
}
```

Avec Apache (`mod_proxy`, `mod_headers`) :

```apache
<Location "/factures/">
    ProxyPass "http://127.0.0.1:8000/"
    ProxyPassReverse "http://127.0.0.1:8000/"
    RequestHeader set X-Forwarded-Proto "https"
    RequestHeader set X-Forwarded-Prefix "/factures"
</Location>
LimitRequestBody 26214400
```

Dans les deux cas, `TRUST_PROXY=1` est obligatoire, et l'adresse doit se terminer par `/`
(`/factures/`), d'où la redirection de `/factures`.

## Comptes

Depuis l'interface (administrateurs) : **Comptes** en haut de la page pour créer ou supprimer
les comptes des membres Local Stock. Chacun peut changer son mot de passe (« Mot de passe »).

En ligne de commande (dans Docker : `docker compose exec factures python manage.py …`) :

```bash
python manage.py lister-utilisateurs
```

```bash
python manage.py ajouter-utilisateur prenom
```

```bash
python manage.py mot-de-passe prenom
```

```bash
python manage.py admin prenom oui
```

```bash
python manage.py supprimer-utilisateur prenom
```

À chaque nouveau mandat : créer les comptes de la nouvelle équipe, supprimer ceux de l'ancienne.

## Journal

Les connexions, échecs de connexion, envois de factures et changements de comptes ou de
connexion Nextcloud sont écrits dans la sortie standard (`docker compose logs factures`,
`journalctl -u aml-factures`).
