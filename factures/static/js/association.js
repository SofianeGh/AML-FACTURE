// Infos de l'association (adresse, SIRET, contacts, IBAN, préfixes…) : imprimées sur les devis,
// factures et notes de frais. Tout le monde peut les lire, un administrateur les modifie.
import { api, putJSON } from "./api.js";
import { $, state } from "./outils.js";

let cache = null;

export function association(recharger = false) {
  if (!cache || recharger) cache = api("api/association").catch((e) => { cache = null; throw e; });
  return cache;
}

const dlg = $("#dlg-association");
const form = $("#form-association");
const q = (k) => form.querySelector(`[data-f="${k}"]`);

async function ouvrir() {
  q("erreur").textContent = "";
  let a;
  try {
    a = await association();
  } catch (e) {
    q("erreur").textContent = e.message;
    dlg.showModal();
    return;
  }
  for (const champ of form.elements) {
    if (champ.name && champ.name in a) champ.value = a[champ.name] ?? "";
  }
  const lecture = !state.moi?.admin;
  for (const champ of form.elements) if (champ.name) champ.readOnly = lecture;
  q("lecture").hidden = !lecture;
  q("enregistrer").hidden = lecture;
  dlg.showModal();
}

document.querySelectorAll("[data-action=association]").forEach((b) => b.addEventListener("click", ouvrir));

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const valeurs = Object.fromEntries([...form.elements].filter((c) => c.name).map((c) => [c.name, c.value]));
  const bouton = q("enregistrer");
  bouton.disabled = true;
  try {
    const a = await putJSON("api/association", valeurs);
    cache = Promise.resolve(a);
    dlg.close();
  } catch (err) {
    q("erreur").textContent = err.message;
  } finally {
    bouton.disabled = false;
  }
});
