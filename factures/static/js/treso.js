// Trésorerie (reprise d'AML Trésorerie) : transactions du relevé, classement (une par une ou plusieurs
// d'un coup), répartition d'une transaction sur plusieurs classeurs, justificatifs (fichiers, notes de
// frais, factures), compte de résultat et exports, mandats et classeurs.
import { api, postJSON, putJSON } from "./api.js";
import { surOnglet } from "./onglets.js";
import { $, alerte, dateFr, el, eur, lien, nombreSaisi } from "./outils.js";

const STATUTS_DOC = { remboursee: "remboursée", a_rembourser: "à rembourser", payee: "payée", a_payer: "à payer" };
const vue = $("[data-vue=treso]");
const choixMandat = $("#treso-mandat");
let mandats = [];
let classeurs = [];
let categories = [];
let operations = [];
let sous = "transactions";
let charge = false;
const selection = new Set(); // transactions cochées pour le classement groupé
let derniereCochee = null;   // pour Maj + clic

const mandatId = () => Number(choixMandat.value) || null;
const classeMontant = (v) => (v < 0 ? "num negatif" : v > 0 ? "num positif" : "num");
const enCentimes = (v) => Math.round(Number(v) * 100);

// listes « Dossier » puis « Étiquette » (classeurs du dossier choisi)
function optionsCategories(select, valeur = "", premier = "Choisir…") {
  const cats = [...new Map(classeurs.map((c) => [c.categorie_id, c.categorie_nom]))];
  select.replaceChildren(el("option", { value: "" }, premier),
    ...cats.map(([cid, nom]) => el("option", { value: String(cid) }, nom)));
  select.value = String(valeur || "");
}

function optionsClasseurs(select, categorieId, valeur = "", sansDossier = "Choisir d'abord le dossier") {
  const liste = classeurs.filter((c) => c.categorie_id === Number(categorieId));
  select.replaceChildren(el("option", { value: "" }, categorieId ? "Choisir…" : sansDossier),
    ...liste.map((c) => el("option", { value: String(c.id) }, c.nom)));
  select.disabled = !categorieId;
  select.value = String(valeur || "");
}

const categorieDe = (classeurId) => classeurs.find((c) => c.id === Number(classeurId))?.categorie_id ?? "";

function message(texte, type = "") {
  const m = $("#treso-message");
  m.textContent = texte;
  m.className = `statut ${type}`;
}

surOnglet("treso", () => {
  if (!charge) {
    charge = true;
    demarrer();
  }
});

// ---------------------------------------------------------------- mandats et sous-onglets

async function demarrer() {
  try {
    [mandats, categories] = await Promise.all([api("api/treso/mandats"), api("api/treso/categories")]);
  } catch (e) {
    charge = false;
    message(`Trésorerie indisponible : ${e.message}`, "ko");
    return;
  }
  let retenu = null;
  try { retenu = Number(localStorage.getItem("treso-mandat")); } catch { /* stockage du navigateur bloqué */ }
  afficherMandats(mandats.some((m) => m.id === retenu) ? retenu : mandats[0]?.id);
  $("#treso-form-classeur").categorie_id.replaceChildren(el("option", { value: "" }, "Choisir…"),
    ...categories.map((c) => el("option", { value: String(c.id) }, c.nom)));
  await changerMandat();
}

function afficherMandats(choisi) {
  choixMandat.replaceChildren(...mandats.map((m) => el("option", { value: String(m.id) }, m.nom)));
  if (choisi) choixMandat.value = String(choisi);
}

async function changerMandat() {
  try { localStorage.setItem("treso-mandat", choixMandat.value); } catch { /* sans importance */ }
  try {
    classeurs = mandatId() ? await api(`api/treso/classeurs?mandat=${mandatId()}`) : [];
  } catch (e) {
    message(e.message, "ko");
  }
  rafraichir();
}

choixMandat.addEventListener("change", changerMandat);

function rafraichir() {
  if (!mandatId()) {
    message("Aucun mandat : créez-en un dans « Mandats et classeurs ».");
    return afficherSous("reglages");
  }
  if (sous === "transactions") chargerOperations();
  else if (sous === "cr") chargerCompteResultat();
  else afficherClasseurs();
}

function afficherSous(nom) {
  sous = nom;
  vue.querySelectorAll(".sous-onglets [data-sous]").forEach((b) =>
    b.setAttribute("aria-selected", String(b.dataset.sous === nom)));
  vue.querySelectorAll("[data-sous-vue]").forEach((s) => { s.hidden = s.dataset.sousVue !== nom; });
}

vue.querySelectorAll(".sous-onglets [data-sous]").forEach((b) => b.addEventListener("click", () => {
  message("");
  afficherSous(b.dataset.sous);
  rafraichir();
}));

const nomClasseur = (id) => {
  const c = classeurs.find((k) => k.id === id);
  return c ? `${c.categorie_nom} › ${c.nom}` : "";
};

function lienJustificatif(j) {
  const prefixe = j.lien_type === "ndf" ? "NDF · " : j.lien_type === "facture" ? "Facture · " : "";
  return el("a", { href: `api/treso/justificatifs/${j.id}`, target: "_blank", rel: "noopener" }, prefixe + j.nom);
}

// ---------------------------------------------------------------- transactions

async function chargerOperations() {
  const params = new URLSearchParams({ mandat: mandatId(), mois: $("#treso-mois").value,
    a_classer: $("#treso-a-classer").checked ? "1" : "" });
  try {
    operations = await api(`api/treso/operations?${params}`);
  } catch (e) {
    $("#treso-vide").textContent = `Liste indisponible : ${e.message}`;
    return;
  }
  const total = operations.reduce((s, o) => s + o.montant, 0);
  $("#treso-resume").textContent = `${operations.length} ligne${operations.length > 1 ? "s" : ""} · total ${eur.format(total)}`;
  const visibles = new Set(operations.map((o) => o.id));
  [...selection].forEach((id) => { if (!visibles.has(id)) selection.delete(id); });
  $("#treso-operations").replaceChildren(...operations.map(ligneOperation));
  $("#treso-vide").hidden = operations.length > 0;
  $("#treso-vide").textContent = "Aucune transaction : importez le relevé CSV du mois.";
  majSelection();
}

const classee = (o) => o.classeur_id || o.ventilations.length;

function ligneOperation(o, index) {
  const repartition = o.ventilations.length
    ? `Répartie : ${o.ventilations.map((p) => `${classeurs.find((c) => c.id === p.classeur_id)?.nom ?? "?"} ${eur.format(p.montant)}`).join(" · ")}`
    : null;
  const details = [o.classeur_id ? nomClasseur(o.classeur_id) : repartition,
    o.justificatifs.length ? `${o.justificatifs.length} justificatif${o.justificatifs.length > 1 ? "s" : ""}` : null,
    o.commentaire ? `Note : ${o.commentaire}` : null].filter(Boolean).join(" · ");
  const case_ = el("input", { type: "checkbox", "aria-label": `Cocher la transaction du ${dateFr(o.date)}` });
  case_.checked = selection.has(o.id);
  case_.addEventListener("click", (e) => cocher(o.id, index, case_.checked, e.shiftKey));
  return el("tr", { class: classee(o) ? "" : "a-classer", "data-id": String(o.id) },
    el("td", { class: "case-ligne" }, case_),
    el("td", { class: "num" }, dateFr(o.date)),
    el("td", { class: "sub" }, o.nature),
    el("td", {}, el("span", { class: "desig" }, o.libelle),
      el("div", { class: "sub" }, classee(o) ? "" : el("span", { class: "pastille st-attente" }, "À classer"),
        classee(o) ? details : details ? ` ${details}` : "")),
    el("td", { class: classeMontant(o.montant) }, eur.format(o.montant)),
    el("td", { class: "actions" }, lien("Modifier", () => ouvrirOperation(o.id)),
      lien("Supprimer", () => supprimerOperation(o))));
}

// ---------------------------------------------------------------- classement groupé

function cocher(id, index, coche, plage) {
  // Maj + clic : coche (ou décoche) toutes les lignes entre la précédente et celle-ci
  const indices = plage && derniereCochee !== null
    ? Array.from({ length: Math.abs(index - derniereCochee) + 1 }, (_, k) => Math.min(index, derniereCochee) + k)
    : [index];
  indices.forEach((i) => { if (coche) selection.add(operations[i].id); else selection.delete(operations[i].id); });
  derniereCochee = index;
  majSelection();
}

function majSelection() {
  document.querySelectorAll("#treso-operations tr").forEach((tr) => {
    const coche = selection.has(Number(tr.dataset.id));
    tr.classList.toggle("cochee", coche);
    tr.querySelector("input[type=checkbox]").checked = coche;
  });
  const tout = $("#treso-tout");
  tout.checked = operations.length > 0 && selection.size === operations.length;
  tout.indeterminate = selection.size > 0 && selection.size < operations.length;
  const barre = $("#treso-groupe");
  const etaitCachee = barre.hidden;
  barre.hidden = selection.size === 0;
  $("#treso-groupe-nb").textContent = `${selection.size} transaction${selection.size > 1 ? "s" : ""} cochée${selection.size > 1 ? "s" : ""}`;
  if (etaitCachee && !barre.hidden) {
    optionsCategories($("#treso-groupe-categorie"), "", "Dossier…");
    optionsClasseursGroupe();
  }
}

function optionsClasseursGroupe() {
  const select = $("#treso-groupe-classeur");
  optionsClasseurs(select, $("#treso-groupe-categorie").value, "", "Étiquette…");
  select.disabled = false;  // « À classer » reste possible sans dossier
  select.append(el("option", { value: "aucun" }, "À classer (retirer le classement)"));
}

$("#treso-tout").addEventListener("change", (e) => {
  operations.forEach((o) => { if (e.target.checked) selection.add(o.id); else selection.delete(o.id); });
  derniereCochee = null;
  majSelection();
});
$("#treso-groupe-categorie").addEventListener("change", optionsClasseursGroupe);
$("#treso-groupe-annuler").addEventListener("click", () => {
  selection.clear();
  majSelection();
});

$("#treso-groupe-classer").addEventListener("click", async () => {
  const choix = $("#treso-groupe-classeur").value;
  if (!choix) {
    message("Choisissez le dossier et l'étiquette où classer les transactions cochées.", "ko");
    return;
  }
  try {
    const r = await postJSON("api/treso/operations/classer", {
      ids: [...selection], classeur_id: choix === "aucun" ? null : Number(choix),
    });
    const ou = choix === "aucun" ? "remises à classer" : `classées dans ${nomClasseur(Number(choix))}`;
    message(`${r.classees} transaction${r.classees > 1 ? "s" : ""} ${ou}.`
      + (r.reparties_ignorees ? ` ${r.reparties_ignorees} transaction${r.reparties_ignorees > 1 ? "s" : ""} répartie${r.reparties_ignorees > 1 ? "s" : ""} sur plusieurs classeurs n'${r.reparties_ignorees > 1 ? "ont" : "a"} pas été modifiée${r.reparties_ignorees > 1 ? "s" : ""}.` : ""), "ok");
    selection.clear();
    chargerOperations();
  } catch (e) {
    message(e.message, "ko");
  }
});

$("#treso-mois").addEventListener("change", chargerOperations);
$("#treso-a-classer").addEventListener("change", chargerOperations);

$("#treso-import").addEventListener("change", async (e) => {
  const fichier = e.target.files[0];
  e.target.value = "";
  if (!fichier || !mandatId()) return;
  const fd = new FormData();
  fd.append("mandat", mandatId());
  fd.append("fichier", fichier, fichier.name);
  message(`Import de ${fichier.name}…`);
  try {
    const r = await api("api/treso/operations/import", { method: "POST", body: fd });
    const hors = r.hors_mandat ? ` Attention : ${r.hors_mandat} ligne${r.hors_mandat > 1 ? "s" : ""} hors des dates du mandat.` : "";
    message(`${r.ajoutees} transaction${r.ajoutees > 1 ? "s" : ""} ajoutée${r.ajoutees > 1 ? "s" : ""}, ${r.doublons} doublon${r.doublons > 1 ? "s" : ""} ignoré${r.doublons > 1 ? "s" : ""}.${hors}`, hors ? "" : "ok");
    chargerOperations();
  } catch (err) {
    message(`Import impossible : ${err.message}`, "ko");
  }
});

async function supprimerOperation(o) {
  if (!confirm(`Supprimer cette transaction et ses justificatifs ?\n${dateFr(o.date)} — ${o.libelle} — ${eur.format(o.montant)}`)) return;
  try {
    await api(`api/treso/operations/${o.id}`, { method: "DELETE" });
    message("Transaction supprimée.", "ok");
    chargerOperations();
  } catch (e) {
    message(e.message, "ko");
  }
}

// ---------------------------------------------------------------- fenêtre « Modifier la transaction »

const dlg = $("#dlg-operation");
const form = $("#form-operation");
const q = (k) => form.querySelector(`[data-f="${k}"]`);
let courante = null;
let parts = null; // null = un seul classeur ; sinon [{categorie, classeur_id, montant, commentaire}]

function remplirClasseurs(categorieId, classeurId = "") {
  optionsClasseurs(form.classeur_id, categorieId, classeurId);
}

// ---------------------------------------------------------------- répartition sur plusieurs classeurs

function modeRepartition(actif) {
  form.querySelectorAll("[data-mode=simple]").forEach((e) => { e.hidden = actif; });
  form.querySelector("[data-mode=repartition]").hidden = !actif;
}

function resteCentimes() {
  return enCentimes(courante.montant) - parts.reduce((s, p) => s + enCentimes(nombreSaisi(p.montant)), 0);
}

function majReste() {
  const reste = resteCentimes();
  const cellule = q("reste");
  cellule.textContent = reste ? `Reste à répartir : ${eur.format(reste / 100)}` : "Tout est réparti";
  cellule.className = `num ${reste ? "negatif" : "positif"}`;
}

function afficherParts() {
  q("parts").replaceChildren(...parts.map((p, i) => {
    const dossier = el("select", { "aria-label": `Part ${i + 1} : dossier` });
    const etiquette = el("select", { "aria-label": `Part ${i + 1} : étiquette` });
    optionsCategories(dossier, p.categorie);
    optionsClasseurs(etiquette, p.categorie, p.classeur_id, "Dossier d'abord");
    dossier.addEventListener("change", () => {
      p.categorie = dossier.value;
      p.classeur_id = "";
      optionsClasseurs(etiquette, p.categorie, "", "Dossier d'abord");
    });
    etiquette.addEventListener("change", () => { p.classeur_id = etiquette.value; });
    const montant = el("input", { type: "number", step: "0.01", inputmode: "decimal", class: "montant",
      "aria-label": `Part ${i + 1} : montant` });
    montant.value = p.montant;
    montant.addEventListener("input", () => { p.montant = montant.value; majReste(); });
    const note = el("input", { maxlength: "200", placeholder: "ex. billetterie du gala", "aria-label": `Part ${i + 1} : note` });
    note.value = p.commentaire;
    note.addEventListener("input", () => { p.commentaire = note.value; });
    const retirer = el("button", { class: "reset", type: "button", title: "Retirer cette part", "aria-label": "Retirer la part" }, "×");
    retirer.addEventListener("click", () => { parts.splice(i, 1); afficherParts(); });
    return el("tr", {}, el("td", {}, dossier), el("td", {}, etiquette), el("td", { class: "num" }, montant),
      el("td", {}, note), el("td", {}, parts.length > 2 ? retirer : ""));
  }));
  majReste();
}

const partVide = () => ({ categorie: "", classeur_id: "", montant: "", commentaire: "" });

q("repartir").addEventListener("click", () => {
  // la première part reprend le classeur déjà choisi ; les montants sont à saisir
  const cl = form.classeur_id.value;
  parts = [{ ...partVide(), categorie: categorieDe(cl), classeur_id: cl }, partVide()];
  modeRepartition(true);
  afficherParts();
});
q("ajouter-part").addEventListener("click", () => { parts.push(partVide()); afficherParts(); });
q("completer").addEventListener("click", () => {
  const derniere = parts.at(-1);
  derniere.montant = ((enCentimes(nombreSaisi(derniere.montant)) + resteCentimes()) / 100).toFixed(2);
  afficherParts();
});
q("un-seul").addEventListener("click", () => {
  const premiere = parts?.find((p) => p.classeur_id);
  parts = null;
  modeRepartition(false);
  form.categorie.value = String(categorieDe(premiere?.classeur_id) || "");
  remplirClasseurs(form.categorie.value, premiere?.classeur_id);
});

function afficherJustificatifs() {
  q("justificatifs").replaceChildren(...(courante.justificatifs.length ? courante.justificatifs.map((j) => {
    const retirer = el("button", { class: "reset", type: "button", title: "Retirer ce justificatif", "aria-label": "Retirer" }, "×");
    retirer.addEventListener("click", async () => {
      if (!confirm(`Retirer « ${j.nom} » de cette transaction ?`)) return;
      try {
        await api(`api/treso/justificatifs/${j.id}`, { method: "DELETE" });
        await recharger();
      } catch (e) {
        q("erreur").textContent = e.message;
      }
    });
    return el("li", {}, lienJustificatif(j), retirer);
  }) : [el("li", { class: "sub" }, "Aucun justificatif.")]));
}

async function chargerDocuments() {
  const choix = q("document");
  choix.replaceChildren(el("option", { value: "" }, "Chargement…"));
  try {
    const d = await api(`api/treso/operations/${courante.id}/documents`);
    const option = (doc) => el("option", { value: `${doc.type}:${doc.id}`, ...(doc.joint ? { disabled: "" } : {}) },
      `${dateFr(doc.date)} · ${doc.titre} · ${eur.format(doc.montant)} (${STATUTS_DOC[doc.statut] || doc.statut})${doc.joint ? " · déjà jointe" : ""}`);
    // même montant en tête, puis le reste (notes de frais d'abord pour un débit, factures pour un crédit)
    const memes = [...d.ndf, ...d.factures].filter((doc) => doc.identique);
    const groupes = [["Notes de frais", d.ndf.filter((doc) => !doc.identique)],
      ["Factures", d.factures.filter((doc) => !doc.identique)]];
    if (!d.debit) groupes.reverse();
    choix.replaceChildren(el("option", { value: "" }, "Joindre une note de frais ou une facture…"),
      ...(memes.length ? [el("optgroup", { label: "Même montant" }, ...memes.map(option))] : []),
      ...groupes.filter(([, docs]) => docs.length).map(([titre, docs]) => el("optgroup", { label: titre }, ...docs.map(option))));
    if (memes.length === 1 && !memes[0].joint) choix.value = `${memes[0].type}:${memes[0].id}`;
  } catch (e) {
    choix.replaceChildren(el("option", { value: "" }, "Documents indisponibles"));
  }
}

async function recharger() {
  await chargerOperations();
  courante = operations.find((o) => o.id === courante.id) || courante;
  afficherJustificatifs();
  chargerDocuments();
}

function ouvrirOperation(id) {
  const o = operations.find((x) => x.id === id);
  if (!o) return;
  courante = o;
  q("resume").replaceChildren(`${dateFr(o.date)} — ${o.nature || "?"} — `,
    el("strong", { class: o.montant < 0 ? "negatif" : "positif" }, eur.format(o.montant)), el("br"), o.libelle);
  form.libelle.value = o.libelle;
  form.commentaire.value = o.commentaire || "";
  optionsCategories(form.categorie, categorieDe(o.classeur_id));
  remplirClasseurs(categorieDe(o.classeur_id), o.classeur_id);
  parts = o.ventilations.length ? o.ventilations.map((p) => ({
    categorie: categorieDe(p.classeur_id), classeur_id: String(p.classeur_id), montant: p.montant.toFixed(2),
    commentaire: p.commentaire })) : null;
  modeRepartition(Boolean(parts));
  if (parts) afficherParts();
  q("erreur").textContent = "";
  q("aide").textContent = o.montant < 0
    ? "Une note de frais jointe à ce débit passe à « Remboursée »."
    : "Une facture jointe à ce crédit passe à « Payée ».";
  afficherJustificatifs();
  chargerDocuments();
  dlg.showModal();
}

form.categorie.addEventListener("change", () => remplirClasseurs(form.categorie.value));

// Enregistre motif, classement (un classeur ou la répartition) et commentaire (aussi avant d'ajouter
// un justificatif). Une répartition incomplète est refusée avant même d'appeler le serveur.
async function enregistrerOperation() {
  if (parts) {
    if (parts.some((p) => !p.classeur_id)) throw new Error("Choisissez l'étiquette (classeur) de chaque part.");
    if (parts.some((p) => !enCentimes(nombreSaisi(p.montant)))) throw new Error("Chaque part doit avoir un montant.");
    const reste = resteCentimes();
    if (reste) throw new Error(`Les parts ne font pas le total : reste à répartir ${eur.format(reste / 100)}.`);
  }
  await putJSON(`api/treso/operations/${courante.id}`, {
    classeur_id: !parts && form.classeur_id.value ? Number(form.classeur_id.value) : null,
    commentaire: form.commentaire.value, libelle: form.libelle.value,
    ventilations: parts ? parts.map((p) => ({ classeur_id: Number(p.classeur_id), montant: nombreSaisi(p.montant),
      commentaire: p.commentaire })) : null,
  });
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await enregistrerOperation();
    dlg.close();
    message("Transaction enregistrée.", "ok");
    chargerOperations();
  } catch (err) {
    q("erreur").textContent = err.message;
  }
});

q("fichier").addEventListener("change", async (e) => {
  const fichier = e.target.files[0];
  e.target.value = "";
  if (!fichier) return;
  q("erreur").textContent = "";
  try {
    await enregistrerOperation();
    const fd = new FormData();
    fd.append("fichier", fichier, fichier.name);
    const r = await api(`api/treso/operations/${courante.id}/justificatifs`, { method: "POST", body: fd });
    if (r.avertissement) q("erreur").textContent = r.avertissement;
    await recharger();
  } catch (err) {
    q("erreur").textContent = err.message;
  }
});

q("joindre").addEventListener("click", async () => {
  const [type, id] = q("document").value.split(":");
  if (!type) return;
  q("erreur").textContent = "";
  try {
    await enregistrerOperation();
    const r = await postJSON(`api/treso/operations/${courante.id}/liens`, { type, id: Number(id) });
    const quoi = type === "ndf" ? "La note de frais" : "La facture";
    q("aide").textContent = r.statut ? `${quoi} est jointe et passe à « ${r.statut} ».` : `${quoi} est jointe.`;
    if (r.avertissement) q("erreur").textContent = r.avertissement;
    await recharger();
  } catch (err) {
    q("erreur").textContent = err.message;
  }
});

// ---------------------------------------------------------------- compte de résultat

async function chargerCompteResultat() {
  vue.querySelector("[data-f=cr-vue]").hidden = false;
  vue.querySelector("[data-f=detail-vue]").hidden = true;
  const base = `api/treso/compte-resultat/export?mandat=${mandatId()}&format=`;
  $("#treso-export-pdf").href = `${base}pdf`;
  $("#treso-export-xlsx").href = `${base}xlsx`;
  $("#treso-export-csv").href = `${base}csv`;
  let cr;
  try {
    cr = await api(`api/treso/compte-resultat?mandat=${mandatId()}`);
  } catch (e) {
    message(e.message, "ko");
    return;
  }
  const ligne = (nom, m, classe = "", action = null) => {
    const tr = el("tr", { class: classe },
      el("td", {}, nom),
      ...["charges", "produits", "balance"].map((k) => el("td", { class: classeMontant(m[k]) }, eur.format(m[k]))));
    if (action) {
      tr.classList.add("cliquable");
      tr.tabIndex = 0;
      tr.addEventListener("click", action);
      tr.addEventListener("keydown", (e) => { if (e.key === "Enter") action(); });
    }
    return tr;
  };
  const bloc = (hors) => cr.categories.filter((c) => c.hors_cr === hors).flatMap((c) => [
    ligne(c.nom, c, "cr-categorie"),
    ...c.classeurs.map((k) => ligne(k.nom, k, "cr-classeur", () => afficherDetail(k, c.nom))),
  ]);
  const nc = cr.non_classe;
  $("#treso-cr").replaceChildren(
    ...bloc(false), ligne("SOUS-TOTAUX", cr.total_cr, "cr-total"),
    ...bloc(true), ...(cr.categories.some((c) => c.hors_cr) ? [ligne("RESTE HORS CR", cr.total_hors_cr, "cr-total")] : []),
    ligne(`Non classé (${nc.nb} ligne${nc.nb > 1 ? "s" : ""})`, nc, "cr-non-classe"));
  $("#treso-controle").replaceChildren(`Solde total du relevé : ${eur.format(cr.solde_releve)} — contrôle : `,
    cr.ecart ? el("strong", { class: "negatif" }, `écart de ${eur.format(cr.ecart)}`) : "tout concorde");
}

async function afficherDetail(classeur, categorie) {
  vue.querySelector("[data-f=cr-vue]").hidden = true;
  vue.querySelector("[data-f=detail-vue]").hidden = false;
  $("#treso-detail-titre").textContent = `${categorie} › ${classeur.nom}`;
  $("#treso-detail").replaceChildren();
  try {
    const ops = await api(`api/treso/operations?mandat=${mandatId()}&classeur=${classeur.id}`);
    // montants qui reviennent à ce classeur : la transaction entière, ou ses parts dans ce classeur
    const montants = ops.flatMap((o) => (o.classeur_id === classeur.id ? [o.montant]
      : o.ventilations.filter((p) => p.classeur_id === classeur.id).map((p) => p.montant)));
    const charges = montants.filter((m) => m < 0).reduce((s, m) => s + m, 0);
    const produits = montants.filter((m) => m > 0).reduce((s, m) => s + m, 0);
    $("#treso-detail-resume").textContent = `${ops.length} transaction${ops.length > 1 ? "s" : ""} — charges ${eur.format(charges)} — produits ${eur.format(produits)} — balance ${eur.format(charges + produits)}`;
    $("#treso-detail").replaceChildren(...(ops.length ? ops.map((o) => {
      const notes = o.ventilations.filter((p) => p.classeur_id === classeur.id && p.commentaire).map((p) => p.commentaire);
      return el("tr", {},
        el("td", { class: "num" }, dateFr(o.date)), el("td", { class: "sub" }, o.nature), el("td", {}, o.libelle),
        el("td", { class: classeMontant(o.montant_classeur) }, eur.format(o.montant_classeur),
          o.classeur_id === classeur.id ? "" : el("div", { class: "sub" }, `part de ${eur.format(o.montant)}`)),
        el("td", { class: "sub" }, [o.commentaire, ...notes].filter(Boolean).join(" · ")),
        el("td", { class: "justifs-liste" }, ...o.justificatifs.map(lienJustificatif)));
    }) : [el("tr", {}, el("td", { colspan: "6", class: "sub" }, "Aucune transaction dans ce classeur."))]));
  } catch (e) {
    message(e.message, "ko");
  }
}

$("#treso-retour").addEventListener("click", chargerCompteResultat);

// ---------------------------------------------------------------- mandats et classeurs

function afficherClasseurs() {
  const m = mandats.find((x) => x.id === mandatId());
  $("#treso-classeurs-titre").textContent = m ? `Classeurs du mandat ${m.nom} (du ${dateFr(m.debut)} au ${dateFr(m.fin)})` : "Classeurs";
  const parCategorie = new Map();
  classeurs.forEach((c) => {
    if (!parCategorie.has(c.categorie_nom)) parCategorie.set(c.categorie_nom, []);
    parCategorie.get(c.categorie_nom).push(c);
  });
  $("#treso-classeurs").replaceChildren(...(classeurs.length ? [...parCategorie].map(([categorie, liste]) =>
    el("div", { class: "classeurs-groupe" }, el("h4", {}, categorie),
      el("ul", {}, ...liste.map((c) => el("li", {}, el("span", {}, c.nom),
        el("span", { class: "sub" }, c.nb ? `${c.nb} transaction${c.nb > 1 ? "s" : ""}` : "vide"),
        c.nb ? "" : lien("supprimer", () => supprimerClasseur(c)))))))
    : [el("p", { class: "sub" }, "Aucun classeur dans ce mandat.")]));
}

async function supprimerClasseur(c) {
  if (!confirm(`Supprimer le classeur « ${c.nom} » ?`)) return;
  try {
    await api(`api/treso/classeurs/${c.id}`, { method: "DELETE" });
    await changerMandat();
  } catch (e) {
    message(e.message, "ko");
  }
}

$("#treso-form-mandat").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.currentTarget;
  if (!f.reportValidity()) return;
  try {
    const r = await postJSON("api/treso/mandats", {
      nom: f.nom.value, debut: f.debut.value, fin: f.fin.value, copier_de: f.copier.checked ? mandatId() : null,
    });
    mandats = await api("api/treso/mandats");
    afficherMandats(r.id);
    f.reset();
    f.copier.checked = true;
    message("Mandat créé.", "ok");
    await changerMandat();
  } catch (err) {
    message(err.message, "ko");
  }
});

$("#treso-form-classeur").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.currentTarget;
  if (!f.reportValidity()) return;
  try {
    await postJSON("api/treso/classeurs", {
      mandat_id: mandatId(), categorie_id: Number(f.categorie_id.value), nom: f.nom.value,
    });
    f.nom.value = "";
    message("Classeur ajouté.", "ok");
    await changerMandat();
  } catch (err) {
    message(err.message, "ko");
  }
});

// une erreur inattendue ne doit pas passer inaperçue
window.addEventListener("unhandledrejection", (e) => {
  if (!vue.hidden) alerte(`Trésorerie : ${e.reason?.message || e.reason}`);
});
