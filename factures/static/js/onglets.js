// Onglets du haut : Factures METRO, Notes de frais, Devis et factures, Trésorerie.
// L'onglet ouvert est noté dans l'adresse (#ndf, #devis, #treso) pour être retrouvé en rechargeant la page.
const ONGLETS = { metro: "Factures METRO", ndf: "Notes de frais", devis: "Devis et factures", treso: "Trésorerie" };
const ecouteurs = {};
let actif = null;

export const ongletActif = () => actif;

// `action` est lancée à chaque ouverture de l'onglet (et tout de suite s'il est déjà ouvert)
export function surOnglet(nom, action) {
  (ecouteurs[nom] ||= []).push(action);
  if (actif === nom) action();
}

function afficher(nom) {
  if (!(nom in ONGLETS)) nom = "metro";
  if (nom === actif) return;
  actif = nom;
  document.querySelectorAll(".onglets [data-onglet]").forEach((b) =>
    b.setAttribute("aria-selected", String(b.dataset.onglet === nom)));
  document.querySelectorAll("[data-vue]").forEach((v) => { v.hidden = v.dataset.vue !== nom; });
  document.querySelectorAll("[data-seulement]").forEach((e) => { e.hidden = e.dataset.seulement !== nom; });
  document.title = nom === "metro" ? "AML Factures" : `${ONGLETS[nom]} · AML Factures`;
  (ecouteurs[nom] || []).forEach((action) => action());
}

document.querySelectorAll(".onglets [data-onglet]").forEach((bouton) => bouton.addEventListener("click", () => {
  const nom = bouton.dataset.onglet;
  history.replaceState(null, "", nom === "metro" ? location.pathname + location.search : `#${nom}`);
  afficher(nom);
}));
window.addEventListener("hashchange", () => afficher(location.hash.slice(1)));
afficher(location.hash.slice(1));
