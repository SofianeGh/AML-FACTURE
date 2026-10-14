"""Client WebDAV minimal pour Nextcloud : lister/créer des dossiers, déposer un fichier."""
import posixpath
import xml.etree.ElementTree as ET
from urllib.parse import quote, unquote, urlsplit

import requests

DAV_NS = "{DAV:}"
PROPFIND_BODY = (
    '<?xml version="1.0"?>'
    '<d:propfind xmlns:d="DAV:"><d:prop>'
    "<d:resourcetype/><d:getcontentlength/>"
    "</d:prop></d:propfind>"
)
TIMEOUT = 30


class NextcloudError(Exception):
    pass


def base_url(url):
    """Accepte « https://cloud.exemple.fr », « .../index.php » ou l'URL WebDAV complète."""
    url = (url or "").strip()
    if not url:
        raise NextcloudError("Adresse du serveur Nextcloud manquante.")
    if "://" not in url:
        url = "https://" + url
    for marqueur in ("/remote.php", "/index.php"):
        if marqueur in url:
            url = url.split(marqueur, 1)[0]
    return url.rstrip("/")


def clean_path(path):
    """Normalise un chemin de dossier : « /Factures//Metro/ » -> « Factures/Metro »."""
    parts = [p for p in (path or "").replace("\\", "/").split("/") if p and p != "."]
    if ".." in parts:
        raise NextcloudError("Chemin de dossier invalide.")
    return "/".join(parts)


class Nextcloud:
    def __init__(self, url, login, password, user_id=None):
        if not login or not password:
            raise NextcloudError("Identifiant ou mot de passe d'application Nextcloud manquant.")
        self.base = base_url(url)
        self.login = login
        self.session = requests.Session()
        self.session.auth = (login, password)
        self.user_id = user_id or login

    # -- utilitaires -------------------------------------------------------
    def _root(self):
        return f"{self.base}/remote.php/dav/files/{quote(self.user_id)}"

    def _url(self, path):
        path = clean_path(path)
        return self._root() + ("/" + quote(path) if path else "")

    def _request(self, method, path, **kw):
        kw.setdefault("timeout", TIMEOUT)
        try:
            resp = self.session.request(method, self._url(path), **kw)
        except requests.RequestException as exc:
            raise NextcloudError(f"Serveur Nextcloud injoignable : {exc}") from exc
        if resp.status_code == 401:
            raise NextcloudError("Identifiants refusés par Nextcloud (401). Utilisez un mot de passe d'application.")
        return resp

    def _propfind(self, path, depth):
        resp = self._request(
            "PROPFIND", path, data=PROPFIND_BODY,
            headers={"Depth": str(depth), "Content-Type": "application/xml"},
        )
        if resp.status_code == 404:
            return None
        if resp.status_code != 207:
            raise NextcloudError(f"Lecture du dossier impossible (HTTP {resp.status_code}).")
        entrees = []
        for r in ET.fromstring(resp.content).iter(DAV_NS + "response"):
            href = unquote(urlsplit(r.findtext(DAV_NS + "href", "")).path)
            prop = r.find(f"{DAV_NS}propstat/{DAV_NS}prop")
            dossier = prop is not None and prop.find(f"{DAV_NS}resourcetype/{DAV_NS}collection") is not None
            taille = prop.findtext(DAV_NS + "getcontentlength") if prop is not None else None
            entrees.append({
                "href": href.rstrip("/"),
                "nom": posixpath.basename(href.rstrip("/")),
                "dossier": dossier,
                "taille": int(taille) if taille and taille.isdigit() else None,
            })
        return entrees

    # -- API -----------------------------------------------------------------
    def resolve_user_id(self):
        """Récupère l'identifiant interne (peut différer du login, ex. connexion par e-mail)."""
        try:
            resp = self.session.get(
                f"{self.base}/ocs/v2.php/cloud/user",
                params={"format": "json"},
                headers={"OCS-APIRequest": "true"},
                timeout=TIMEOUT,
            )
            if resp.ok:
                self.user_id = resp.json()["ocs"]["data"]["id"]
        except (requests.RequestException, ValueError, KeyError, TypeError):
            pass  # on garde le login comme identifiant
        return self.user_id

    def check(self):
        """Vérifie l'accès à l'espace de fichiers de l'utilisateur."""
        self.resolve_user_id()
        if self._propfind("", 0) is None:
            raise NextcloudError("Espace de fichiers introuvable : vérifiez l'adresse et l'identifiant.")
        return self.user_id

    def list_folders(self, path=""):
        entrees = self._propfind(path, 1)
        if entrees is None:
            raise NextcloudError(f"Dossier introuvable : /{clean_path(path)}")
        # la première entrée est le dossier lui-même
        return sorted((e["nom"] for e in entrees[1:] if e["dossier"]), key=str.lower)

    def make_dirs(self, path):
        courant = ""
        for part in clean_path(path).split("/"):
            if not part:
                continue
            courant = f"{courant}/{part}" if courant else part
            if self._propfind(courant, 0) is None:
                resp = self._request("MKCOL", courant)
                if resp.status_code not in (201, 405):  # 405 : existe déjà
                    raise NextcloudError(f"Création du dossier /{courant} impossible (HTTP {resp.status_code}).")

    def upload(self, folder, filename, data):
        """Dépose `data` dans `folder` sous `filename`.

        Si un fichier du même nom existe déjà : identique (même taille) -> rien
        n'est envoyé ; sinon on ajoute « (2) », « (3) »… au nom.
        Retourne {"nom": ..., "chemin": ..., "deja_present": bool}.
        """
        folder = clean_path(folder)
        self.make_dirs(folder)
        racine, ext = posixpath.splitext(filename)
        for i in range(1, 100):
            nom = filename if i == 1 else f"{racine} ({i}){ext}"
            chemin = f"{folder}/{nom}" if folder else nom
            existant = self._propfind(chemin, 0)
            if existant is None:
                break
            if existant[0]["taille"] == len(data):
                return {"nom": nom, "chemin": "/" + chemin, "deja_present": True}
        else:
            raise NextcloudError("Trop de fichiers portant le même nom dans ce dossier.")

        self._put(chemin, data)
        return {"nom": nom, "chemin": "/" + chemin, "deja_present": False}

    def put(self, folder, filename, data):
        """Dépose ou remplace `filename` dans `folder` (qui doit déjà exister)."""
        folder = clean_path(folder)
        chemin = f"{folder}/{filename}" if folder else filename
        self._put(chemin, data)
        return {"nom": filename, "chemin": "/" + chemin}

    def delete(self, folder, filename):
        """Supprime `filename` s'il existe (il part dans la corbeille Nextcloud). True si supprimé."""
        folder = clean_path(folder)
        chemin = f"{folder}/{filename}" if folder else filename
        resp = self._request("DELETE", chemin)
        if resp.status_code == 404:
            return False
        if resp.status_code not in (200, 204):
            raise NextcloudError(f"Suppression de /{chemin} impossible (HTTP {resp.status_code}).")
        return True

    def _put(self, chemin, data):
        resp = self._request("PUT", chemin, data=data, headers={"Content-Type": "application/pdf"})
        if resp.status_code not in (200, 201, 204):
            raise NextcloudError(f"Envoi refusé par Nextcloud (HTTP {resp.status_code}).")
