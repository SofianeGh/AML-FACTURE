// Démarrage de la page : chargement des réglages, dépôt des factures, fenêtres, onglets.
import { api, store } from "./api.js";
import { afficherReglages, champsReglages } from "./calculs.js";
import { majSession } from "./comptes.js";
import { ajouterFichiers, recalcAll } from "./facture.js";
import { majDossier } from "./dossiers.js";
import { afficherConducteurs } from "./nextcloud.js";
import { ongletActif } from "./onglets.js";
import { $, alerte, state } from "./outils.js";
import "./association.js";
import "./ndf.js";
import "./devis.js";
import "./treso.js";

champsReglages.forEach((champ) => champ.addEventListener("input", recalcAll));

document.querySelectorAll("dialog [data-close]").forEach((b) =>
  b.addEventListener("click", () => b.closest("dialog").close()));

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
  // ailleurs que dans l'onglet METRO, un fichier lâché à côté d'une zone de dépôt est ignoré
  if (ongletActif() === "metro" && e.dataTransfer?.files?.length) ajouterFichiers([...e.dataTransfer.files]);
});

// ---------------------------------------------------------------- démarrage

async function demarrer() {
  const [moi, preferences, config] = await Promise.all([
    api("api/moi"), api("api/preferences"), api("api/config"),
  ]);
  state.moi = moi;
  state.config = config;
  store.valeurs = preferences;
  afficherReglages();
  afficherConducteurs();
  majSession();
  majDossier();
}

state.pret = demarrer().catch((e) => {
  alerte(`Démarrage impossible : ${e.message}`);
  $("#dossier-courant").textContent = "Serveur injoignable";
});
