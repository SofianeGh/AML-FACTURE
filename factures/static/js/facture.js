// Affichage d'une facture : lignes, catégories, pièces, prix de vente, totaux, notes, export CSV.
import { api, store } from "./api.js";
import { calcLigne, enregistrerReglages, reglages } from "./calculs.js";
import { envoyer, statut, urlApercu, urlBilan, urlVentes } from "./nextcloud.js";
import { $, CATEGORIES, el, eur, eur3, nombre, pct, state } from "./outils.js";

export function recalc(f) {
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
  const conducteur = f.q("conducteur").value.trim();
  f.q("cadeau").previousElementSibling.textContent = `Cadeau conducteur${conducteur ? ` (${conducteur})` : ""}`;
  f.q("benefice-net").textContent = eur.format(net);
  f.q("benefice").parentElement.classList.toggle("benefice", !cadeau);
  f.q("benefice").classList.toggle("negatif", benefice < 0);
  f.q("benefice-net").classList.toggle("negatif", net < 0);
  f.q("cadeau").parentElement.hidden = !cadeau;
  f.q("benefice-net").parentElement.hidden = !cadeau;
}

// Réglage du haut de page modifié : enregistré pour tous et appliqué à toutes les factures
export function recalcAll() {
  enregistrerReglages();
  state.factures.forEach(recalc);
  majResumeGlobal();
}

// ---------------------------------------------------------------- champs de chaque ligne

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

// ---------------------------------------------------------------- notes des PDF

// Note imprimée dans un PDF (bilan ou récap d'une catégorie), propre à cette facture
const dlgNote = $("#dlg-note");
const formNote = $("#form-note");
let noteCible = null; // { f, doc, maj }

function lienNote(f, doc, libelle) {
  const lien = el("button", { class: "lien", type: "button", title: `Note imprimée dans le PDF ${libelle}` });
  const maj = () => {
    lien.textContent = f.notes[doc] ? "modifier la note ✎" : "ajouter une note";
    lien.classList.toggle("avec-note", Boolean(f.notes[doc]));
  };
  lien.addEventListener("click", () => {
    noteCible = { f, doc, maj };
    $("[data-f=titre]", formNote).textContent = `Note — ${libelle}`;
    formNote.texte.value = f.notes[doc] || "";
    dlgNote.showModal();
    formNote.texte.focus();
  });
  maj();
  return lien;
}

formNote.addEventListener("submit", (e) => {
  e.preventDefault();
  const { f, doc, maj } = noteCible;
  const texte = formNote.texte.value.trim();
  if (texte) f.notes[doc] = texte;
  else delete f.notes[doc];
  maj();
  dlgNote.close();
});

$("[data-f=effacer]", formNote).addEventListener("click", () => {
  formNote.texte.value = "";
  formNote.requestSubmit();
});

// Lien ordinaire vers un PDF : l'adresse est calculée au moment du clic (catégories, prix,
// conducteur et date à jour)
function lienApercu(f, lien, adresse) {
  lien.addEventListener("click", (e) => {
    if (!/^\d{2}-\d{2}-\d{4}$/.test(f.q("nom").value.trim())) {
      e.preventDefault();
      statut(f, "Date attendue au format JJ-MM-AAAA.", "ko");
      return;
    }
    lien.href = adresse();
  });
}

// Lignes « par catégorie » sous le total, avec l'aperçu du PDF de la catégorie et sa note
function lignesCategories(f) {
  f.lignesCat = {};
  const rows = Object.entries(CATEGORIES).map(([cat, libelle]) => {
    const n = el("span", { class: "nb" });
    const montant = el("td", { class: "num" });
    const lien = el("a", { class: "lien", href: "#", target: "_blank", rel: "noopener", title: `Voir le PDF ${libelle}` },
      "aperçu PDF");
    lienApercu(f, lien, () => urlApercu(f, cat));
    const tr = el("tr", { class: "ligne-cat" },
      el("td", { colspan: "9" },
        el("span", { class: `pastille cat-${cat}` }, libelle), " ", n, " · ", lien, " · ",
        lienNote(f, cat, `Récap ${libelle}`)),
      montant);
    f.lignesCat[cat] = { tr, n, montant };
    return tr;
  });
  f.q("total-ttc").parentElement.after(...rows);
}

// ---------------------------------------------------------------- carte d'une facture

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
  for (const [doc, libelle, url] of [["bilan", "Bilan final", urlBilan], ["ventes", "Bilan des ventes", urlVentes]]) {
    lienApercu(f, f.q(doc), () => url(f));
    f.q(doc).after(lienNote(f, doc, libelle));
  }
  f.q("conducteur").addEventListener("input", () => {
    f.q("conducteur").classList.remove("manquant");
    recalc(f); // libellé « Cadeau conducteur (…) »
  });
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

export async function ajouterFichiers(fichiers) {
  await state.pret; // préférences partagées chargées (pièces, prix, catégorie Local)
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
      const data = await api("api/factures", { method: "POST", body: fd });
      const f = {
        file: fichier,
        data,
        pieces: data.lignes.map((l) => store.get(`pieces:${l.article}`, 1)),
        prix: data.lignes.map((l) => store.get(`prix:${l.article}`, null)),
        categories: data.lignes.map((l) => (store.get(`local:${l.article}`, false) ? "local" : "vente")),
        notes: {}, // note de chaque PDF : { bilan: "…", ventes: "…", event: "…" }
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
