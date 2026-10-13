"""Le rapport d'audit : ce qu'on remet au client.

    python -m brain.rapport <identifiant-audit> [--sortie rapport.html]

Un fichier HTML autonome (aucune image, aucun script, aucune police à
télécharger), imprimable en PDF depuis n'importe quel navigateur. Il s'ouvre
sur une machine sans Internet — comme le reste du produit.

Trois règles, tenues par le code :

1. **Le rapport ne dit que ce qui a été mesuré.** Chaque écart porte la
   commande exacte, sa sortie, l'heure, et la fiche qui l'a jugé. Ce que le
   modèle a *dit* sans observation n'entre pas : les hypothèses non fondées
   sont comptées en note, jamais présentées comme des constats.

2. **Un audit vide ne ressemble pas à un audit propre.** Si rien n'a été
   mesuré, le rapport le dit en tête, en grand, au lieu de sortir un beau
   document sans contenu. C'est la même règle que pour les outils : un échec
   ne doit jamais ressembler à un résultat propre.

3. **Ce que l'audit ne dit pas est écrit dedans.** Les contrôles indéterminés,
   ce qui n'a pas été regardé, et les limites de la mesure ont leur section.
   Personne n'écrit cette section-là ; c'est elle qui rend le reste croyable.

Aucune dépendance : bibliothèque standard seulement.
"""
from __future__ import annotations

import argparse
import html
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ORDRE_GRAVITE = ["critique", "elevee", "élevée", "moyenne", "faible", ""]
LISIBLE = {"critique": "critique", "elevee": "élevée", "élevée": "élevée",
           "moyenne": "moyenne", "faible": "faible", "": "non précisée"}


def _rang(gravite: str) -> int:
    g = (gravite or "").lower()
    return ORDRE_GRAVITE.index(g) if g in ORDRE_GRAVITE else len(ORDRE_GRAVITE)


def _date(horodatage: float | None) -> str:
    if not horodatage:
        return "—"
    return datetime.fromtimestamp(horodatage, timezone.utc).strftime(
        "%d/%m/%Y à %H:%M UTC")


def _e(texte) -> str:
    """Échappe tout ce qui vient de la machine auditée.

    La sortie d'une commande est du texte contrôlé par la machine mesurée :
    elle ne doit jamais pouvoir écrire du HTML dans notre rapport."""
    return html.escape(str(texte if texte is not None else ""), quote=True)


# --------------------------------------------------------------------------- #
# Lecture de la mémoire d'audit
# --------------------------------------------------------------------------- #
def charger(identifiant: str, dossier: Path) -> dict:
    chemin = Path(dossier) / f"{identifiant}.json"
    if not chemin.exists():
        raise FileNotFoundError(f"audit introuvable : {chemin}")
    return json.loads(chemin.read_text(encoding="utf-8"))


def trier(audit: dict) -> dict:
    """Range la mémoire d'audit en matière de rapport.

    Le tri est fait ICI, pas dans le gabarit : ce qui décide de ce qu'on
    montre doit être lisible et testable."""
    evaluations = list((audit.get("evaluations") or {}).values())
    constats = audit.get("constats") or []

    ecarts = [e for e in evaluations if e.get("statut") == "ecart"]
    conformes = [e for e in evaluations if e.get("statut") == "conforme"]
    indetermines = [e for e in evaluations if e.get("statut") == "indetermine"]
    ecarts.sort(key=lambda e: (_rang(e.get("gravite", "")),
                               e.get("titre", "")))
    indetermines.sort(key=lambda e: e.get("titre", ""))

    # Un écart mesuré puis retrouvé conforme : c'est un écart CORRIGÉ, il ne
    # disparaît pas du rapport — il change de section.
    cles_corrigees = {c.get("cle") for c in constats if c.get("corrige")}
    ecarts_restants = [e for e in ecarts
                       if f"{e.get('fiche')}#{e.get('controle')}"
                       not in cles_corrigees]

    corrections = audit.get("corrections") or []
    appliquees = [c for c in corrections if c.get("applique")]
    revenues = [c for c in corrections
                if c.get("revenu") or c.get("annule") or c.get("refus")]

    hypotheses = [c for c in constats if not c.get("fonde", True)]
    du_modele = [c for c in constats
                 if c.get("fonde", True) and c.get("origine") != "code"]

    commandes = audit.get("commandes") or []
    return {
        "ecarts": ecarts_restants,
        "ecarts_corriges": [e for e in ecarts if e not in ecarts_restants],
        "conformes": conformes,
        "indetermines": indetermines,
        "corrections_appliquees": appliquees,
        "corrections_sans_suite": revenues,
        "hypotheses": hypotheses,
        "constats_du_modele": du_modele,
        "commandes": commandes,
        "lectures": [c for c in commandes if c.get("executee")],
        "preuves": audit.get("preuves") or [],
        "mesure": bool(evaluations),
    }


def par_gravite(ecarts: list[dict]) -> dict[str, int]:
    comptes: dict[str, int] = {}
    for e in ecarts:
        nom = LISIBLE.get((e.get("gravite") or "").lower(), "non précisée")
        comptes[nom] = comptes.get(nom, 0) + 1
    return comptes


# --------------------------------------------------------------------------- #
# Mise en page
# --------------------------------------------------------------------------- #
STYLE = """
:root{
  --encre:#16181a; --doux:#5c6166; --filet:#d9dbd8; --fond:#ffffff;
  --papier:#f7f7f5;
  --critique:#a3322a; --elevee:#b4652c; --moyenne:#8a7a28; --faible:#4a6b46;
  --conforme:#3f6b42; --indetermine:#6b6560;
}
*{box-sizing:border-box}
body{margin:0;background:var(--papier);color:var(--encre);
  font:15px/1.6 "Segoe UI",system-ui,-apple-system,sans-serif}
.page{max-width:980px;margin:0 auto;background:var(--fond);
  padding:44px 48px 64px;min-height:100vh}
h1{font-size:30px;margin:0 0 6px;letter-spacing:-.01em}
h2{font-size:20px;margin:40px 0 14px;padding-bottom:7px;
  border-bottom:2px solid var(--encre)}
h3{font-size:16px;margin:0 0 4px}
p{margin:0 0 12px;max-width:74ch}
.sous{color:var(--doux);margin:0 0 26px}
.mono{font-family:"Cascadia Mono",Consolas,"DejaVu Sans Mono",monospace;
  font-size:13px}
table{border-collapse:collapse;width:100%;margin:10px 0 18px;font-size:14px}
th,td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--filet);
  vertical-align:top}
th{font-size:12px;text-transform:uppercase;letter-spacing:.08em;
  color:var(--doux);font-weight:600}
td.nb{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.bandeau{display:flex;flex-wrap:wrap;gap:10px;margin:18px 0 26px}
.tuile{border:1px solid var(--filet);border-radius:5px;padding:12px 16px;
  min-width:120px}
.tuile .n{font-size:26px;font-weight:700;font-variant-numeric:tabular-nums;
  line-height:1.1}
.tuile .q{font-size:12px;color:var(--doux);text-transform:uppercase;
  letter-spacing:.07em}
.constat{border:1px solid var(--filet);border-left:4px solid var(--teinte,var(--filet));
  border-radius:4px;padding:14px 18px;margin:0 0 12px;
  break-inside:avoid;page-break-inside:avoid}
.constat.critique{--teinte:var(--critique)}
.constat.elevee,.constat\\.élevée{--teinte:var(--elevee)}
.constat.moyenne{--teinte:var(--moyenne)}
.constat.faible{--teinte:var(--faible)}
.etiquette{display:inline-block;font-size:11px;text-transform:uppercase;
  letter-spacing:.09em;font-weight:700;color:var(--teinte,var(--doux))}
.champ{display:grid;grid-template-columns:150px 1fr;gap:4px 14px;
  margin-top:10px;font-size:13.5px}
.champ dt{color:var(--doux)}
.champ dd{margin:0}
.sortie{background:var(--papier);border:1px solid var(--filet);border-radius:3px;
  padding:8px 11px;margin:4px 0 0;white-space:pre-wrap;word-break:break-word;
  max-height:22em;overflow:auto}
.avert{border:2px solid var(--critique);border-radius:5px;padding:16px 20px;
  margin:0 0 26px;background:#fdf6f5}
.avert strong{color:var(--critique)}
.note{color:var(--doux);font-size:13.5px}
.pied{margin-top:46px;padding-top:16px;border-top:1px solid var(--filet);
  color:var(--doux);font-size:12.5px}
ul.serree{margin:6px 0 14px;padding-left:20px}
ul.serree li{margin:2px 0}
@media print{
  body{background:#fff}
  .page{padding:0;max-width:none}
  h2{break-after:avoid;page-break-after:avoid}
  .sortie{max-height:none}
}
"""


def _tuiles(t: dict) -> str:
    comptes = [
        ("écarts ouverts", len(t["ecarts"])),
        ("corrigés", len(t["ecarts_corriges"])),
        ("conformes", len(t["conformes"])),
        ("indéterminés", len(t["indetermines"])),
        ("lectures exécutées", len(t["lectures"])),
    ]
    return '<div class="bandeau">' + "".join(
        f'<div class="tuile"><div class="n">{n}</div>'
        f'<div class="q">{_e(q)}</div></div>' for q, n in comptes) + "</div>"


def _constat(e: dict, index: int) -> str:
    gravite = (e.get("gravite") or "").lower()
    classe = {"élevée": "elevee"}.get(gravite, gravite) or "faible"
    ref = f"{e.get('fiche', '')}#{e.get('controle', '')}"
    champs = [
        ("Constaté", f'<span class="mono">{_e(e.get("constate"))}</span>'),
        ("Attendu", f'<span class="mono">{_e(e.get("attendu"))}</span>'),
        ("Mesuré par", f'<span class="mono">{_e(e.get("commande"))}</span>'),
        ("Le", _e(_date(e.get("quand")))),
        ("Fiche", f'<span class="mono">{_e(ref)}</span>'),
    ]
    if e.get("motif"):
        champs.append(("Motif", _e(e["motif"])))
    if e.get("playbook"):
        champs.append(("Correction", f'<span class="mono">'
                                     f'{_e(e["playbook"])}</span> — réversible'))
    else:
        champs.append(("Correction", "manuelle (aucun playbook : la décision "
                                     "reste humaine)"))
    corps = "".join(f"<dt>{q}</dt><dd>{v}</dd>" for q, v in champs)
    return (f'<div class="constat {classe}">'
            f'<span class="etiquette">{index}. '
            f'{_e(LISIBLE.get(gravite, "non précisée"))}</span>'
            f'<h3>{_e(e.get("titre") or ref)}</h3>'
            f'<dl class="champ">{corps}</dl></div>')


def _correction(c: dict) -> str:
    etapes = []
    if c.get("simulation") is not None:
        etapes.append("simulation sans changement")
    if c.get("confirme"):
        etapes.append("confirmée par un humain")
    if c.get("applique"):
        etapes.append("appliquée")
    if c.get("verifie"):
        etapes.append("vérifiée par le playbook")
    if c.get("remesure"):
        etapes.append(f"re-mesurée par le code : {c['remesure']}")
    if c.get("revenu"):
        etapes.append("retour arrière effectué")
    if c.get("refus"):
        etapes.append(f"refusée : {c['refus']}")
    if c.get("annule"):
        etapes.append("annulée par l'opérateur")
    return (f'<div class="constat faible">'
            f'<h3>{_e(c.get("fiche"))} — {_e(c.get("controle"))}</h3>'
            f'<dl class="champ">'
            f'<dt>Playbook</dt><dd><span class="mono">'
            f'{_e(c.get("playbook"))}</span></dd>'
            f'<dt>Paramètres</dt><dd><span class="mono">'
            f'{_e(json.dumps(c.get("parametres") or {}, ensure_ascii=False))}'
            f'</span></dd>'
            f'<dt>Déroulé</dt><dd>{_e(" → ".join(etapes) or "aucune étape")}</dd>'
            f'<dt>Le</dt><dd>{_e(_date(c.get("quand")))}</dd>'
            f'</dl></div>')


def construire(audit: dict, tri: dict | None = None) -> str:
    """Le rapport complet, en HTML autonome."""
    t = tri or trier(audit)
    contexte = audit.get("contexte") or {}
    systeme = contexte.get("libelle") or " ".join(
        str(v) for v in (contexte.get("famille"), contexte.get("version")) if v
    ) or "non détecté"

    morceaux = [f"<!doctype html><html lang=fr><head><meta charset=utf-8>"
                f"<title>Rapport d'audit — {_e(audit.get('id'))}</title>"
                f"<style>{STYLE}</style></head><body><div class=page>"]

    morceaux.append(
        f"<h1>Rapport d'audit</h1>"
        f'<p class="sous">{_e(audit.get("id"))} — machine '
        f'<strong>{_e(audit.get("hote") or "non nommée")}</strong>, '
        f'système {_e(systeme)}<br>'
        f'périmètre : {_e(audit.get("perimetre") or "non défini")}<br>'
        f'commencé le {_e(_date(audit.get("debut")))}, '
        f'édité le {_e(_date(time.time()))}</p>')

    # --- Règle 2 : un audit vide ne ressemble pas à un audit propre --------
    if not t["mesure"]:
        morceaux.append(
            '<div class="avert"><strong>Aucune mesure n\'a été faite.</strong>'
            "<p>Cet audit ne contient aucun contrôle exécuté par le code. Il "
            "ne dit donc <em>rien</em> de l'état de la machine — ni en bien, "
            "ni en mal. Ce document n'est pas un résultat d'audit : c'est la "
            "trace d'une session sans mesure.</p></div>")

    morceaux.append("<h2>Synthèse</h2>")
    morceaux.append(_tuiles(t))
    comptes = par_gravite(t["ecarts"])
    if comptes:
        lignes = "".join(f"<tr><td>{_e(g)}</td><td class=nb>{n}</td></tr>"
                         for g, n in sorted(comptes.items(),
                                            key=lambda kv: _rang(kv[0])))
        morceaux.append(f"<table><tr><th>Gravité</th><th class=nb>Écarts "
                        f"ouverts</th></tr>{lignes}</table>")
    elif t["mesure"]:
        morceaux.append("<p>Aucun écart ouvert sur les contrôles mesurés. "
                        "Voir « Ce que cet audit ne dit pas » : cela ne "
                        "signifie pas que la machine est conforme sur tout.</p>")

    # --- Écarts ------------------------------------------------------------
    if t["ecarts"]:
        morceaux.append("<h2>Écarts constatés</h2>")
        morceaux.append("<p>Classés du plus grave au moins grave. Chacun porte "
                        "la commande qui l'a mesuré et la fiche qui l'a jugé : "
                        "tout est rejouable.</p>")
        morceaux += [_constat(e, i) for i, e in enumerate(t["ecarts"], 1)]

    # --- Corrections -------------------------------------------------------
    if t["corrections_appliquees"] or t["corrections_sans_suite"]:
        morceaux.append("<h2>Corrections</h2>")
        if t["corrections_appliquees"]:
            morceaux.append("<p>Chaque correction est passée par une "
                            "simulation, une confirmation humaine, une "
                            "vérification, puis une <strong>re-mesure par le "
                            "code</strong>. Toutes sont réversibles.</p>")
            morceaux += [_correction(c) for c in t["corrections_appliquees"]]
        if t["corrections_sans_suite"]:
            morceaux.append("<h3>Tentatives sans suite</h3>"
                            "<p class=note>Gardées : une correction refusée ou "
                            "annulée fait partie de l'histoire de la machine."
                            "</p>")
            morceaux += [_correction(c) for c in t["corrections_sans_suite"]]

    # --- Conformes ---------------------------------------------------------
    if t["conformes"]:
        morceaux.append("<h2>Contrôles conformes</h2>")
        morceaux.append("<ul class=serree>" + "".join(
            f'<li>{_e(c.get("titre") or c.get("fiche"))} '
            f'<span class="mono note">{_e(c.get("constate"))}</span></li>'
            for c in t["conformes"][:80]) + "</ul>")
        if len(t["conformes"]) > 80:
            morceaux.append(f'<p class=note>… et {len(t["conformes"]) - 80} '
                            f'autres.</p>')

    # --- Règle 3 : ce que l'audit ne dit pas -------------------------------
    morceaux.append("<h2>Ce que cet audit ne dit pas</h2>")
    morceaux.append(
        "<p>Cette section existe parce qu'un rapport qui ne montre que ce "
        "qu'il a trouvé laisse croire qu'il a tout regardé.</p>")
    if t["indetermines"]:
        morceaux.append(
            f'<p><strong>{len(t["indetermines"])} contrôle(s) indéterminé(s)'
            "</strong> : la machine n'a pas pu répondre (commande absente, "
            "droits insuffisants, composant non installé). Un indéterminé "
            "n'est ni une conformité ni un écart — c'est une question "
            "ouverte.</p>")
        morceaux.append("<ul class=serree>" + "".join(
            f'<li>{_e(c.get("titre") or c.get("fiche"))} — '
            f'<span class=note>{_e(c.get("motif") or c.get("constate"))}</span>'
            f"</li>" for c in t["indetermines"][:40]) + "</ul>")
    morceaux.append(
        "<ul class=serree>"
        "<li>Seuls les contrôles <strong>mesurés pendant cette session</strong> "
        "figurent ici ; la bibliothèque en contient bien davantage.</li>"
        "<li>Les contrôles du noyau et de systemd ne peuvent pas être jugés "
        "depuis un conteneur : ils demandent une machine réelle.</li>"
        "<li>Un audit de configuration ne dit rien des vulnérabilités des "
        "logiciels installés (c'est un autre outil), ni de ce qui s'est passé "
        "avant la mesure.</li>"
        "<li>Les corrections appliquées l'ont été à un instant donné : rien ne "
        "garantit qu'elles tiennent encore après une modification ultérieure de "
        "la machine.</li>"
        "</ul>")
    if t["hypotheses"]:
        morceaux.append(
            f'<p class=note>{len(t["hypotheses"])} affirmation(s) formulée(s) '
            "pendant la session n'ont pas été retenues : elles ne reposaient "
            "sur aucune observation. Elles ne figurent pas dans ce rapport.</p>")

    # --- Preuves -----------------------------------------------------------
    if t["lectures"] or t["preuves"]:
        morceaux.append("<h2>Preuves</h2>")
        if t["lectures"]:
            morceaux.append("<table><tr><th>Commande exécutée</th>"
                            "<th>Niveau</th><th>Quand</th></tr>" + "".join(
                f'<tr><td class="mono">{_e(c.get("commande"))}</td>'
                f'<td>{_e(c.get("niveau"))}</td>'
                f'<td>{_e(_date(c.get("quand")))}</td></tr>'
                for c in t["lectures"][:120]) + "</table>")
        if t["preuves"]:
            morceaux.append("<h3>Observations apportées par l'opérateur</h3>")
            morceaux += [f'<pre class="sortie mono">{_e(p)}</pre>'
                         for p in t["preuves"][:20]]

    morceaux.append(
        '<div class="pied">Rapport engendré par MAEL à partir de la mémoire '
        f'd\'audit <span class="mono">{_e(audit.get("id"))}.json</span>. '
        "Les verdicts sont produits par du code, pas par un modèle de langage ; "
        "chaque écart est rejouable avec la commande indiquée.</div>")

    morceaux.append("</div></body></html>")
    return "\n".join(morceaux)


# --------------------------------------------------------------------------- #
def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        prog="brain.rapport",
        description="Engendre le rapport d'audit remis au client.")
    ap.add_argument("audit", help="identifiant de l'audit (nom du fichier "
                                  "JSON sans l'extension)")
    ap.add_argument("--dossier", type=Path, default=None,
                    help="dossier des mémoires d'audit")
    ap.add_argument("--sortie", type=Path, default=None,
                    help="fichier HTML à écrire")
    args = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    dossier = args.dossier
    if dossier is None:
        # Django sait où sont les audits, mais le rapport doit pouvoir
        # s'engendrer sans lui : on remet un rapport depuis une archive, sur
        # une machine où le service n'est pas installé.
        try:
            from brain.memoire import dossier_par_defaut
            dossier = dossier_par_defaut()
        except Exception:                                   # noqa: BLE001
            dossier = Path(__file__).resolve().parent.parent / "reports" / "audits"

    audit = charger(args.audit, dossier)
    t = trier(audit)
    sortie = args.sortie or Path(dossier) / f"rapport-{args.audit}.html"
    sortie.parent.mkdir(parents=True, exist_ok=True)
    sortie.write_text(construire(audit, t), encoding="utf-8")

    print(f"rapport : {sortie}")
    print(f"  {len(t['ecarts'])} ecart(s) ouvert(s), "
          f"{len(t['ecarts_corriges'])} corrige(s), "
          f"{len(t['conformes'])} conforme(s), "
          f"{len(t['indetermines'])} indetermine(s)")
    if not t["mesure"]:
        print("  ATTENTION : aucune mesure dans cet audit — le rapport le dit.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
