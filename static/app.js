"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const eur = new Intl.NumberFormat("fr-FR", { style: "currency", currency: "EUR" });
const eur3 = new Intl.NumberFormat("fr-FR", {
  style: "currency", currency: "EUR", minimumFractionDigits: 3, maximumFractionDigits: 3,
});
const nombre = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 3 });
const pct = (v) => (v == null ? "?" : `${nombre.format(v)} %`);

// Préférences locales au navigateur (marge, arrondi, pièces et articles non vendus)
const store = {
  get(cle, defaut) {
    try {
      const v = localStorage.getItem(cle);
      return v === null ? defaut : JSON.parse(v);
    } catch { return defaut; }
  },
  set(cle, valeur) {
    try { localStorage.setItem(cle, JSON.stringify(valeur)); } catch { /* stockage indisponible */ }
  },
  remove(cle) {
    try { localStorage.removeItem(cle); } catch { /* stockage indisponible */ }
  },
};

// Catégorie de dépense de chaque ligne (mêmes clés que recap_pdf.CATEGORIES côté serveur).
// Seules les lignes VENTE ont un prix de vente ; un PDF est créé pour chaque catégorie utilisée.
const CATEGORIES = {
  vente: "Vente",
  event: "Event",
  local: "Local",
  cadeau: "Cadeau conducteur",
  hors: "Hors catégorie",
};

const state = { config: null, factures: [] };

async function api(url, options = {}) {
  const resp = await fetch(url, options);
  let data = null;
  try { data = await resp.json(); } catch { /* réponse non JSON */ }
  if (!resp.ok) throw new Error(data?.erreur || `Erreur HTTP ${resp.status}`);
  return data;
}

const postJSON = (url, body) => api(url, {
  method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
});

// ---------------------------------------------------------------- calculs

const margeInput = $("#marge");
const margeType = $("#marge-type");
const arrondiSel = $("#arrondi");
const taxeInput = $("#taxe");

const lireNombre = (input) => Math.max(0, parseFloat(String(input.value).replace(",", ".")) || 0);

function reglages() {
  return {
    marge: lireNombre(margeInput),
    type: margeType.value,
    taxe: lireNombre(taxeInput),
    pas: parseFloat(arrondiSel.value) || 0,
  };
}

// Prix optimal = coût TTC + marge + taxe TPE (la marge ne s'applique pas sur la taxe), arrondi
function prixOptimal(coutTTC, r) {
  let pv = (r.type === "pct" ? coutTTC * (1 + r.marge / 100) : coutTTC + r.marge) + r.taxe;
  if (r.pas > 0) pv = Math.ceil(pv / r.pas - 1e-9) * r.pas;
  return Math.round(pv * 100) / 100;
}

// Une ligne hors VENTE n'a pas de prix de vente : elle coûte sans rapporter.
// `prixChoisi` : prix saisi par l'utilisateur, ou null pour vendre au prix optimal.
function calcLigne(ligne, pieces, vendu, prixChoisi, r) {
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

function recalc(f) {
  const r = reglages();
  const parCat = Object.fromEntries(Object.keys(CATEGORIES).map((k) => [k, { n: 0, ttc: 0 }]));
  let total = 0;
  let taxes = 0;
  let ca = 0;
  f.data.lignes.forEach((ligne, i) => {
    const cat = f.categories[i];
    const vendu = cat === "vente";
    const c = calcLigne(ligne, f.pieces[i], vendu, f.prix[i], r);
    const cells = f.rows[i];
    cells.tr.className = vendu ? "" : `hors-vente cat-${cat}`;
    cells.categorie.value = cat;
    cells.coutHT.textContent = eur3.format(c.coutHT);
    cells.coutTTC.textContent = eur3.format(c.coutTTC);
    cells.optimal.textContent = vendu ? eur.format(c.optimal) : "—";
    afficherPrix(cells, vendu, f.prix[i], c);
    cells.totalTTC.textContent = eur.format(c.totalTTC);
    total += c.totalTTC;
    taxes += c.taxes;
    ca += c.ca;
    parCat[cat].n += 1;
    parCat[cat].ttc += c.totalTTC;
  });
  f.q("total-ttc").textContent = eur.format(total);
  for (const [cat, { n, ttc }] of Object.entries(parCat)) {
    const ligne = f.lignesCat[cat];
    ligne.tr.hidden = n === 0;
    ligne.n.textContent = `${n} ligne${n > 1 ? "s" : ""}`;
    ligne.montant.textContent = eur.format(ttc);
  }
  f.q("ca").textContent = eur.format(ca);
  f.q("taxes").textContent = eur.format(taxes);

  // les cadeaux conducteur sont une perte sur le bénéfice de la course
  const benefice = ca - parCat.vente.ttc - taxes;
  const cadeau = parCat.cadeau.ttc;
  const net = benefice - cadeau;
  f.q("benefice").textContent = eur.format(benefice);
  f.q("cadeau").textContent = eur.format(-cadeau);
  f.q("benefice-net").textContent = eur.format(net);
  f.q("benefice").parentElement.classList.toggle("benefice", !cadeau);
  f.q("benefice").classList.toggle("negatif", benefice < 0);
  f.q("benefice-net").classList.toggle("negatif", net < 0);
  f.q("cadeau").parentElement.hidden = !cadeau;
  f.q("benefice-net").parentElement.hidden = !cadeau;
}

function recalcAll() {
  store.set("marge", margeInput.value);
  store.set("margeType", margeType.value);
  store.set("arrondi", arrondiSel.value);
  store.set("taxe", taxeInput.value);
  state.factures.forEach(recalc);
  majResumeGlobal();
}

margeInput.value = store.get("marge", "20");
margeType.value = store.get("margeType", "pct");
arrondiSel.value = store.get("arrondi", "0");
taxeInput.value = store.get("taxe", "");
[margeInput, margeType, taxeInput, arrondiSel].forEach((el) => el.addEventListener("input", recalcAll));

// ---------------------------------------------------------------- factures

function el(tag, attrs = {}, ...enfants) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else node.setAttribute(k, v);
  }
  node.append(...enfants.filter((e) => e != null && e !== false));
  return node;
}

// Pièces par unité : mémorisé par article et appliqué à toutes les factures ouvertes
function champPieces(f, i, ligne) {
  const input = el("input", {
    type: "number", min: "1", step: "1", value: String(f.pieces[i]), class: "pieces",
    "aria-label": `Pièces par unité pour ${ligne.designation}`,
  });
  input.addEventListener("input", () => {
    const v = Math.max(1, parseInt(input.value, 10) || 1);
    store.set(`pieces:${ligne.article}`, v);
    for (const autre of state.factures) {
      autre.data.lignes.forEach((l, j) => {
        if (l.article !== ligne.article) return;
        autre.pieces[j] = v;
        if (autre.rows[j].pieces !== input) autre.rows[j].pieces.value = String(v);
      });
      recalc(autre);
    }
  });
  return input;
}

// Prix de vente choisi : pré-rempli avec le prix optimal. Une fois modifié, il est mémorisé
// par article et repris sur les autres factures ; vider le champ ou ↺ revient au prix optimal.
function champPrix(f, i, ligne) {
  const input = el("input", {
    type: "number", min: "0", step: "0.01", class: "prix",
    "aria-label": `Prix de vente de ${ligne.designation}`,
  });
  const reset = el("button", {
    type: "button", class: "reset", title: "Revenir au prix optimal",
    "aria-label": `Revenir au prix optimal pour ${ligne.designation}`,
  }, "↺");
  const appliquer = (v) => {
    if (v == null) store.remove(`prix:${ligne.article}`);
    else store.set(`prix:${ligne.article}`, v);
    for (const autre of state.factures) {
      autre.data.lignes.forEach((l, j) => {
        if (l.article === ligne.article) autre.prix[j] = v;
      });
      recalc(autre);
    }
  };
  input.addEventListener("input", () => {
    const v = parseFloat(input.value.replace(",", "."));
    appliquer(input.value.trim() === "" || Number.isNaN(v) ? null : Math.max(0, v));
  });
  input.addEventListener("blur", () => recalc(f)); // champ vidé : on réaffiche le prix optimal
  reset.addEventListener("click", () => appliquer(null));
  return { input, reset };
}

function afficherPrix(cells, vendu, prixChoisi, c) {
  const { input, reset } = cells.prix;
  input.disabled = !vendu;
  input.placeholder = vendu ? c.optimal.toFixed(2) : "—";
  // ne pas réécrire le champ pendant que l'utilisateur tape dedans
  if (document.activeElement !== input) input.value = vendu ? c.pv.toFixed(2) : "";
  input.classList.toggle("modifie", vendu && prixChoisi != null);
  reset.hidden = !vendu || prixChoisi == null;
  cells.prixTd.classList.toggle("perte", c.perte);
  cells.prixTd.title = c.perte ? "Prix inférieur au coût TTC (+ taxe TPE) : vendu à perte" : "";
}

// LOCAL est mémorisé par article et appliqué aux factures ouvertes (produits utilisés
// au local à chaque fois) ; les autres catégories ne concernent que la ligne choisie.
function champCategorie(f, i, ligne) {
  const select = el("select", { class: "categorie", "aria-label": `Catégorie de ${ligne.designation}` },
    ...Object.entries(CATEGORIES).map(([v, libelle]) => el("option", { value: v }, libelle)));
  select.value = f.categories[i];
  select.addEventListener("change", () => {
    const avant = f.categories[i];
    const v = select.value;
    f.categories[i] = v;
    if (v === "local" || avant === "local") {
      if (v === "local") store.set(`local:${ligne.article}`, true);
      else store.remove(`local:${ligne.article}`);
      for (const autre of state.factures) {
        autre.data.lignes.forEach((l, j) => {
          if (l.article !== ligne.article) return;
          if (v === "local" && autre.categories[j] === "vente") autre.categories[j] = "local";
          if (v !== "local" && autre.categories[j] === "local") autre.categories[j] = "vente";
        });
      }
      state.factures.forEach(recalc);
    } else {
      recalc(f);
    }
  });
  return select;
}

// Lignes « par catégorie » sous le total, avec un bouton d'aperçu du PDF de la catégorie
function lignesCategories(f) {
  f.lignesCat = {};
  const rows = Object.entries(CATEGORIES).map(([cat, libelle]) => {
    const n = el("span", { class: "nb" });
    const montant = el("td", { class: "num" });
    // lien ordinaire : l'adresse est calculée au moment du clic (catégories et date à jour)
    const lien = el("a", { class: "lien", href: "#", target: "_blank", rel: "noopener", title: `Voir le PDF ${libelle}` },
      "aperçu PDF");
    lien.addEventListener("click", (e) => {
      if (!/^\d{2}-\d{2}-\d{4}$/.test(f.q("nom").value.trim())) {
        e.preventDefault();
        statut(f, "Date attendue au format JJ-MM-AAAA.", "ko");
        return;
      }
      lien.href = urlApercu(f, cat);
    });
    const tr = el("tr", { class: "ligne-cat" },
      el("td", { colspan: "9" },
        el("span", { class: `pastille cat-${cat}` }, libelle), " ", n, " · ", lien),
      montant);
    f.lignesCat[cat] = { tr, n, montant };
    return tr;
  });
  f.q("total-ttc").parentElement.after(...rows);
}

function renderFacture(f) {
  const node = $("#tpl-facture").content.firstElementChild.cloneNode(true);
  const d = f.data;
  f.el = node;
  f.q = (k) => node.querySelector(`[data-f="${k}"]`);

  f.q("date").textContent = d.date ?? "date inconnue";
  f.q("meta").textContent = [d.numero && `N° ${d.numero}`, d.ticket && `ticket ${d.ticket}`, d.fichier]
    .filter(Boolean).join(" · ");

  const tvaTotale = Object.values(d.tva).reduce((s, t) => s + t.tva, 0);
  f.q("totaux").append(
    el("div", {}, el("span", {}, "Total HT"), el("strong", {}, d.total_ht == null ? "?" : eur.format(d.total_ht))),
    el("div", {}, el("span", {}, "TVA"), el("strong", {}, eur.format(tvaTotale))),
    el("div", { class: "ttc" }, el("span", {}, "Total TTC"), el("strong", {}, d.total_ttc == null ? "?" : eur.format(d.total_ttc))),
  );

  const controle = f.q("controle");
  if (d.controle_ok) {
    controle.classList.add("ok");
    controle.textContent = `✓ ${d.lignes.length} lignes lues — leur somme correspond au récapitulatif TVA de la facture.`;
  } else {
    controle.classList.add("ko");
    const details = d.controles.map((c) => `TVA ${c.code} : facture ${c.attendu_ht ?? "?"} € HT, lignes lues ${c.calcule_ht} € HT`);
    controle.textContent = `⚠ Écart détecté, vérifiez les lignes. ${details.join(" · ")}`;
  }

  f.q("nom").value = d.date ?? "";

  // lignes groupées par rayon, dans l'ordre de la facture
  const tbody = f.q("lignes");
  f.rows = [];
  let rayon = null;
  d.lignes.forEach((ligne, i) => {
    if (ligne.categorie !== rayon) {
      rayon = ligne.categorie;
      tbody.append(el("tr", { class: "cat" }, el("th", { colspan: "10", scope: "rowgroup" }, rayon)));
    }
    const sous = [ligne.ean && `EAN ${ligne.ean}`, `réf. ${ligne.article}`,
      ligne.colisage > 1 && `colis de ${ligne.colisage} × ${nombre.format(ligne.quantite)}`,
      ligne.remise_ht > 0 && `remise −${eur.format(ligne.remise_ht)} HT`].filter(Boolean).join(" · ");

    const cells = {
      pieces: champPieces(f, i, ligne),
      categorie: champCategorie(f, i, ligne),
      coutHT: el("td", { class: "num" }),
      coutTTC: el("td", { class: "num" }),
      optimal: el("td", { class: "num optimal" }),
      prix: champPrix(f, i, ligne),
      totalTTC: el("td", { class: "num" }),
    };
    cells.prixTd = el("td", { class: "num accent" }, cells.prix.reset, cells.prix.input);
    cells.tr = el("tr", {},
      el("td", {},
        el("div", { class: "desig" }, ligne.designation, ligne.promo && el("span", { class: "tag" }, "promo")),
        el("div", { class: "sub" }, sous)),
      el("td", {}, cells.categorie),
      el("td", { class: "num" }, nombre.format(ligne.unites)),
      el("td", { class: "num" }, cells.pieces),
      cells.coutHT,
      el("td", { class: "num" }, pct(ligne.tva_taux)),
      cells.coutTTC,
      cells.optimal,
      cells.prixTd,
      cells.totalTTC,
    );
    tbody.append(cells.tr);
    f.rows.push(cells);
  });

  lignesCategories(f);
  f.q("envoyer").addEventListener("click", () => envoyer(f));
  f.q("csv").addEventListener("click", () => exporterCSV(f));
  f.q("retirer").addEventListener("click", () => retirer(f));
  recalc(f);
  return node;
}

function retirer(f) {
  f.el.remove();
  state.factures = state.factures.filter((x) => x !== f);
  majResumeGlobal();
}

function carteErreur(fichier, message) {
  const btn = el("button", { class: "btn ghost", type: "button" }, "Retirer");
  const carte = el("section", { class: "facture erreur-carte" },
    el("p", {}, el("strong", {}, fichier.name), ` — ${message}`), btn);
  btn.addEventListener("click", () => carte.remove());
  return carte;
}

async function ajouterFichiers(fichiers) {
  const zone = $("#factures");
  for (const fichier of fichiers) {
    if (!/\.pdf$/i.test(fichier.name) && fichier.type !== "application/pdf") {
      zone.prepend(carteErreur(fichier, "ce n'est pas un PDF."));
      continue;
    }
    if (state.factures.some((f) => f.file.name === fichier.name && f.file.size === fichier.size)) continue;

    const attente = el("section", { class: "facture chargement" }, `Analyse de ${fichier.name}…`);
    zone.prepend(attente);
    const fd = new FormData();
    fd.append("fichier", fichier);
    try {
      const data = await api("/api/factures", { method: "POST", body: fd });
      const f = {
        file: fichier,
        data,
        pieces: data.lignes.map((l) => store.get(`pieces:${l.article}`, 1)),
        prix: data.lignes.map((l) => store.get(`prix:${l.article}`, null)),
        categories: data.lignes.map((l) => (store.get(`local:${l.article}`, false) ? "local" : "vente")),
      };
      state.factures.push(f);
      attente.replaceWith(renderFacture(f));
    } catch (e) {
      attente.replaceWith(carteErreur(fichier, e.message));
    }
  }
  majResumeGlobal();
}

function majResumeGlobal() {
  const n = state.factures.length;
  $("#actions-globales").hidden = n < 2;
  const ttc = state.factures.reduce((s, f) => s + (f.data.total_ttc || 0), 0);
  $("#resume-global").textContent = `${n} factures · ${eur.format(ttc)} TTC au total`;
}

// ---------------------------------------------------------------- envoi Nextcloud

function statut(f, texte, type = "") {
  const s = f.q("statut");
  s.textContent = texte;
  s.className = `statut ${type}`;
}

// Facture + nom JJ-MM-AAAA.pdf + catégorie de chaque ligne ; null si la date est invalide
function formulaire(f) {
  const date = f.q("nom").value.trim();
  if (!/^\d{2}-\d{2}-\d{4}$/.test(date)) {
    statut(f, "Date attendue au format JJ-MM-AAAA.", "ko");
    f.q("nom").focus();
    return null;
  }
  const fd = new FormData();
  fd.append("fichier", f.file, f.file.name);
  fd.append("nom", `${date}.pdf`);
  fd.append("categories", JSON.stringify(f.categories));
  return fd;
}

async function envoyer(f) {
  const fd = formulaire(f);
  if (!fd) return false;
  if (!state.config?.configure) {
    ouvrirReglages();
    return false;
  }
  fd.append("dossier", state.config.dossier);
  const bouton = f.q("envoyer");
  bouton.disabled = true;
  statut(f, "Envoi en cours…");
  try {
    const res = await api("/api/nextcloud/envoyer", { method: "POST", body: fd });
    const recaps = res.recaps.map((r) => r.nom.split(" - ").pop().replace(/\.pdf$/, ""));
    statut(f, [
      res.deja_present ? `Facture déjà présente : ${res.chemin}` : `✓ Envoyé : ${res.chemin}`,
      `PDF par catégorie : ${recaps.join(", ")}`,
      res.supprimes.length && `anciens PDF supprimés : ${res.supprimes.join(", ")}`,
    ].filter(Boolean).join(" · "), "ok");
    return true;
  } catch (e) {
    statut(f, e.message, "ko");
    return false;
  } finally {
    bouton.disabled = false;
  }
}

// Adresse du PDF d'une catégorie, tel qu'il sera envoyé (le serveur garde la facture analysée)
function urlApercu(f, cat) {
  const params = new URLSearchParams({ nom: `${f.q("nom").value.trim()}.pdf`, categories: f.categories.join(",") });
  return `/api/recap/${f.data.id}/${cat}?${params}`;
}

$("#btn-tout-envoyer").addEventListener("click", async () => {
  if (!state.config?.configure) return ouvrirReglages();
  for (const f of state.factures) await envoyer(f);
});

// ---------------------------------------------------------------- export CSV

function exporterCSV(f) {
  const r = reglages();
  const n = (v, dec = 2) => v.toFixed(dec).replace(".", ",");
  const cell = (v) => (/[;"\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : String(v));
  const lignes = [["Rayon", "EAN", "Réf. METRO", "Désignation", "Catégorie", "Pièces", "Coût HT / pièce",
    "TVA %", "Coût TTC / pièce", "Taxe TPE / pièce", "Prix de vente optimal", "Prix de vente", "Total TTC ligne"]];
  f.data.lignes.forEach((l, i) => {
    const vendu = f.categories[i] === "vente";
    const c = calcLigne(l, f.pieces[i], vendu, f.prix[i], r);
    lignes.push([l.categorie, l.ean, l.article, l.designation, CATEGORIES[f.categories[i]], n(c.nb, 0),
      n(c.coutHT, 3), l.tva_taux == null ? "" : n(l.tva_taux, 1), n(c.coutTTC, 3),
      vendu ? n(r.taxe) : "", vendu ? n(c.optimal) : "", vendu ? n(c.pv) : "", n(c.totalTTC)]);
  });
  const csv = "﻿" + lignes.map((l) => l.map(cell).join(";")).join("\r\n");
  const a = el("a", {
    href: URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" })),
    download: `${f.q("nom").value || "facture"}-prix.csv`,
  });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

// ---------------------------------------------------------------- dépôt de fichiers

const dropzone = $("#dropzone");
const inputFichiers = $("#fichiers");
inputFichiers.addEventListener("change", () => {
  ajouterFichiers([...inputFichiers.files]);
  inputFichiers.value = "";
});
["dragenter", "dragover"].forEach((t) => dropzone.addEventListener(t, (e) => {
  e.preventDefault();
  dropzone.classList.add("survol");
}));
["dragleave", "drop"].forEach((t) => dropzone.addEventListener(t, () => dropzone.classList.remove("survol")));
dropzone.addEventListener("drop", (e) => {
  e.preventDefault();
  ajouterFichiers([...e.dataTransfer.files]);
});
// évite que le navigateur ouvre le PDF si on le lâche à côté de la zone
window.addEventListener("dragover", (e) => e.preventDefault());
window.addEventListener("drop", (e) => {
  e.preventDefault();
  if (e.dataTransfer?.files?.length) ajouterFichiers([...e.dataTransfer.files]);
});

// ---------------------------------------------------------------- réglages Nextcloud

document.querySelectorAll("dialog [data-close]").forEach((b) =>
  b.addEventListener("click", () => b.closest("dialog").close()));

function majDossier() {
  const c = state.config;
  $("#dossier-courant").textContent = c?.configure ? `/${c.dossier}` : "Configurer Nextcloud…";
}

const dlgReglages = $("#dlg-reglages");
const formReglages = $("#form-reglages");

function ouvrirReglages() {
  const c = state.config || {};
  formReglages.nextcloud_url.value = c.nextcloud_url || "";
  formReglages.nextcloud_login.value = c.nextcloud_login || "";
  formReglages.nextcloud_password.value = "";
  formReglages.nextcloud_password.placeholder = c.has_password ? "•••••••• (inchangé)" : "";
  formReglages.nextcloud_password.required = !c.has_password;
  $("[data-f=erreur]", formReglages).textContent = "";
  dlgReglages.showModal();
}

formReglages.addEventListener("submit", async (e) => {
  e.preventDefault();
  const bouton = formReglages.querySelector("button[type=submit]");
  const erreur = $("[data-f=erreur]", formReglages);
  bouton.disabled = true;
  erreur.textContent = "Connexion à Nextcloud…";
  try {
    state.config = await postJSON("/api/config", {
      nextcloud_url: formReglages.nextcloud_url.value,
      nextcloud_login: formReglages.nextcloud_login.value,
      nextcloud_password: formReglages.nextcloud_password.value,
    });
    majDossier();
    dlgReglages.close();
  } catch (err) {
    erreur.textContent = err.message;
  } finally {
    bouton.disabled = false;
  }
});

$("#btn-reglages").addEventListener("click", ouvrirReglages);

// ---------------------------------------------------------------- choix du dossier

const dlgDossier = $("#dlg-dossier");
const dq = (k) => dlgDossier.querySelector(`[data-f="${k}"]`);
let cheminCourant = "";

const joindre = (...parts) => parts.filter(Boolean).join("/");
const parent = (chemin) => chemin.split("/").slice(0, -1).join("/");

async function chargerDossier(chemin) {
  const liste = dq("liste");
  liste.replaceChildren(el("li", { class: "vide" }, "Chargement…"));
  dq("erreur").textContent = "";
  let res;
  try {
    res = await api(`/api/nextcloud/dossiers?chemin=${encodeURIComponent(chemin)}`);
  } catch (e) {
    // dossier pas encore créé : on remonte au parent (il sera créé au premier envoi)
    if (chemin) return chargerDossier(parent(chemin));
    liste.replaceChildren();
    dq("erreur").textContent = e.message;
    return;
  }
  cheminCourant = res.chemin;

  const fil = dq("fil");
  const racine = el("button", { type: "button" }, "Racine");
  racine.addEventListener("click", () => chargerDossier(""));
  fil.replaceChildren(racine);
  cheminCourant.split("/").filter(Boolean).forEach((part, i, parts) => {
    const b = el("button", { type: "button" }, part);
    b.addEventListener("click", () => chargerDossier(parts.slice(0, i + 1).join("/")));
    fil.append(el("span", { class: "sep" }, "/"), b);
  });

  liste.replaceChildren(...(res.dossiers.length ? res.dossiers.map((nom) => {
    const b = el("button", { type: "button" }, `📁 ${nom}`);
    b.addEventListener("click", () => chargerDossier(joindre(cheminCourant, nom)));
    return el("li", {}, b);
  }) : [el("li", { class: "vide" }, "Aucun sous-dossier")]));
}

async function ouvrirDossier() {
  if (!state.config?.configure) return ouvrirReglages();
  dlgDossier.showModal();
  await chargerDossier(state.config.dossier);
}

dq("form-nouveau").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.currentTarget;
  try {
    const res = await postJSON("/api/nextcloud/dossiers", { parent: cheminCourant, nom: form.nom.value.trim() });
    form.reset();
    await chargerDossier(res.chemin);
  } catch (err) {
    dq("erreur").textContent = err.message;
  }
});

dq("choisir").addEventListener("click", async () => {
  try {
    state.config = await postJSON("/api/config", { dossier: cheminCourant });
    majDossier();
    dlgDossier.close();
  } catch (err) {
    dq("erreur").textContent = err.message;
  }
});

$("#btn-dossier").addEventListener("click", ouvrirDossier);

// ---------------------------------------------------------------- démarrage

api("/api/config")
  .then((c) => { state.config = c; majDossier(); })
  .catch(() => { $("#dossier-courant").textContent = "Serveur injoignable"; });
