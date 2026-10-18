// Échanges avec le serveur et préférences partagées entre les membres.
import { alerte } from "./outils.js";

// Adresses relatives (« api/… ») : l'application peut être servie dans un sous-dossier du site.
// L'en-tête X-Requested-With est exigé par le serveur pour toute modification (anti-CSRF).
export async function api(url, options = {}) {
  const resp = await fetch(url, {
    ...options, headers: { "X-Requested-With": "fetch", ...options.headers },
  });
  if (resp.status === 401) {
    location.href = "connexion"; // session expirée
    throw new Error("Session expirée : reconnectez-vous.");
  }
  let data = null;
  try { data = await resp.json(); } catch { /* réponse non JSON */ }
  if (!resp.ok) throw new Error(data?.erreur || `Erreur HTTP ${resp.status}`);
  return data;
}

export const postJSON = (url, body) => api(url, {
  method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
});

// Préférences partagées entre tous les membres (marge, taxe TPE, arrondi ; par article :
// pièces, prix choisi, catégorie Local ; noms des conducteurs). Chargées au démarrage,
// enregistrées sur le serveur par petits lots (une requête pour plusieurs frappes).
export const store = {
  valeurs: {},
  enAttente: {},
  minuteur: null,
  get(cle, defaut) {
    return cle in this.valeurs ? this.valeurs[cle] : defaut;
  },
  set(cle, valeur) {
    this.valeurs[cle] = valeur;
    this.planifier(cle, valeur);
  },
  remove(cle) {
    delete this.valeurs[cle];
    this.planifier(cle, null);
  },
  planifier(cle, valeur) {
    this.enAttente[cle] = valeur;
    clearTimeout(this.minuteur);
    this.minuteur = setTimeout(() => this.envoyer(), 500);
  },
  async envoyer() {
    const lot = this.enAttente;
    this.enAttente = {};
    if (!Object.keys(lot).length) return;
    try {
      await api("api/preferences", {
        method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(lot),
      });
      alerte("");
    } catch (e) {
      alerte(`Préférences non enregistrées : ${e.message}`);
    }
  },
};

// enregistre ce qui reste avant de quitter la page
window.addEventListener("pagehide", () => {
  if (!Object.keys(store.enAttente).length) return;
  fetch("api/preferences", {
    method: "PUT", keepalive: true,
    headers: { "Content-Type": "application/json", "X-Requested-With": "fetch" },
    body: JSON.stringify(store.enAttente),
  });
});
