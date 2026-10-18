// Nextcloud : connexion (admin), dossier principal, destination de chaque type de PDF.
import { api, postJSON } from "./api.js";
import { $, alerte, el, state } from "./outils.js";

// ---------------------------------------------------------------- connexion Nextcloud

export function majDossier() {
  const c = state.config;
  const perso = c ? Object.values(c.destinations).filter(Boolean).length : 0;
  const detail = c?.rangement === "facture" ? " · 1 dossier par facture" : perso ? ` (+${perso})` : "";
  $("#dossier-courant").textContent = c?.configure ? `/${c.dossier}${detail}`
    : state.moi?.admin ? "Configurer Nextcloud…" : "Nextcloud non configuré";
}

// Nextcloud pas encore connecté : un administrateur le configure, les autres sont prévenus
export function besoinNextcloud() {
  if (state.moi?.admin) ouvrirReglages();
  else alerte("Nextcloud n'est pas encore configuré : demandez à un administrateur Local Stock.");
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
    state.config = await postJSON("api/config", {
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

// ---------------------------------------------------------------- destinations des PDF

// Chaque type de PDF (facture, bilans, récap de chaque catégorie) peut avoir son dossier ;
// sinon il va dans le dossier principal.
const dlgDestinations = $("#dlg-destinations");

function afficherDestinations() {
  const c = state.config;
  const ligne = (cle, libelle, chemin, propre) => {
    const changer = el("button", { class: "btn", type: "button" }, "Changer");
    changer.addEventListener("click", () => ouvrirDossier(cle));
    const li = el("li", {},
      el("span", { class: "doc" }, libelle),
      el("span", { class: propre ? "chemin" : "chemin herite" },
        propre ? `/${chemin}` : `dossier principal (/${c.dossier})`),
      changer);
    if (cle !== "principal" && propre) {
      const reset = el("button", { class: "reset", type: "button", title: "Revenir au dossier principal" }, "↺");
      reset.addEventListener("click", async () => {
        try {
          state.config = await postJSON("api/config", { destinations: { [cle]: "" } });
          majDossier();
          afficherDestinations();
        } catch (err) {
          dlgDestinations.querySelector("[data-f=erreur]").textContent = err.message;
        }
      });
      li.append(reset);
    }
    return li;
  };
  const liste = dlgDestinations.querySelector("[data-f=liste]");
  liste.replaceChildren(
    ligne("principal", "Dossier principal", c.dossier, true),
    ...Object.entries(c.documents).map(([cle, libelle]) =>
      ligne(cle, libelle, c.destinations[cle], Boolean(c.destinations[cle]))),
  );
  // un dossier par facture : les dossiers par type ne servent pas
  liste.classList.toggle("par-facture", c.rangement === "facture");
  dlgDestinations.querySelector(`input[name=rangement][value=${c.rangement}]`).checked = true;
}

dlgDestinations.querySelectorAll("input[name=rangement]").forEach((radio) =>
  radio.addEventListener("change", async () => {
    const erreur = dlgDestinations.querySelector("[data-f=erreur]");
    erreur.textContent = "";
    try {
      state.config = await postJSON("api/config", { rangement: radio.value });
      majDossier();
      afficherDestinations();
    } catch (err) {
      erreur.textContent = err.message;
    }
  }));

function ouvrirDestinations() {
  if (!state.config?.configure) return besoinNextcloud();
  dlgDestinations.querySelector("[data-f=erreur]").textContent = "";
  afficherDestinations();
  dlgDestinations.showModal();
}

$("#btn-dossier").addEventListener("click", ouvrirDestinations);

// ---------------------------------------------------------------- choix du dossier

const dlgDossier = $("#dlg-dossier");
const dq = (k) => dlgDossier.querySelector(`[data-f="${k}"]`);
let cheminCourant = "";
let cibleDossier = "principal"; // "principal" ou un type de PDF

const joindre = (...parts) => parts.filter(Boolean).join("/");
const parent = (chemin) => chemin.split("/").slice(0, -1).join("/");

async function chargerDossier(chemin) {
  const liste = dq("liste");
  liste.replaceChildren(el("li", { class: "vide" }, "Chargement…"));
  dq("erreur").textContent = "";
  let res;
  try {
    res = await api(`api/nextcloud/dossiers?chemin=${encodeURIComponent(chemin)}`);
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

async function ouvrirDossier(cible = "principal") {
  if (!state.config?.configure) return besoinNextcloud();
  cibleDossier = cible;
  const c = state.config;
  dq("titre").textContent = cible === "principal" ? "Dossier principal" : `Dossier : ${c.documents[cible]}`;
  dlgDossier.showModal();
  await chargerDossier((cible !== "principal" && c.destinations[cible]) || c.dossier);
}

dq("form-nouveau").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.currentTarget;
  try {
    const res = await postJSON("api/nextcloud/dossiers", { parent: cheminCourant, nom: form.nom.value.trim() });
    form.reset();
    await chargerDossier(res.chemin);
  } catch (err) {
    dq("erreur").textContent = err.message;
  }
});

dq("choisir").addEventListener("click", async () => {
  try {
    state.config = await postJSON("api/config", cibleDossier === "principal"
      ? { dossier: cheminCourant }
      : { destinations: { [cibleDossier]: cheminCourant } });
    majDossier();
    if (dlgDestinations.open) afficherDestinations();
    dlgDossier.close();
  } catch (err) {
    dq("erreur").textContent = err.message;
  }
});
