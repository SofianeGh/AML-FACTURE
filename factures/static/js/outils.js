// Outils partagés : accès au DOM, mise en forme des nombres et des dates, état de la page.

export const $ = (sel, root = document) => root.querySelector(sel);

// Dates au format des champs date (« AAAA-MM-JJ »), en heure locale
const isoLocal = (d) => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
export const aujourdhui = () => isoLocal(new Date());
export function plusJours(iso, jours) {
  const d = new Date(`${iso}T12:00:00`);
  d.setDate(d.getDate() + jours);
  return isoLocal(d);
}
export const dateFr = (iso) => (iso ? iso.split("-").reverse().join("/") : "");

// Nombre saisi (« 8,50 » accepté) ; 0 si vide ou illisible
export function nombreSaisi(valeur) {
  const n = parseFloat(String(valeur ?? "").replace(/[\s ]/g, "").replace(",", "."));
  return Number.isFinite(n) ? n : 0;
}

// Bouton d'apparence « lien » qui appelle `action`
export function lien(texte, action, attrs = {}) {
  const b = el("button", { class: "lien", type: "button", ...attrs }, texte);
  b.addEventListener("click", action);
  return b;
}

// Ouvre un PDF dans un nouvel onglet une fois `enregistrer()` terminé (qui renvoie l'adresse ou null).
// L'onglet est ouvert tout de suite, pendant le clic, pour ne pas être bloqué par le navigateur.
export async function ouvrirApresEnregistrement(enregistrer) {
  const onglet = window.open("", "_blank");
  const adresse = await enregistrer();
  if (adresse && onglet) onglet.location.href = new URL(adresse, location.href).href;
  else if (onglet) onglet.close();
}

export function el(tag, attrs = {}, ...enfants) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else node.setAttribute(k, v);
  }
  node.append(...enfants.filter((e) => e != null && e !== false));
  return node;
}

export const eur = new Intl.NumberFormat("fr-FR", { style: "currency", currency: "EUR" });
export const eur3 = new Intl.NumberFormat("fr-FR", {
  style: "currency", currency: "EUR", minimumFractionDigits: 3, maximumFractionDigits: 3,
});
export const nombre = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 3 });
export const pct = (v) => (v == null ? "?" : `${nombre.format(v)} %`);

// Catégorie de dépense de chaque ligne (mêmes clés que CATEGORIES dans factures/pdf/commun.py).
// Seules les lignes VENTE ont un prix de vente ; un PDF est créé pour chaque catégorie utilisée.
export const CATEGORIES = {
  vente: "Vente",
  event: "Event",
  local: "Local",
  cadeau: "Cadeau conducteur",
  hors: "Hors catégorie",
};

// État de la page. `pret` : promesse résolue quand préférences et réglages sont chargés.
export const state = { config: null, moi: null, factures: [], pret: null };

// Bandeau d'erreur en haut de page (texte vide = masqué)
export function alerte(texte) {
  const bandeau = $("#alerte");
  bandeau.textContent = texte;
  bandeau.hidden = !texte;
}
