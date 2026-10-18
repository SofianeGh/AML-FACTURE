// Calculs : coût par pièce, prix optimal, TTC, chiffre d'affaires ; réglages du haut de page.
import { store } from "./api.js";
import { $ } from "./outils.js";

const margeInput = $("#marge");
const margeType = $("#marge-type");
const arrondiSel = $("#arrondi");
const taxeInput = $("#taxe");
export const champsReglages = [margeInput, margeType, taxeInput, arrondiSel];

const lireNombre = (input) => Math.max(0, parseFloat(String(input.value).replace(",", ".")) || 0);

export function reglages() {
  return {
    marge: lireNombre(margeInput),
    type: margeType.value,
    taxe: lireNombre(taxeInput),
    pas: parseFloat(arrondiSel.value) || 0,
  };
}

// Réglages tels que saisis (imprimés dans le bilan des ventes)
export function reglagesSaisis() {
  return { marge: margeInput.value, margeType: margeType.value, taxe: taxeInput.value, arrondi: arrondiSel.value };
}

export function afficherReglages() {
  margeInput.value = store.get("marge", "20");
  margeType.value = store.get("margeType", "pct");
  arrondiSel.value = store.get("arrondi", "0");
  taxeInput.value = store.get("taxe", "");
}

export function enregistrerReglages() {
  store.set("marge", margeInput.value);
  store.set("margeType", margeType.value);
  store.set("arrondi", arrondiSel.value);
  store.set("taxe", taxeInput.value);
}

// Prix optimal = coût TTC + marge + taxe TPE (la marge ne s'applique pas sur la taxe), arrondi
export function prixOptimal(coutTTC, r) {
  let pv = (r.type === "pct" ? coutTTC * (1 + r.marge / 100) : coutTTC + r.marge) + r.taxe;
  if (r.pas > 0) pv = Math.ceil(pv / r.pas - 1e-9) * r.pas;
  return Math.round(pv * 100) / 100;
}

// Une ligne hors VENTE n'a pas de prix de vente : elle coûte sans rapporter.
// `prixChoisi` : prix saisi par l'utilisateur, ou null pour vendre au prix optimal.
export function calcLigne(ligne, pieces, vendu, prixChoisi, r) {
  const taux = ligne.tva_taux ?? 0;
  const nb = ligne.unites * pieces;
  const coutHT = nb ? ligne.montant_net_ht / nb : 0;
  const coutTTC = coutHT * (1 + taux / 100);
  const optimal = vendu ? prixOptimal(coutTTC, r) : null;
  const pv = vendu ? (prixChoisi ?? optimal) : null;
  return {
    nb, coutHT, coutTTC, optimal, pv,
    perte: vendu && pv < coutTTC + r.taxe,
    totalTTC: ligne.montant_net_ht * (1 + taux / 100),
    taxes: vendu ? r.taxe * nb : 0,
    ca: vendu ? pv * nb : 0,
  };
}
