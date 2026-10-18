// Outils partagés : accès au DOM, mise en forme des nombres, état de la page.

export const $ = (sel, root = document) => root.querySelector(sel);

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
