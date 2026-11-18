// Devis et factures de l'association : liste, formulaire, numérotation, transformation d'un devis en facture.
import { api, postJSON, putJSON } from "./api.js";
import { surOnglet } from "./onglets.js";
import { $, alerte, aujourdhui, dateFr, el, eur, lien, nombreSaisi, ouvrirApresEnregistrement, rapprochement } from "./outils.js";

const TYPES = { devis: "Devis", facture: "Facture" };
const STATUTS = {
  devis: { en_attente: ["En attente", "st-attente"], accepte: ["Accepté", "st-ok"], refuse: ["Refusé", "st-ko"] },
  facture: { a_payer: ["À payer", "st-attente"], payee: ["Payée", "st-ok"] },
};
const TVA = [["", "Non applicable"], ["0", "0 %"], ["5.5", "5,5 %"], ["10", "10 %"], ["20", "20 %"]];
const CHAMPS = ["numero", "date", "validite", "echeance", "nature", "statut", "client_nom", "client_adresse",
  "client_telephone", "client_email", "objet", "lieu", "description", "conditions", "notes"];
// repris d'un document à l'autre (dupliquer, transformer un devis en facture)
const CONTENU = ["nature", "client_nom", "client_adresse", "client_telephone", "client_email", "objet", "lieu",
  "description", "notes", "lignes"];

const editeur = $("#devis-editeur");
const form = $("#form-devis");
const q = (k) => form.querySelector(`[data-f="${k}"]`);
let pieces = [];
let clients = [];
let courant = null; // { id, type, devis_id, devis_numero, lignes, numeroAuto }
let cellules = [];
let charge = false;

surOnglet("devis", () => {
  if (!charge) {
    charge = true;
    charger();
  }
});

const arrondi = (v) => Math.round((v + Number.EPSILON) * 100) / 100;
const feminin = (type) => (type === "facture" ? "e" : "");

// ---------------------------------------------------------------- liste

async function charger() {
  try {
    pieces = await api("api/devis");
    afficherListe();
  } catch (e) {
    charge = false;
    $("#devis-vide").textContent = `Liste indisponible : ${e.message}`;
  }
}

function afficherListe() {
  const texte = $("#devis-recherche").value.trim().toLowerCase();
  const filtre = $("#devis-filtre").value;
  const visibles = pieces.filter((p) => (!filtre || p.type === filtre)
    && (!texte || `${p.numero} ${p.client} ${p.objet}`.toLowerCase().includes(texte)));
  $("#devis-liste").replaceChildren(...visibles.map(ligneListe));
  $("#devis-vide").hidden = visibles.length > 0;
  $("#devis-vide").textContent = pieces.length ? "Aucun document ne correspond." : "Aucun devis ni facture pour l'instant.";
}

function ligneListe(p) {
  const statuts = STATUTS[p.type];
  const suivi = el("select", { "aria-label": "Suivi" },
    ...Object.entries(statuts).map(([cle, [libelle]]) => el("option", { value: cle }, libelle)));
  const colorer = () => { suivi.className = `statut-liste ${statuts[suivi.value]?.[1] || ""}`; };
  suivi.value = p.statut;
  colorer();
  suivi.addEventListener("change", async () => {
    try {
      await postJSON(`api/devis/${p.id}/statut`, { statut: suivi.value });
      p.statut = suivi.value;
      colorer();
    } catch (e) {
      alerte(e.message);
      suivi.value = p.statut;
      colorer();
    }
  });
  const actions = [
    lien("Modifier", () => ouvrir(p.id)),
    el("a", { class: "lien", href: `api/devis/${p.id}/pdf`, target: "_blank", rel: "noopener" }, "PDF"),
  ];
  if (p.type === "devis") {
    actions.push(p.facture
      ? el("span", { class: "sub", title: "Facture établie d'après ce devis" }, `→ ${p.facture}`)
      : lien("Facturer", () => facturer(p.id), { title: "Créer la facture d'après ce devis" }));
  }
  actions.push(lien("Dupliquer", () => dupliquer(p.id)), lien("Supprimer", () => supprimer(p)));
  return el("tr", {},
    el("td", { class: "num numero" }, p.numero, el("span", { class: "sub type" }, TYPES[p.type])),
    el("td", { class: "num" }, dateFr(p.date)),
    el("td", {}, p.client),
    el("td", {}, p.objet, rapprochement(p.rapprochements)),
    el("td", { class: "num" }, eur.format(p.total_ttc)),
    el("td", {}, suivi),
    el("td", { class: "actions" }, ...actions));
}

$("#devis-recherche").addEventListener("input", afficherListe);
$("#devis-filtre").addEventListener("change", afficherListe);

async function supprimer(p) {
  if (!confirm(`Supprimer ${TYPES[p.type].toLowerCase()} ${p.numero} (${p.client}) ?`)) return;
  try {
    await api(`api/devis/${p.id}`, { method: "DELETE" });
    if (courant?.id === p.id) fermer();
    await charger();
  } catch (e) {
    alerte(e.message);
  }
}

// ---------------------------------------------------------------- formulaire

function message(texte, type = "") {
  q("statut").textContent = texte;
  q("statut").className = `statut ${type}`;
}

async function suggestion(type, date) {
  return api(`api/devis/nouveau?type=${type}&date=${encodeURIComponent(date || aujourdhui())}`);
}

async function nouveau(type, modele = null) {
  try {
    const proposition = await suggestion(type, aujourdhui());
    const contenu = modele ? Object.fromEntries(CONTENU.map((k) => [k, modele[k]])) : {};
    if (modele?.type === type && modele.conditions) contenu.conditions = modele.conditions;
    courant = { id: null, type, devis_id: modele?.devis_id ?? null, devis_numero: modele?.devis_numero ?? null,
      numeroAuto: true };
    remplir({
      nature: "Prestation de services", ...proposition, ...contenu, statut: Object.keys(STATUTS[type])[0],
      lignes: contenu.lignes?.length ? contenu.lignes : [{ designation: "", prix_ht: "", quantite: 1, tva: null }],
    });
  } catch (e) {
    alerte(e.message);
  }
}

async function ouvrir(id) {
  try {
    const p = await api(`api/devis/${id}`);
    courant = { id: p.id, type: p.type, devis_id: p.devis_id, devis_numero: p.devis_numero ?? null, numeroAuto: false };
    remplir(p);
  } catch (e) {
    alerte(e.message);
  }
}

async function dupliquer(id) {
  try {
    const p = await api(`api/devis/${id}`);
    await nouveau(p.type, { ...p, devis_id: null, devis_numero: null });
  } catch (e) {
    alerte(e.message);
  }
}

async function facturer(id) {
  try {
    const devis = await api(`api/devis/${id}`);
    const deja = pieces.find((x) => x.id === id)?.facture;
    if (deja && !confirm(`La facture ${deja} existe déjà pour ce devis. En créer une autre ?`)) return;
    await nouveau("facture", { ...devis, devis_id: devis.id, devis_numero: devis.numero });
  } catch (e) {
    alerte(e.message);
  }
}

function remplir(p) {
  const statut = form.elements.statut;
  statut.replaceChildren(...Object.entries(STATUTS[courant.type]).map(([cle, [libelle]]) =>
    el("option", { value: cle }, libelle)));
  for (const k of CHAMPS) form.elements[k].value = p[k] ?? "";
  form.querySelectorAll("[data-pour]").forEach((e) => { e.hidden = e.dataset.pour !== courant.type; });
  courant.lignes = (p.lignes || []).map((l) => ({
    designation: l.designation ?? "", prix_ht: l.prix_ht ?? "", quantite: l.quantite ?? 1, tva: l.tva ?? null,
  }));
  majTitre(p.numero);
  q("source").hidden = !courant.devis_numero;
  q("source").textContent = courant.devis_numero ? `Facture établie d'après le devis ${courant.devis_numero}.` : "";
  afficherLignes();
  message("");
  chargerClients();
  editeur.hidden = false;
  editeur.scrollIntoView({ behavior: "smooth", block: "start" });
}

function majTitre(numero) {
  const type = courant.type;
  q("titre").textContent = courant.id ? `${TYPES[type]} ${numero}` : type === "devis" ? "Nouveau devis" : "Nouvelle facture";
  q("transformer").hidden = !(courant.id && type === "devis");
}

function fermer() {
  editeur.hidden = true;
  courant = null;
}

$("#devis-nouveau").addEventListener("click", () => nouveau("devis"));
$("#facture-nouvelle").addEventListener("click", () => nouveau("facture"));
q("fermer").addEventListener("click", fermer);

// Nouveau document : la date change le numéro proposé (année) et la date de validité ou d'échéance
form.elements.numero.addEventListener("input", () => { if (courant) courant.numeroAuto = false; });
form.elements.date.addEventListener("change", async () => {
  if (!courant || courant.id || !form.elements.date.value) return;
  try {
    const proposition = await suggestion(courant.type, form.elements.date.value);
    if (courant.numeroAuto) form.elements.numero.value = proposition.numero;
    if (courant.type === "devis") form.elements.validite.value = proposition.validite;
    else form.elements.echeance.value = proposition.echeance;
  } catch { /* on garde les valeurs saisies */ }
});

// ---------------------------------------------------------------- clients déjà enregistrés

async function chargerClients() {
  try {
    clients = await api("api/devis/clients");
  } catch {
    clients = [];
  }
  q("clients").replaceChildren(
    el("option", { value: "" }, clients.length ? "Choisir pour remplir les cases ci-dessous…" : "Aucun pour l'instant"),
    ...clients.map((c, i) => el("option", { value: String(i) }, c.nom.replace(/\n/g, " · "))));
}

q("clients").addEventListener("change", () => {
  const c = clients[q("clients").value];
  if (!c) return;
  for (const k of ["nom", "adresse", "telephone", "email"]) form.elements[`client_${k}`].value = c[k] || "";
  q("clients").value = "";
});

// ---------------------------------------------------------------- lignes

function afficherLignes() {
  cellules = [];
  q("lignes").replaceChildren(...courant.lignes.map((l, i) => {
    const designation = el("textarea", { rows: "1", maxlength: "300", required: "", "aria-label": "Désignation", placeholder: "Formule sandwich" });
    designation.value = l.designation;
    designation.addEventListener("input", () => { l.designation = designation.value; });
    const prix = el("input", { type: "number", step: "0.01", required: "", inputmode: "decimal", class: "montant", "aria-label": "Prix HT" });
    prix.value = l.prix_ht;
    prix.addEventListener("input", () => { l.prix_ht = prix.value; recalc(); });
    const quantite = el("input", { type: "number", step: "any", min: "0", required: "", inputmode: "decimal", class: "qte", "aria-label": "Quantité" });
    quantite.value = l.quantite;
    quantite.addEventListener("input", () => { l.quantite = quantite.value; recalc(); });
    const tva = el("select", { "aria-label": "TVA" }, ...TVA.map(([v, libelle]) => el("option", { value: v }, libelle)));
    tva.value = l.tva == null ? "" : String(l.tva);
    tva.addEventListener("change", () => { l.tva = tva.value === "" ? null : Number(tva.value); recalc(); });
    const retirer = el("button", { class: "reset", type: "button", title: "Retirer la ligne", "aria-label": "Retirer la ligne" }, "×");
    retirer.addEventListener("click", () => { courant.lignes.splice(i, 1); afficherLignes(); });
    const totalHT = el("td", { class: "num" });
    const totalTTC = el("td", { class: "num" });
    cellules.push({ totalHT, totalTTC });
    return el("tr", {}, el("td", { class: "designation" }, designation), el("td", { class: "num" }, prix),
      el("td", { class: "num" }, quantite), el("td", {}, tva), totalHT, totalTTC,
      el("td", {}, courant.lignes.length > 1 ? retirer : ""));
  }));
  recalc();
}

// Mêmes règles que le serveur : total HT par ligne, TVA arrondie une fois par taux
function recalc() {
  const bases = new Map();
  courant.lignes.forEach((l, i) => {
    const taux = l.tva ?? 0;
    const ht = arrondi(nombreSaisi(l.prix_ht) * nombreSaisi(l.quantite));
    cellules[i].totalHT.textContent = eur.format(ht);
    cellules[i].totalTTC.textContent = eur.format(arrondi(ht * (1 + taux / 100)));
    bases.set(l.tva ?? null, (bases.get(l.tva ?? null) || 0) + ht);
  });
  let totalHT = 0;
  let totalTVA = 0;
  for (const [taux, base] of bases) {
    totalHT += base;
    totalTVA += arrondi(base * (taux ?? 0) / 100);
  }
  q("total-ht").textContent = eur.format(totalHT);
  q("total-tva").textContent = eur.format(totalTVA);
  q("total-ttc").textContent = eur.format(totalHT + totalTVA);
}

q("ajouter-ligne").addEventListener("click", () => {
  courant.lignes.push({ designation: "", prix_ht: "", quantite: 1, tva: courant.lignes.at(-1)?.tva ?? null });
  afficherLignes();
  q("lignes").querySelector("tr:last-child textarea")?.focus();
});

// ---------------------------------------------------------------- enregistrement

function lireFormulaire() {
  const p = { type: courant.type };
  for (const k of CHAMPS) p[k] = form.elements[k].value;
  p.lignes = courant.lignes.map((l) => ({
    designation: l.designation, prix_ht: nombreSaisi(l.prix_ht), quantite: nombreSaisi(l.quantite), tva: l.tva,
  }));
  if (!courant.id && courant.devis_id) p.devis_id = courant.devis_id;
  return p;
}

// Renvoie l'identifiant du document enregistré, ou null
async function enregistrer() {
  if (!form.reportValidity()) return null;
  if (!courant.lignes.length) {
    message("Ajoutez au moins une ligne.", "ko");
    return null;
  }
  const boutons = form.querySelectorAll(".editeur-actions .btn");
  boutons.forEach((b) => { b.disabled = true; });
  message("Enregistrement…");
  try {
    const p = courant.id ? await putJSON(`api/devis/${courant.id}`, lireFormulaire())
      : await postJSON("api/devis", lireFormulaire());
    courant.id = p.id;
    courant.numeroAuto = false;
    form.elements.numero.value = p.numero;
    majTitre(p.numero);
    message(`✓ ${TYPES[p.type]} ${p.numero} enregistré${feminin(p.type)}`, "ok");
    charger();
    return p.id;
  } catch (e) {
    message(e.message, "ko");
    return null;
  } finally {
    boutons.forEach((b) => { b.disabled = false; });
  }
}

form.addEventListener("submit", (e) => {
  e.preventDefault();
  enregistrer();
});
q("pdf").addEventListener("click", () => ouvrirApresEnregistrement(async () => {
  const id = await enregistrer();
  return id ? `api/devis/${id}/pdf` : null;
}));
q("transformer").addEventListener("click", async () => {
  const id = await enregistrer();
  if (id) await facturer(id);
});
