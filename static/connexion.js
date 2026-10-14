"use strict";

const form = document.getElementById("form-connexion");
const erreur = form.querySelector("[data-f=erreur]");

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const bouton = form.querySelector("button[type=submit]");
  bouton.disabled = true;
  erreur.textContent = "";
  try {
    const resp = await fetch("api/connexion", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Requested-With": "fetch" },
      body: JSON.stringify({ nom: form.nom.value, mot_de_passe: form.mot_de_passe.value }),
    });
    const data = await resp.json().catch(() => null);
    if (!resp.ok) throw new Error(data?.erreur || `Erreur HTTP ${resp.status}`);
    location.href = "./";
  } catch (err) {
    erreur.textContent = err.message;
    form.mot_de_passe.select();
  } finally {
    bouton.disabled = false;
  }
});
