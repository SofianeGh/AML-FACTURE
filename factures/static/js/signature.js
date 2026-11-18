// Zone de signature : on signe à la souris, au doigt ou au stylet ; on peut aussi importer une image.
// La signature est envoyée au serveur en PNG (fond transparent).

export class Signature {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.vide = true;
    this.trace = null;
    canvas.addEventListener("pointerdown", (e) => this.debut(e));
    canvas.addEventListener("pointermove", (e) => this.suite(e));
    ["pointerup", "pointercancel"].forEach((t) => canvas.addEventListener(t, () => { this.trace = null; }));
  }

  position(e) {
    const r = this.canvas.getBoundingClientRect();
    return [(e.clientX - r.left) * this.canvas.width / r.width, (e.clientY - r.top) * this.canvas.height / r.height];
  }

  stylo() {
    const c = this.ctx;
    c.strokeStyle = "#111";
    c.fillStyle = "#111";
    c.lineWidth = 3.4;
    c.lineCap = "round";
    c.lineJoin = "round";
  }

  debut(e) {
    e.preventDefault();
    this.canvas.setPointerCapture(e.pointerId);
    this.trace = this.position(e);
    this.stylo();
    this.ctx.beginPath();
    this.ctx.arc(...this.trace, this.ctx.lineWidth / 2, 0, Math.PI * 2);
    this.ctx.fill();
    this.vide = false;
  }

  suite(e) {
    if (!this.trace) return;
    const points = e.getCoalescedEvents ? e.getCoalescedEvents() : [e];
    this.stylo();
    this.ctx.beginPath();
    this.ctx.moveTo(...this.trace);
    for (const p of points.length ? points : [e]) {
      this.trace = this.position(p);
      this.ctx.lineTo(...this.trace);
    }
    this.ctx.stroke();
  }

  effacer() {
    this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
    this.vide = true;
  }

  // Affiche une signature (data URL), centrée et réduite pour tenir dans la zone
  async charger(source) {
    this.effacer();
    if (!source) return;
    const image = new Image();
    image.src = source;
    await image.decode();
    const { width: l, height: h } = this.canvas;
    const echelle = Math.min((l - 20) / image.width, (h - 20) / image.height, 1.5);
    const lw = image.width * echelle;
    const lh = image.height * echelle;
    this.ctx.drawImage(image, (l - lw) / 2, (h - lh) / 2, lw, lh);
    this.vide = false;
  }

  // Image choisie sur l'appareil (photo d'une signature sur papier blanc, par exemple)
  importer(fichier) {
    return new Promise((ok, ko) => {
      const lecteur = new FileReader();
      lecteur.onload = () => this.charger(lecteur.result).then(ok, ko);
      lecteur.onerror = () => ko(lecteur.error);
      lecteur.readAsDataURL(fichier);
    });
  }

  valeur() {
    return this.vide ? null : this.canvas.toDataURL("image/png");
  }
}
