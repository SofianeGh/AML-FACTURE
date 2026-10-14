"""Extraction des lignes d'une facture METRO (PDF texte, police à chasse fixe).

Les factures METRO sont imprimées en MS-Gothic 8,5 pt (chasse fixe) avec un
filigrane « Duplicata » en diagonale. On ignore le filigrane (caractères
pivotés et gros corps), on reconstruit chaque ligne de texte, puis on lit :
  - la date et le numéro de facture,
  - les lignes articles (prix unitaire HT, colisage, quantité, montant, code TVA),
  - les remises (« Offre Achetez Plus Payez Moins ... 2,32- ») rattachées à
    l'article précédent,
  - le récapitulatif TVA (code -> taux, HT, TVA, TTC) pour contrôler le résultat.

Usage en ligne de commande :  python metro_parser.py facture.pdf
"""
import re
import sys
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

import pdfplumber

CHAR_WIDTH = 4.25  # largeur d'un caractère demi-chasse en MS-Gothic 8,5 pt
LINE_TOLERANCE = 2.0  # écart vertical max (pt) entre caractères d'une même ligne

NUM = r"\d+(?:\.\d{3})*,\d+"

RE_DATE = re.compile(r"Date facture\s*:\s*(\d{2})-(\d{2})-(\d{4})")
RE_NUMERO = re.compile(r"N[º°]\s*FACTURE\s+(\S+?)[②\s]")
RE_TICKET = re.compile(r"\((\d{3}-\d{6})\)")
RE_ARTICLE = re.compile(
    r"^\s*(?:(?P<ean>\d{8,14})\s+)?(?P<art>\d{6,8})\s(?P<milieu>.*?)\s+"
    rf"(?P<prix>{NUM})\s+(?P<colis>\d+)\s+(?P<qte>{NUM}|\d+)\s+"
    rf"(?P<montant>{NUM})(?P<neg>-)?\s+(?P<tva>[A-Z])\b(?P<fin>.*)$"
)
RE_REMISE = re.compile(rf"^\s+(?P<libelle>\S.*?)\s{{2,}}(?P<montant>{NUM})-(?:\s+(?P<tva>[A-Z]))?\s*$")
RE_SECTION = re.compile(rf"^\s*\*{{3}}\s*(?P<nom>.+?)\s+Total\s*:\s*(?P<montant>{NUM})")
RE_TVA = re.compile(
    rf"(?P<ht>{NUM})\s+(?P<code>[A-Z])\s*=\s*(?P<taux>{NUM})\s*%\s+(?P<tva>{NUM})\s+(?P<ttc>{NUM})"
)
RE_TOTAL_HT = re.compile(rf"Total H\.T\.\s*:\s*(?P<v>{NUM})")
RE_TOTAL_PAYER = re.compile(rf"Total à payer\s+(?P<v>{NUM})")


class FactureIllisible(Exception):
    """Le PDF ne ressemble pas à une facture METRO exploitable."""


def _dec(txt):
    return Decimal(txt.replace(".", "").replace(",", "."))


def _money(value):
    return float(Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _is_text(c):
    m = c["matrix"]
    return abs(m[1]) < 0.01 and abs(m[2]) < 0.01 and c["size"] < 20 and c["text"].strip()


def extract_lines(pdf):
    """Retourne la liste des lignes de texte (filigrane retiré), toutes pages confondues."""
    lignes = []
    for page in pdf.pages:
        chars = [c for c in page.chars if _is_text(c)]
        if not chars:
            continue
        left = min(c["x0"] for c in chars)
        chars.sort(key=lambda c: (c["top"], c["x0"]))
        groupes, courant, top = [], [], None
        for c in chars:
            if top is not None and c["top"] - top > LINE_TOLERANCE:
                groupes.append(courant)
                courant = []
            if not courant:
                top = c["top"]
            courant.append(c)
        if courant:
            groupes.append(courant)
        for groupe in groupes:
            cols = {}
            for c in groupe:
                cols[round((c["x0"] - left) / CHAR_WIDTH)] = c["text"]
            lignes.append("".join(cols.get(i, " ") for i in range(max(cols) + 1)).rstrip())
    return lignes


def parse_lines(lignes):
    facture = {
        "date": None,
        "numero": None,
        "ticket": None,
        "lignes": [],
        "tva": {},
        "total_ht": None,
        "total_ttc": None,
    }
    articles = []
    debut_section = 0

    for ligne in lignes:
        if facture["date"] is None and (m := RE_DATE.search(ligne)):
            j, mo, a = m.groups()
            facture["date"] = f"{j}-{mo}-{a}"
        if facture["numero"] is None and (m := RE_NUMERO.search(ligne)):
            facture["numero"] = m.group(1)
            if t := RE_TICKET.search(ligne):
                facture["ticket"] = t.group(1)

        if m := RE_ARTICLE.match(ligne):
            milieu = m["milieu"]
            montant = _dec(m["montant"]) * (-1 if m["neg"] else 1)
            colis = int(m["colis"])
            qte = _dec(m["qte"]) if "," in m["qte"] else Decimal(m["qte"])
            articles.append(
                {
                    "ean": m["ean"] or "",
                    "article": m["art"],
                    "designation": " ".join(milieu[:31].split()),
                    "infos": " ".join(milieu[31:].split()),
                    "categorie": "",
                    "prix_unitaire_ht": _dec(m["prix"]),
                    "colisage": colis,
                    "quantite": qte,
                    "montant_ht": montant,
                    "remise_ht": Decimal(0),
                    "tva_code": m["tva"],
                    "promo": "P" in m["fin"].split(),
                }
            )
            continue

        if m := RE_SECTION.match(ligne):
            for a in articles[debut_section:]:
                a["categorie"] = m["nom"].strip().title()
            debut_section = len(articles)
            continue

        if (m := RE_REMISE.match(ligne)) and articles:
            articles[-1]["remise_ht"] += _dec(m["montant"])
            continue

        if m := RE_TVA.search(ligne):
            facture["tva"][m["code"]] = {
                "taux": float(_dec(m["taux"])),
                "ht": _money(_dec(m["ht"])),
                "tva": _money(_dec(m["tva"])),
                "ttc": _money(_dec(m["ttc"])),
            }
            continue

        if facture["total_ht"] is None and (m := RE_TOTAL_HT.search(ligne)):
            facture["total_ht"] = _money(_dec(m["v"]))
        if facture["total_ttc"] is None and (m := RE_TOTAL_PAYER.search(ligne)):
            facture["total_ttc"] = _money(_dec(m["v"]))

    if not articles:
        raise FactureIllisible("Aucune ligne article METRO trouvée dans ce PDF.")

    # Calculs par ligne et contrôle par code TVA
    sommes = defaultdict(Decimal)
    for a in articles:
        net = a["montant_ht"] - a["remise_ht"]
        unites = a["colisage"] * a["quantite"]
        sommes[a["tva_code"]] += net
        taux = facture["tva"].get(a["tva_code"], {}).get("taux")
        facture["lignes"].append(
            {
                "ean": a["ean"],
                "article": a["article"],
                "designation": a["designation"],
                "infos": a["infos"],
                "categorie": a["categorie"] or "Autres",
                "prix_unitaire_ht": float(a["prix_unitaire_ht"]),
                "colisage": a["colisage"],
                "quantite": float(a["quantite"]),
                "unites": float(unites),
                "montant_ht": _money(a["montant_ht"]),
                "remise_ht": _money(a["remise_ht"]),
                "montant_net_ht": _money(net),
                # coût réel d'une unité, remises comprises
                "cout_unitaire_ht": float(net / unites) if unites else 0.0,
                "tva_code": a["tva_code"],
                "tva_taux": taux,
                "promo": a["promo"],
            }
        )

    controles = []
    for code, recap in sorted(facture["tva"].items()):
        calcule = _money(sommes.get(code, Decimal(0)))
        controles.append(
            {
                "code": code,
                "attendu_ht": recap["ht"],
                "calcule_ht": calcule,
                "ok": abs(calcule - recap["ht"]) < 0.005,
            }
        )
    for code in sorted(set(sommes) - set(facture["tva"])):
        controles.append(
            {"code": code, "attendu_ht": None, "calcule_ht": _money(sommes[code]), "ok": False}
        )
    facture["controles"] = controles
    facture["controle_ok"] = bool(controles) and all(c["ok"] for c in controles)
    return facture


def parse_pdf(source):
    """`source` : chemin ou objet fichier binaire."""
    try:
        with pdfplumber.open(source) as pdf:
            lignes = extract_lines(pdf)
    except Exception as exc:  # PDF corrompu, chiffré, etc.
        raise FactureIllisible(f"Impossible de lire le PDF : {exc}") from exc
    return parse_lines(lignes)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    for chemin in sys.argv[1:]:
        f = parse_pdf(chemin)
        print(f"== {chemin}")
        print(f"   date {f['date']}  n° {f['numero']}  ticket {f['ticket']}  "
              f"HT {f['total_ht']}  TTC {f['total_ttc']}  TVA {f['tva']}")
        for l in f["lignes"]:
            print(f"   {l['categorie'][:14]:14} {l['designation'][:30]:30} {l['unites']:>6g} u "
                  f"PU {l['prix_unitaire_ht']:>7.3f} net {l['montant_net_ht']:>8.2f} "
                  f"remise {l['remise_ht']:>5.2f} {l['tva_code']} {l['tva_taux']}")
        for c in f["controles"]:
            print(f"   contrôle TVA {c['code']}: attendu {c['attendu_ht']} calculé {c['calcule_ht']} "
                  f"{'OK' if c['ok'] else 'ÉCART'}")
