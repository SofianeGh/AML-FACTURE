// Notes de frais : liste, formulaire, justificatifs (photos ou PDF) et signature.
import { api, postJSON, putJSON } from "./api.js";
import { association } from "./association.js";
import { surOnglet } from "./onglets.js";
import { Signature } from "./signature.js";
import { $, alerte, aujourdhui, dateFr, el, eur, lien, nombreSaisi, ouvrirApresEnregistrement } from "./outils.js";

const STATUTS = { a_rembourser: ["À rembourser", "st-attente"], remboursee: ["Remboursée", "st-ok"] };
const CHAMPS = ["civilite", "prenom", "nom", "naissance_date", "naissance_lieu", "qualite", "association", "adresse",
  "nature", "liaison", "evenement", "fait_a", "fait_le", "statut"];
const LIAISON_DEFAUT = "réglés à l’occasion de l’";

const editeur = $("#ndf-editeur");
const form = $("#form-ndf");
const q = (k) => form.querySelector(`[data-f="${k}"]`);
const signature = new Signature(q("signature"));
let notes = [];
let courante = null; // { id (null tant que pas enregistrée), depenses: [...] }
let chargee = false;

surOnglet("ndf", () => {
  if (!chargee) {
    chargee = true;
    charger();
  }
});

// ---------------------------------------------------------------- liste

async function charger() {
  try {
    notes = await api("api/ndf");
    afficherListe();
  } catch (e) {
    chargee = false;
    $("#ndf-vide").textContent = `Liste indisponible : ${e.message}`;
  }
}

function afficherListe() {
  const texte = $("#ndf-recherche").value.trim().toLowerCase();
  const filtre = $("#ndf-filtre").value;
  const visibles = notes.filter((n) => (!filtre || n.statut === filtre)
    && (!texte || `${n.personne} ${n.objet}`.toLowerCase().includes(texte)));
  $("#ndf-liste").replaceChildren(...visibles.map(ligneListe));
  $("#ndf-vide").hidden = visibles.length > 0;
  $("#ndf-vide").textContent = notes.length ? "Aucune note ne correspond." : "Aucune note de frais pour l'instant.";
}

function choixStatut(statut, changer) {
  const choix = el("select", { class: "statut-liste", "aria-label": "Suivi" },
    ...Object.entries(STATUTS).map(([cle, [libelle]]) => el("option", { value: cle }, libelle)));
  const colorer = () => { choix.className = `statut-liste ${STATUTS[choix.value]?.[1] || ""}`; };
  choix.value = statut;
  colorer();
  choix.addEventListener("change", async () => {
    try {
      await changer(choix.value);
      colorer();
    } catch (e) {
      alerte(e.message);
    }
  });
  return choix;
}

function ligneListe(n) {
  const suivi = choixStatut(n.statut, async (statut) => {
    await postJSON(`api/ndf/${n.id}/statut`, { statut });
    n.statut = statut;
  });
  const pj = n.nb_justificatifs ? ` · ${n.nb_justificatifs} justif.` : "";
  return el("tr", {},
    el("td", { class: "num" }, dateFr(n.date)),
    el("td", {}, n.personne),
    el("td", {}, n.objet, el("span", { class: "sub" }, pj)),
    el("td", { class: "num" }, eur.format(n.total_ttc)),
    el("td", {}, suivi),
    el("td", { class: "actions" },
      lien("Modifier", () => ouvrir(n.id)),
      el("a", { class: "lien", href: `api/ndf/${n.id}/pdf`, target: "_blank", rel: "noopener" }, "PDF"),
      lien("Dupliquer", () => dupliquer(n.id), { title: "Nouvelle note pour la même personne" }),
      lien("Supprimer", () => supprimer(n))));
}

$("#ndf-recherche").addEventListener("input", afficherListe);
$("#ndf-filtre").addEventListener("change", afficherListe);

async function supprimer(n) {
  if (!confirm(`Supprimer la note de frais de ${n.personne} (${eur.format(n.total_ttc)}) et ses justificatifs ?`)) return;
  try {
    await api(`api/ndf/${n.id}`, { method: "DELETE" });
    if (courante?.id === n.id) fermer();
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

async function nouvelle(modele = null) {
  let a = { sigle: "AML", ville_signature: "Lyon" };
  try { a = await association(); } catch { /* valeurs par défaut */ }
  courante = { id: null };
  remplir({
    civilite: "M.", qualite: "membre", association: a.sigle, liaison: LIAISON_DEFAUT, fait_a: a.ville_signature,
    ...modele,
    fait_le: aujourdhui(), statut: "a_rembourser",
    depenses: (modele?.depenses || [{ fournisseur: "", date: aujourdhui(), recu: "", montant: "" }])
      .map((d) => ({ ...d, justificatifs: [] })), // un justificatif n'appartient qu'à une note
  });
}

async function ouvrir(id) {
  try {
    const n = await api(`api/ndf/${id}`);
    courante = { id };
    remplir(n);
  } catch (e) {
    alerte(e.message);
  }
}

async function dupliquer(id) {
  try {
    const n = await api(`api/ndf/${id}`);
    await nouvelle({ ...n, depenses: undefined });
  } catch (e) {
    alerte(e.message);
  }
}

function remplir(n) {
  for (const k of CHAMPS) form.elements[k].value = n[k] ?? "";
  courante.depenses = n.depenses.map((d) => ({
    fournisseur: d.fournisseur ?? "", date: d.date ?? "", recu: d.recu ?? "", montant: d.montant ?? "",
    justificatifs: [...(d.justificatifs || [])],
  }));
  q("titre").textContent = courante.id ? `Note de frais de ${n.prenom} ${String(n.nom).toUpperCase()}` : "Nouvelle note de frais";
  afficherDepenses();
  majPhrase();
  message("");
  signature.charger(n.signature).catch(() => signature.effacer());
  editeur.hidden = false;
  editeur.scrollIntoView({ behavior: "smooth", block: "start" });
}

function fermer() {
  editeur.hidden = true;
  courante = null;
}

$("#ndf-nouvelle").addEventListener("click", () => nouvelle());
q("fermer").addEventListener("click", fermer);

// Aperçu de la phrase imprimée : « … les dépenses suivantes : 10 repas complets réglés à l'occasion de l'afterwork… »
function majPhrase() {
  const v = (k) => form.elements[k].value.trim();
  const liaison = v("liaison");
  const espace = !liaison || /['’]$/.test(liaison) ? "" : " ";
  q("phrase").replaceChildren("Sur le PDF : « … les dépenses suivantes : ", el("strong", {}, v("nature") || "…"),
    ` ${liaison}${espace}`, el("strong", {}, v("evenement") || "…"), ". »");
}
["nature", "liaison", "evenement"].forEach((k) => form.elements[k].addEventListener("input", majPhrase));

// ---------------------------------------------------------------- dépenses et justificatifs

function afficherDepenses() {
  q("depenses").replaceChildren(...courante.depenses.map((d, i) => {
    const champ = (attrs, cle) => {
      const input = el("input", attrs);
      input.value = d[cle];
      input.addEventListener("input", () => { d[cle] = input.value; majTotal(); });
      return input;
    };
    const fichiers = el("input", { type: "file", accept: "image/*,application/pdf", multiple: "", hidden: "" });
    fichiers.addEventListener("change", () => {
      ajouterJustificatifs(d, [...fichiers.files]);
      fichiers.value = "";
    });
    const vignettes = el("div", { class: "vignettes" }, ...d.justificatifs.map((id, k) => {
      const retirer = el("button", { type: "button", class: "retirer", title: "Retirer ce justificatif", "aria-label": "Retirer" }, "×");
      retirer.addEventListener("click", () => { d.justificatifs.splice(k, 1); afficherDepenses(); });
      return el("span", { class: "vignette" },
        el("a", { href: `api/ndf/justificatifs/${id}`, target: "_blank", rel: "noopener", title: "Voir en grand" },
          el("img", { src: `api/ndf/justificatifs/${id}`, alt: `Justificatif ${k + 1}`, loading: "lazy" })),
        retirer);
    }), el("label", { class: "btn ghost ajout", title: "Photo du ticket ou PDF (glisser-déposer possible)" }, "Ajouter", fichiers));
    const cellule = el("td", { class: "justificatifs" }, vignettes);
    ["dragenter", "dragover"].forEach((t) => cellule.addEventListener(t, (e) => {
      e.preventDefault();
      e.stopPropagation();
      cellule.classList.add("survol");
    }));
    cellule.addEventListener("dragleave", () => cellule.classList.remove("survol"));
    cellule.addEventListener("drop", (e) => {
      e.preventDefault();
      e.stopPropagation();
      cellule.classList.remove("survol");
      ajouterJustificatifs(d, [...e.dataTransfer.files]);
    });
    const retirer = el("button", { class: "reset", type: "button", title: "Retirer la dépense", "aria-label": "Retirer la dépense" }, "×");
    retirer.addEventListener("click", () => {
      courante.depenses.splice(i, 1);
      afficherDepenses();
    });
    return el("tr", {},
      el("td", {}, champ({ required: "", maxlength: "200", placeholder: "Restaurant du Parc, 5 avenue des Tilleuls, 69100 Villeurbanne", "aria-label": "Fournisseur" }, "fournisseur")),
      el("td", {}, champ({ type: "date", required: "", "aria-label": "Date" }, "date")),
      el("td", {}, champ({ maxlength: "40", class: "recu", "aria-label": "N° de reçu" }, "recu")),
      el("td", { class: "num" }, champ({ type: "number", step: "0.01", min: "0.01", required: "", inputmode: "decimal", class: "montant", "aria-label": "Montant TTC" }, "montant")),
      cellule,
      el("td", {}, courante.depenses.length > 1 ? retirer : ""));
  }));
  majTotal();
}

function majTotal() {
  const total = courante.depenses.reduce((s, d) => s + nombreSaisi(d.montant), 0);
  q("total").textContent = eur.format(total);
}

q("ajouter-depense").addEventListener("click", () => {
  const precedente = courante.depenses.at(-1);
  courante.depenses.push({ fournisseur: "", date: precedente?.date || aujourdhui(), recu: "", montant: "", justificatifs: [] });
  afficherDepenses();
});

async function ajouterJustificatifs(depense, fichiers) {
  for (const fichier of fichiers) {
    const fd = new FormData();
    fd.append("fichier", fichier, fichier.name);
    message(`Envoi de ${fichier.name}…`);
    try {
      const pages = await api("api/ndf/justificatifs", { method: "POST", body: fd });
      depense.justificatifs.push(...pages.map((p) => p.id));
      message(pages.length > 1 ? `${fichier.name} : ${pages.length} pages ajoutées` : "");
    } catch (e) {
      message(`${fichier.name} : ${e.message}`, "ko");
    }
    if (courante?.depenses.includes(depense)) afficherDepenses();
  }
}

// ---------------------------------------------------------------- signature

q("effacer-signature").addEventListener("click", () => signature.effacer());
q("importer-signature").addEventListener("change", async (e) => {
  const fichier = e.target.files[0];
  e.target.value = "";
  if (!fichier) return;
  try {
    await signature.importer(fichier);
  } catch {
    message("Image illisible : choisissez une photo JPEG ou PNG de la signature.", "ko");
  }
});

// ---------------------------------------------------------------- enregistrement

function lireFormulaire() {
  const n = Object.fromEntries(CHAMPS.map((k) => [k, form.elements[k].value.trim()]));
  n.depenses = courante.depenses.map((d) => ({
    fournisseur: d.fournisseur.trim(), date: d.date, recu: d.recu.trim(), montant: nombreSaisi(d.montant),
    justificatifs: d.justificatifs,
  }));
  n.signature = signature.valeur();
  return n;
}

// Renvoie l'identifiant de la note enregistrée, ou null
async function enregistrer() {
  if (!form.reportValidity()) return null;
  if (!courante.depenses.length) {
    message("Ajoutez au moins une dépense.", "ko");
    return null;
  }
  const boutons = form.querySelectorAll(".editeur-actions .btn");
  boutons.forEach((b) => { b.disabled = true; });
  message("Enregistrement…");
  try {
    const donnees = lireFormulaire();
    const res = courante.id ? await putJSON(`api/ndf/${courante.id}`, donnees) : await postJSON("api/ndf", donnees);
    courante.id = res.id;
    q("titre").textContent = `Note de frais de ${donnees.prenom} ${donnees.nom.toUpperCase()}`;
    message("✓ Enregistrée", "ok");
    charger();
    return res.id;
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
  return id ? `api/ndf/${id}/pdf` : null;
}));
