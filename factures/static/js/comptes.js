// Session et comptes : nom affiché, déconnexion, mot de passe, gestion des comptes (admin).
import { api, postJSON, store } from "./api.js";
import { $, el, state } from "./outils.js";

export function majSession() {
  const moi = state.moi;
  $("#utilisateur").textContent = moi.admin ? `${moi.nom} (admin)` : moi.nom;
  $("#liens-admin").hidden = !moi.admin;
  $("#btn-reglages").hidden = !moi.admin;
}

$("#btn-deconnexion").addEventListener("click", async () => {
  await store.envoyer();
  await api("api/deconnexion", { method: "POST" }).catch(() => {});
  location.href = "connexion";
});

const dlgMdp = $("#dlg-mdp");
const formMdp = $("#form-mdp");

$("#btn-mdp").addEventListener("click", () => {
  formMdp.reset();
  $("[data-f=erreur]", formMdp).textContent = "";
  dlgMdp.showModal();
});

formMdp.addEventListener("submit", async (e) => {
  e.preventDefault();
  const erreur = $("[data-f=erreur]", formMdp);
  if (formMdp.nouveau.value !== formMdp.confirmation.value) {
    erreur.textContent = "Les deux nouveaux mots de passe ne correspondent pas.";
    return;
  }
  try {
    await postJSON("api/moi/mot-de-passe", { actuel: formMdp.actuel.value, nouveau: formMdp.nouveau.value });
    dlgMdp.close();
  } catch (err) {
    erreur.textContent = err.message;
  }
});

const dlgComptes = $("#dlg-comptes");
const cq = (k) => dlgComptes.querySelector(`[data-f="${k}"]`);

function afficherComptes(comptes) {
  cq("liste").replaceChildren(...comptes.map((c) => {
    const li = el("li", {},
      el("span", { class: "nom" }, c.nom),
      el("span", { class: c.admin ? "pastille cat-vente" : "pastille cat-local" }, c.admin ? "admin" : "membre"));
    if (c.nom !== state.moi.nom) {
      const suppr = el("button", { class: "lien", type: "button" }, "supprimer");
      suppr.addEventListener("click", async () => {
        if (!confirm(`Supprimer le compte « ${c.nom} » ?`)) return;
        try {
          afficherComptes(await api(`api/comptes/${encodeURIComponent(c.nom)}`, { method: "DELETE" }));
        } catch (err) {
          cq("erreur").textContent = err.message;
        }
      });
      li.append(suppr);
    }
    return li;
  }));
}

$("#btn-comptes").addEventListener("click", async () => {
  cq("erreur").textContent = "";
  cq("form-nouveau").reset();
  dlgComptes.showModal();
  try {
    afficherComptes(await api("api/comptes"));
  } catch (err) {
    cq("erreur").textContent = err.message;
  }
});

cq("form-nouveau").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.currentTarget;
  cq("erreur").textContent = "";
  try {
    afficherComptes(await postJSON("api/comptes", {
      nom: form.nom.value.trim(), mot_de_passe: form.mot_de_passe.value, admin: form.admin.checked,
    }));
    form.reset();
  } catch (err) {
    cq("erreur").textContent = err.message;
  }
});
