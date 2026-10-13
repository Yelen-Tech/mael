"""L'AGENT sur un depot existant : du ticket au correctif VERIFIE.

Point 4.5 de la feuille de route « agent autonome » (12/10/2026). Il
enchaine les pieces du point 4, chacune deja eprouvee seule :

  1. INDEX et LOCALISATION (depot.py, localisation.py) — sans modele ;
  2. ENVIRONNEMENT du depot (essais_depot.py) — construit une fois ;
  3. TEST DE REPRODUCTION ecrit par le modele : un NOUVEAU fichier de test
     qui doit ECHOUER avant la correction (sinon il ne reproduit rien : il
     est refait une fois, puis abandonne — et le bilan le dit) ;
  4. AVANT : la reproduction et les tests lies aux fichiers designes ;
  5. CORRECTION par retouches ciblees (correctif.py) ;
  6. APRES : les memes tests. La reproduction doit passer, aucun test qui
     passait ne doit casser ; sinon la sortie des tests repart au modele
     (TOURS_VERIFICATION fois au plus) ;
  7. BILAN honnete : « resolu et verifie » seulement si la reproduction
     passe sans regression ; « corrige, non verifie » si les tests n'ont
     pas pu tourner ; jamais de reussite sans preuve.

Le correctif rendu (diff) ne contient que le code source ; le test de
reproduction est rendu a part (il reste dans le depot, utile au developpeur).
Memoire (8 Go) : le modele est decharge avant chaque passage des tests.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from . import correctif, depot, localisation
from . import essais_depot as ed
from .envergure import PETIT, Envergure
from .espace import CheminRefuse, Espace
from .extraction import extraire

TOURS_REPRODUCTION = 2
TOURS_VERIFICATION = 2
NOM_REPRODUCTION = "test_mael_ticket.py"

SYSTEME_REPRO = """Tu ecris UN test qui REPRODUIT le ticket dans un depot
existant : il doit ECHOUER sur le code actuel (le bug est la) et REUSSIR
quand le bug sera corrige. On te montre le ticket, les extraits du code
concerne, et un test existant du depot pour le style et les imports.
Reponds par UN seul bloc :

```python fichier=CHEMIN_DONNE
...le test (pytest)...
```

Regles : importe le code du depot comme le font ses tests existants ;
des fonctions test_... courtes ; une assertion qui verifie le comportement
ATTENDU decrit par le ticket ; aucun acces reseau ; ne modifie rien
d'autre."""


@dataclass
class Bilan:
    verdict: str = "echec"     # resolu-verifie | modifie-non-verifie | echec
    lieux: list = field(default_factory=list)
    reproduction: str = ""     # chemin du test ecrit par le modele
    reproduction_valide: bool = False
    tests: list[str] = field(default_factory=list)      # relances avant/apres
    avant: ed.Execution | None = None
    apres: ed.Execution | None = None
    comparaison: ed.Comparaison | None = None
    diff: str = ""             # le correctif (code source seulement)
    test_ajoute: str = ""      # le contenu du test de reproduction
    tours: int = 0
    notes: list[str] = field(default_factory=list)      # ce qui s'est passe
    securite: list[str] = field(default_factory=list)   # defauts deja la


def _dossier_des_tests(index: depot.Index, suite: depot.Suite | None,
                       lies: list[str]) -> str:
    """Ou poser le test de reproduction : a cote des tests lies, sinon dans
    le dossier de tests le plus courant du (sous-)projet."""
    if lies:
        return str(PurePosixPath(lies[0]).parent)
    base = suite.dossier if suite and suite.dossier else ""
    compte: dict[str, int] = {}
    for f, fi in index.fichiers.items():
        if fi.test and f.endswith(".py") and (not base or f.startswith(base
                                                                       + "/")):
            d = str(PurePosixPath(f).parent)
            compte[d] = compte.get(d, 0) + 1
    if compte:
        return max(compte, key=lambda d: (compte[d], -len(d)))
    return f"{base}/tests" if base else "tests"


def _suite_de(index: depot.Index, fichier: str) -> depot.Suite | None:
    """La suite du (sous-)projet qui contient le fichier : la plus profonde."""
    candidates = [s for s in index.suites
                  if not s.dossier or fichier.startswith(s.dossier + "/")]
    return max(candidates, key=lambda s: len(s.dossier), default=None)


def _relatif_a(suite: depot.Suite | None, chemin: str) -> str:
    if suite and suite.dossier and chemin.startswith(suite.dossier + "/"):
        return chemin[len(suite.dossier) + 1:]
    return chemin


def _echecs(ex: ed.Execution, tests: list[str], limite: int = 3000) -> str:
    """La partie utile de la sortie des tests pour le modele : les tests en
    echec et leurs traces, coupees."""
    if not ex or not ex.lance:
        return ""
    en_echec = [t for t, s in ex.statuts.items() if s in {"FAILED", "ERROR"}
                and (not tests or any(t.startswith(x) for x in tests))]
    morceaux = []
    for t in en_echec[:5]:
        nom = t.split("::")[-1]
        m = re.search(rf"_{{3,}} [^\n]*{re.escape(nom)}[^\n]* _{{3,}}\n"
                      rf"(.*?)(?=\n_{{3,}} |\n={{3,}} )", ex.sortie, re.S)
        morceaux.append(f"{t} : {ex.statuts[t]}\n"
                        + (m.group(1)[-800:] if m else ""))
    return "\n\n".join(morceaux)[:limite]


class _Journal:
    """Enveloppe du moteur : chaque echange est garde (ce que le modele a
    VRAIMENT repondu). Sans lui, un « aucun bloc lisible » ne s'explique pas
    (premier essai reel phi4-mini, 12/10/2026)."""

    def __init__(self, backend):
        self._backend = backend
        self.echanges: list[tuple[str, str, str]] = []   # etape, demande, reponse

    def completer(self, *, systeme, messages, role_modele="codeur", **kw):
        rep = self._backend.completer(systeme=systeme, messages=messages,
                                      role_modele=role_modele, **kw)
        etape = ("reproduction" if "REPRODUIT" in systeme else
                 "choix" if "CANDIDATS" in systeme else "correction")
        self.echanges.append((etape, messages[-1]["content"], rep.texte))
        return rep

    def __getattr__(self, nom):
        return getattr(self._backend, nom)

    def ecrire(self, chemin: Path) -> None:
        l = ["# Journal du ticket (echanges avec le modele)", ""]
        for n, (etape, demande, reponse) in enumerate(self.echanges, 1):
            l += [f"## {n}. {etape}", "", "### Demande", "", "````",
                  demande, "````", "", "### Reponse", "", "````", reponse,
                  "````", ""]
        try:
            chemin.parent.mkdir(parents=True, exist_ok=True)
            chemin.write_text("\n".join(l), encoding="utf-8")
        except OSError:
            pass


class AgentDepot:
    def __init__(self, backend, racine: Path | str, *,
                 envergure: Envergure | None = None, decharger=None,
                 executer: bool = True, reseau: bool = True,
                 choix: bool = False):
        self.backend = _Journal(backend)
        self.racine = Path(racine).resolve()
        self.espace = Espace(self.racine)
        self.envergure = envergure or PETIT
        self._envergure_connue = envergure       # None : moteur muet
        self.decharger = decharger
        self.executer = executer
        self.reseau = reseau
        # levier 3 : le modele departage les candidats (choix.py). Desactive
        # par defaut tant que le banc ne l'a pas valide (12/10/2026).
        self.choix = choix

    # ---------------------------------------------------------- les tests
    def _lancer(self, env, tests: list[str], suite) -> ed.Execution:
        if self.decharger is not None:
            self.decharger()                    # 8 Go : le modele OU Docker
        return ed.executer_tests(env, self.racine,
                                 [_relatif_a(suite, t) for t in tests])

    def _requalifier(self, ex: ed.Execution, suite) -> ed.Execution:
        """Les identifiants de pytest sont relatifs au dossier de la suite :
        on les remet relatifs au depot."""
        if suite and suite.dossier and ex.statuts:
            ex.statuts = {f"{suite.dossier}/{t}": s
                          for t, s in ex.statuts.items()}
        return ex

    # ---------------------------------------------------- la reproduction
    def _reproduire(self, ticket, index, lieux, env, suite, lies, b: Bilan):
        chemin = f"{_dossier_des_tests(index, suite, lies)}/{NOM_REPRODUCTION}"
        if (self.racine / chemin).exists():
            b.notes.append(f"{chemin} existe deja : pas de test de "
                           "reproduction (rien n'est ecrase)")
            return
        budget = self.envergure.budget_extraits
        extraits = correctif.choisir_extraits(self.racine, lieux,
                                              budget * 2 // 3, index)
        textes = {}
        for e in extraits:
            textes.setdefault(e.fichier, self.espace.lire(e.fichier))
        modele = ""
        if lies:
            try:
                modele = "\n".join(self.espace.lire(lies[0]).split("\n")[:50])
            except (OSError, CheminRefuse):
                modele = ""
        message = (correctif.message_initial(ticket, lieux, extraits, textes,
                                             budget // 3)
                   + (f"\n\nTEST EXISTANT ({lies[0]}, debut) :\n```python\n"
                      f"{modele}\n```" if modele else "")
                   + f"\n\nEcris le test dans : {chemin}")
        messages = [{"role": "user", "content": message}]
        for tour in range(1, TOURS_REPRODUCTION + 1):
            rep = self.backend.completer(
                systeme=SYSTEME_REPRO.replace("CHEMIN_DONNE", chemin),
                messages=messages, role_modele="codeur")
            fichiers = extraire(rep.texte).fichiers
            code = fichiers.get(chemin) or next(
                (v for k, v in fichiers.items() if k.endswith(".py")), "")
            if not code:
                retour = "aucun bloc ```python fichier=... lisible"
            else:
                self.espace.ecrire(chemin, code)
                b.reproduction = chemin
                b.test_ajoute = code
                if env is None or not env.pret:
                    b.notes.append("test de reproduction ecrit, NON execute "
                                   "(pas d'environnement)")
                    return
                ex = self._requalifier(self._lancer(env, [chemin], suite),
                                       suite)
                propres = {t: s for t, s in ex.statuts.items()
                           if t.startswith(chemin)}
                if any(s == "FAILED" for s in propres.values()):
                    b.reproduction_valide = True
                    b.notes.append(f"reproduction : {chemin} ECHOUE avant la "
                                   "correction, comme il le doit")
                    return
                if propres and all(s == "PASSED" for s in propres.values()):
                    retour = ("ton test REUSSIT sur le code actuel : il ne "
                              "reproduit pas le bug. L'assertion doit verifier "
                              "le comportement ATTENDU par le ticket.")
                else:
                    retour = ("ton test ne s'execute pas (erreur de collecte "
                              "ou d'import) :\n" + _echecs(ex, [chemin])
                              + "\n" + ex.sortie[-800:])
            if tour < TOURS_REPRODUCTION:
                messages += [{"role": "assistant", "content": rep.texte},
                             {"role": "user", "content": retour
                              + "\n\nRenvoie le test corrige."}]
        b.notes.append("aucun test ne reproduit le ticket (apres "
                       f"{TOURS_REPRODUCTION} essais) : la correction sera "
                       "jugee sur les tests existants seulement")
        if b.reproduction:
            try:
                (self.racine / b.reproduction).unlink()
            except OSError:
                pass
            b.reproduction, b.test_ajoute = "", ""

    # ----------------------------------------------------------- l'agent
    def traiter(self, ticket: str) -> Bilan:
        try:
            return self._traiter(ticket)
        finally:
            self.backend.ecrire(self.racine / ".mael" / "journal-ticket.md")

    def _traiter(self, ticket: str) -> Bilan:
        b = Bilan()
        index = depot.indexer(self.racine)
        lieux = localisation.localiser(index, ticket)
        if self.choix and lieux:
            from . import choix as choix_
            textes = {}
            for l in lieux[:choix_.CANDIDATS]:
                try:
                    textes[l.fichier] = self.espace.lire(l.fichier)
                except (OSError, CheminRefuse):
                    pass
            lieux, c = choix_.choisir(self.backend, ticket, lieux, textes)
            b.notes.append(
                "choix du modele parmi les candidats : "
                + (", ".join(c.fichiers) + (f" — {c.raison}" if c.raison
                                            else "")
                   if c.fichiers else f"aucun ({c.raison})"))
        b.lieux = lieux
        if not lieux:
            b.notes.append("la localisation n'a rien trouve : aucun endroit "
                           "a corriger")
            return b
        suite = _suite_de(index, lieux[0].fichier)
        sources = [l.fichier for l in lieux[:5]
                   if not index.fichiers[l.fichier].test]
        # les tests de TOUS les fichiers que le modele pourra modifier (essai
        # du 12/10 : sessions.py modifie, ses tests jamais relances)
        lies = ed.tests_lies(index, sources)
        env = None
        if self.executer and suite and ed.sorte(suite) == "python":
            env = ed.preparer(self.racine, suite, reseau=self.reseau)
            if not env.pret:
                b.notes.append(f"tests NON executes : {env.raison}")
        elif self.executer:
            b.notes.append("tests NON executes : "
                           + ("aucune suite de tests dans le depot" if not suite
                              else f"suite « {ed.sorte(suite) or '?'} » pas "
                              "encore prise en charge par l'agent"))
        b.notes += ed.limites(suite)
        self._reproduire(ticket, index, lieux, env, suite, lies, b)
        b.tests = ([b.reproduction] if b.reproduction else []) + lies
        if env and env.pret and b.tests:
            b.avant = self._requalifier(self._lancer(env, b.tests, suite),
                                        suite)
        # les originaux des fichiers de code, pour le diff final
        originaux: dict[str, str] = {}
        correcteur = correctif.Correcteur(self.backend, self.racine,
                                          envergure=self._envergure_connue)
        retour = ""
        for tour in range(1, TOURS_VERIFICATION + 1):
            b.tours = tour
            index = depot.indexer(self.racine)
            for l in lieux:
                if l.fichier not in originaux and l.fichier in index.fichiers \
                        and not index.fichiers[l.fichier].test:
                    originaux[l.fichier] = self.espace.lire(l.fichier)
            r = correcteur.corriger(ticket, index, lieux, retour=retour)
            if not r.appliquees and tour == 1:
                b.notes.append("aucune correction appliquee : "
                               + "; ".join(r.refus[:3]))
                break
            if not (env and env.pret and b.tests):
                break
            b.apres = self._requalifier(self._lancer(env, b.tests, suite),
                                        suite)
            b.comparaison = ed.comparer(b.avant, b.apres) if b.avant else None
            repro_ok = (not b.reproduction_valide) or all(
                s == "PASSED" for t, s in b.apres.statuts.items()
                if t.startswith(b.reproduction))
            sans_regression = b.comparaison is None or \
                b.comparaison.sans_regression
            if repro_ok and sans_regression:
                break
            retour = _echecs(b.apres, [b.reproduction] if not repro_ok else [])
            if b.comparaison and b.comparaison.regressions:
                retour += ("\n\nREGRESSIONS (passaient avant) : "
                           + ", ".join(b.comparaison.regressions[:5]))
        b.diff = correctif.diff(originaux, self.espace)
        b.securite = self._securite(originaux)
        b.verdict = self._verdict(b)
        return b

    def _securite(self, originaux: dict[str, str]) -> list[str]:
        """Les defauts bloquants des fichiers MODIFIES, tels qu'ils restent :
        le correctif n'a pu en introduire aucun (refuse par appliquer()) ;
        ceux-ci etaient deja la — le developpeur doit les connaitre."""
        from .juges import GRAVITE, juger_fichier
        out = []
        for f, avant in originaux.items():
            try:
                apres = self.espace.lire(f)
            except (OSError, CheminRefuse):
                continue
            if apres == avant:
                continue
            for d in juger_fichier(f, apres):
                if d.gravite is GRAVITE.BLOQUANT:
                    out.append(f"{f}:{d.ligne} — {d.message} ({d.norme}) — "
                               "deja present avant le correctif")
        return out

    @staticmethod
    def _verdict(b: Bilan) -> str:
        if not b.diff:
            return "echec"
        if b.apres is None or not b.apres.lance:
            return "modifie-non-verifie"
        repro_ok = b.reproduction_valide and all(
            s == "PASSED" for t, s in b.apres.statuts.items()
            if t.startswith(b.reproduction))
        sans_regression = b.comparaison is None or \
            b.comparaison.sans_regression
        if repro_ok and sans_regression:
            return "resolu-verifie"
        if not b.reproduction_valide and sans_regression:
            return "modifie-non-verifie"
        return "echec"


def rendre(b: Bilan) -> str:
    """Le bilan pour le developpeur."""
    titre = {"resolu-verifie": "RESOLU ET VERIFIE",
             "modifie-non-verifie": "MODIFIE, NON VERIFIE",
             "echec": "NON RESOLU"}[b.verdict]
    l = [f"# {titre}", ""]
    if b.lieux:
        l += ["## Ou MAEL a regarde", *(f"- {x.fichier} — {', '.join(x.raisons[:3])}"
                                         for x in b.lieux[:5]), ""]
    if b.reproduction:
        l += ["## Test de reproduction", f"- {b.reproduction} : "
              + ("echouait avant la correction" if b.reproduction_valide
                 else "n'a pas pu etre execute"), ""]
    if b.comparaison:
        c = b.comparaison
        l += ["## Tests (avant / apres)",
              f"- repares : {len(c.repares)}", f"- regressions : "
              f"{len(c.regressions)}" + (f" ({', '.join(c.regressions[:5])})"
                                         if c.regressions else ""),
              f"- toujours en echec : {len(c.toujours_en_echec)}", ""]
    if b.notes:
        l += ["## A savoir", *(f"- {n}" for n in b.notes), ""]
    l += ["## Securite", "- le correctif n'introduit aucun defaut que les "
          "juges de MAEL refusent (verifie a chaque modification)"]
    if b.securite:
        l += ["- defauts DEJA PRESENTS dans les fichiers modifies (a "
              "traiter a part) :", *(f"  - {s}" for s in b.securite[:10])]
    l.append("")
    if b.diff:
        l += ["## Correctif", "```diff", b.diff.rstrip(), "```"]
    return "\n".join(l) + "\n"
