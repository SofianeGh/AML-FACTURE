// Envoi des factures sur Nextcloud, adresses des aperçus PDF, noms des conducteurs.
import { api, store } from "./api.js";
import { calcLigne, reglages, reglagesSaisis } from "./calculs.js";
import { besoinNextcloud } from "./dossiers.js";
import { $, el, state } from "./outils.js";

export function statut(f, texte, type = "") {
  const s = f.q("statut");
  s.textContent = texte;
  s.className = `statut ${type}`;
}

// Le conducteur est obligatoire pour envoyer : case signalée en rouge s'il manque
function conducteurDe(f, signaler = true) {
  const champ = f.q("conducteur");
  const nom = champ.value.trim().replace(/\s+/g, " ");
  if (!nom && signaler) {
    champ.classList.add("manquant");
    statut(f, "Indiquez le nom du conducteur avant d'envoyer.", "ko");
    champ.focus();
  }
  return nom;
}

// Facture + nom JJ-MM-AAAA.pdf + conducteur + catégorie de chaque ligne ; null s'il manque quelque chose
function formulaire(f) {
  const date = f.q("nom").value.trim();
  if (!/^\d{2}-\d{2}-\d{4}$/.test(date)) {
    statut(f, "Date attendue au format JJ-MM-AAAA.", "ko");
    f.q("nom").focus();
    return null;
  }
  const conducteur = conducteurDe(f);
  if (!conducteur) return null;
  const fd = new FormData();
  fd.append("fichier", f.file, f.file.name);
  fd.append("nom", `${date}.pdf`);
  fd.append("conducteur", conducteur);
  fd.append("categories", JSON.stringify(f.categories));
  fd.append("vente", JSON.stringify(donneesVente(f)));
  fd.append("notes", JSON.stringify(f.notes));
  return fd;
}

// Choix de vente pour le PDF « Bilan des ventes » : pièces, prix de vente et prix optimal
// de chaque ligne (null hors catégorie Vente), avec les réglages utilisés
function donneesVente(f) {
  const r = reglages();
  const vente = { pieces: [...f.pieces], prix: [], optimal: [] };
  f.data.lignes.forEach((ligne, i) => {
    const c = calcLigne(ligne, f.pieces[i], f.categories[i] === "vente", f.prix[i], r);
    vente.prix.push(c.pv);
    vente.optimal.push(c.optimal);
  });
  vente.reglages = reglagesSaisis();
  return vente;
}

export async function envoyer(f) {
  const fd = formulaire(f);
  if (!fd) return false;
  if (!state.config?.configure) {
    besoinNextcloud();
    return false;
  }
  const bouton = f.q("envoyer");
  bouton.disabled = true;
  statut(f, "Envoi en cours…");
  try {
    const res = await api("api/nextcloud/envoyer", { method: "POST", body: fd });
    const recaps = res.recaps.map((r) => r.nom.split(" - ").pop().replace(/\.pdf$/, ""));
    const nomFichier = (chemin) => chemin.split("/").pop();
    statut(f, (res.dossier ? [
      `✓ Dossier ${res.dossier}`,
      res.deja_present ? "facture déjà présente" : `facture ${nomFichier(res.chemin)}`,
      `bilan final, bilan des ventes et PDF ${recaps.join(", ")}`,
    ] : [
      res.deja_present ? `Facture déjà présente : ${res.chemin}` : `✓ Envoyé : ${res.chemin}`,
      `bilan final : ${res.bilan.chemin}`,
      `bilan des ventes : ${res.ventes.chemin}`,
      `PDF par catégorie : ${recaps.join(", ")}`,
    ]).concat(res.supprimes.length ? [`anciens PDF supprimés : ${res.supprimes.join(", ")}`] : [])
      .join(" · "), "ok");
    retenirConducteur(conducteurDe(f, false));
    return true;
  } catch (e) {
    statut(f, e.message, "ko");
    return false;
  } finally {
    bouton.disabled = false;
  }
}

$("#btn-tout-envoyer").addEventListener("click", async () => {
  if (!state.config?.configure) return besoinNextcloud();
  for (const f of state.factures) await envoyer(f);
});

// ---------------------------------------------------------------- adresses des aperçus

// Adresse du PDF d'une catégorie, tel qu'il sera envoyé (le serveur garde la facture analysée)
export function urlApercu(f, cat) {
  const params = new URLSearchParams({
    nom: `${f.q("nom").value.trim()}.pdf`, categories: f.categories.join(","), note: f.notes[cat] || "",
    conducteur: conducteurDe(f, false),
  });
  return `api/recap/${f.data.id}/${cat}?${params}`;
}

export function urlBilan(f) {
  const params = new URLSearchParams({
    nom: `${f.q("nom").value.trim()}.pdf`,
    categories: f.categories.join(","),
    note: f.notes.bilan || "",
    conducteur: conducteurDe(f, false),
  });
  return `api/bilan/${f.data.id}?${params}`;
}

export function urlVentes(f) {
  const params = new URLSearchParams({
    nom: `${f.q("nom").value.trim()}.pdf`,
    categories: f.categories.join(","),
    vente: JSON.stringify(donneesVente(f)),
    note: f.notes.ventes || "",
    conducteur: conducteurDe(f, false),
  });
  return `api/ventes/${f.data.id}?${params}`;
}

// ---------------------------------------------------------------- conducteurs

// Noms de conducteurs déjà utilisés, proposés dans la case (partagés entre les membres)
function retenirConducteur(nom) {
  if (!nom) return;
  const liste = store.get("conducteurs", []);
  store.set("conducteurs", [nom, ...liste.filter((n) => n.toLowerCase() !== nom.toLowerCase())].slice(0, 30));
  afficherConducteurs();
}

export function afficherConducteurs() {
  $("#liste-conducteurs").replaceChildren(...store.get("conducteurs", []).map((nom) => el("option", { value: nom })));
}
