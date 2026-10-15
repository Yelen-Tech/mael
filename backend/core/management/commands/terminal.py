"""IA en terminal, experte en audit et cybersecurite (etape 1).

    python manage.py terminal
    python manage.py terminal --executer          # execute vraiment les lectures
    python manage.py terminal --perimetre "10.0.0.0/24, exemple.fr"

Boucle de conversation avec le modele local (Ollama). Le modele PROPOSE des
commandes ; ce programme les CLASSE (brain.garde) et decide :

  LECTURE      -> executee (si --executer), resultat renvoye au modele
  MODIFICATION -> montree, l'humain valide (o/n) avant execution
  INTERDIT     -> bloquee, jamais executee

Un constat n'est retenu que s'il repose sur une observation (commande
executee ou /preuve de l'humain) ; sinon c'est une hypothese, et le modele est
renvoye observer (brain.fondement).

Avant le classement, la commande est comparee aux fiches de la bibliotheque
(brain.bibliotheque.verification). Une option ou sous-commande absente des
fiches renvoie UNE demande de correction au modele ; s'il maintient sa
commande, elle est marquee « non verifiee » et l'humain valide meme une lecture.

Apres chaque lecture executee, le CODE compare la sortie aux fiches
(brain.bibliotheque.ecarts, etape 5) : conforme / ecart / indetermine. Le
modele recoit ces verdicts et n'explique que les ecarts ; /ecarts les liste.

/corriger boucle la correction (etape 2.6) : playbook scelle, parametres de
la fiche, simulation obligatoire, confirmation par code, application,
verification, RE-MESURE par le code ; retour arriere automatique en cas
d'echec. /revenir annule une correction appliquee.

Sans --executer, rien ne tourne vraiment : le programme montre le classement
et la commande exacte. Utile pour eprouver le mode d'emploi sans machine cible.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time

from django.core.management.base import BaseCommand

from brain import (
    animation,
    bibliotheque,
    console,
    fondement,
    interface,
    mode_emploi,
    modeles,
    reglages,
)
from brain import contexte as ctx_mod
from brain.backends.base import obtenir_backend
from brain.bibliotheque import ecarts, verification
from brain.garde import NIVEAU, classer
from brain.memoire import MemoireAudit, dossier_par_defaut

COULEURS = {
    NIVEAU.LECTURE: "\033[32m",       # vert
    NIVEAU.MODIFICATION: "\033[33m",  # jaune
    NIVEAU.INTERDIT: "\033[31m",      # rouge
}
RESET = "\033[0m"
GRIS = "\033[90m"
GRAS = "\033[1m"


def _bash() -> str | None:
    """Bash reel (Git Bash de preference ; le bash de WSL sans distro echoue)."""
    for c in (r"C:\Program Files\Git\bin\bash.exe",
              r"C:\Program Files\Git\usr\bin\bash.exe"):
        if os.path.exists(c):
            return c
    return shutil.which("bash")


def _niveau(texte: str) -> tuple | None:
    """« 1:intermediaire » -> (1, "intermediaire") ; « tout » -> None."""
    from brain.bibliotheque.taxonomie import NIVEAUX_ANSSI
    if (texte or "").strip().lower() in {"tout", "tous", "aucun"}:
        return None
    cis, _, anssi = texte.partition(":")
    anssi = anssi.strip().lower() or None
    if anssi is not None and anssi not in NIVEAUX_ANSSI:
        raise SystemExit(f"--niveau : ANSSI « {anssi} » inconnu "
                         f"({', '.join(NIVEAUX_ANSSI)})")
    return (int(cis) if cis.strip() else None, anssi)


class Command(BaseCommand):
    help = "IA en terminal, experte en audit et cybersecurite."

    def add_arguments(self, parser):
        parser.add_argument("--executer", action="store_true",
                            help="Executer reellement les commandes de lecture "
                                 "et les modifications validees.")
        parser.add_argument("--perimetre", default=None,
                            help="Perimetre autorise (machines/adresses).")
        parser.add_argument("--role", default=None,
                            help="Role de modele (defaut : reglage « role », "
                                 "expert a l'origine).")
        parser.add_argument("--modele", default=None,
                            help="Modele Ollama pour cette session seulement, "
                                 "sans substitution s'il manque (defaut : "
                                 "reglage « modele », puis choix automatique "
                                 "parmi les modeles installes).")
        parser.add_argument("--audit", default=None,
                            help="Identifiant d'audit a reprendre (defaut : "
                                 "nouvel audit horodate). La memoire vit dans "
                                 "reports/audits/<id>.json.")
        parser.add_argument("--systeme", default=None,
                            help="Systeme audite si on ne peut pas le "
                                 "detecter, ex. ubuntu:22.04 ou rhel:9.")
        parser.add_argument("--profil", default=None,
                            choices=["court", "complet"],
                            help="Profil du mode d'emploi (defaut : reglage "
                                 "BRAIN_PROFIL). 'court' = plus rapide sans GPU.")
        parser.add_argument("--niveau", default=None,
                            help="Niveau de conformite mesure par le code : "
                                 "<cis>:<anssi>, ex. 1:intermediaire, "
                                 "2:renforce, ou « tout ».")
        # --- apparence (voir brain/console.py et brain/reglages.py) ---
        parser.add_argument("--theme", default=None, choices=["sombre", "clair"],
                            help="Couleurs du terminal.")
        parser.add_argument("--sans-couleur", action="store_true",
                            dest="sans_couleur",
                            help="Texte brut, sans aucune couleur (utile pour "
                                 "un journal ou un lecteur d'ecran).")
        parser.add_argument("--largeur", type=int, default=None,
                            dest="largeur_max",
                            help="Largeur maximale du texte, en colonnes.")

    # ------------------------------------------------------------ apparence
    def _appliquer_apparence(self):
        """Construit le style et coupe les couleurs si besoin.

        Les constantes de module servent partout dans ce fichier : on les
        vide d'un coup plutot que de semer des « if couleur » a chaque
        ligne. Une sortie redirigee (journal, tube) ne recoit jamais de
        codes d'echappement."""
        global RESET, GRIS, GRAS, COULEURS
        # Sous Windows, vt_pret() active le mode « terminal virtuel » ; si la
        # console le refuse, on coupe les couleurs plutot que d'imprimer les
        # codes en clair (« ←[94m »…). Sans effet hors Windows.
        couleur = (bool(self.reglages["couleurs"])
                   and console.couleurs_possibles() and animation.vt_pret())
        self.style = console.Style(self.reglages["theme"], couleur)
        self.largeur = console.largeur(self.reglages["largeur_max"])
        if not couleur:
            RESET = GRIS = GRAS = ""
            COULEURS = dict.fromkeys(COULEURS, "")
        else:
            RESET, GRIS, GRAS = console.RESET, self.style.discret, self.style.gras
            COULEURS = {NIVEAU.LECTURE: self.style.lecture,
                        NIVEAU.MODIFICATION: self.style.attention,
                        NIVEAU.INTERDIT: self.style.danger}
        # Un changement de theme en cours de session doit suivre dans la
        # barre de saisie, pas seulement au prochain demarrage.
        if getattr(self, "interface", None) is not None:
            self.interface.style = self.style

    def _attente(self):
        """L'indicateur pendant que le modele reflechit : l'orbe 3D si le
        reglage « animation » le permet ET si la console sait interpreter
        les sequences ANSI (vt_pret) — sinon l'indicateur simple, qui
        n'ecrit qu'une ligne. Les deux se taisent hors d'un terminal.
        En mode interface, l'orbe est reduit pour rester dans la zone."""
        if self.reglages.get("animation") and animation.vt_pret():
            hauteur = animation.HAUTEUR
            if getattr(self, "interface", None) is not None:
                hauteur = min(hauteur, max(5, self.interface.bas_zone - 2))
            return animation.Orbe("MAEL reflechit", self.style,
                                  actif=self.reglages["attente"],
                                  hauteur=hauteur)
        return console.Attente("MAEL reflechit", self.style,
                               actif=self.reglages["attente"])

    def _saisir(self) -> str:
        """La saisie de l'utilisateur.

        En mode interface : la barre fixe en bas de l'ecran, et la ligne
        tapee est re-ecrite dans la zone pour que l'historique la garde.
        En mode classique : un cadre qui s'ouvre, recoit la ligne, puis se
        referme. « vous » porte la couleur de l'humain ; MAEL a la sienne."""
        if getattr(self, "interface", None) is not None:
            entree = self.interface.lire().strip()
            if entree:
                self.stdout.write(self.style.teinte(f"vous › {entree}",
                                                    self.style.utilisateur))
            return entree
        # Mode classique (console sans ANSI, ou reglage interface=non) :
        # une invite simple, une seule ligne — aucun cadre a empiler.
        entree = input(f"\n{self.style.utilisateur}vous ›{RESET} ").strip()
        return entree

    def _demander(self, prompt: str) -> str:
        """Une confirmation (o/N, code) : dans la barre en mode interface,
        en ligne simple sinon."""
        if getattr(self, "interface", None) is not None:
            return self.interface.lire(prompt).strip()
        return input(prompt).strip()

    def _historique(self):
        """Fleches haut/bas d'une session a l'autre, quand c'est possible.

        readline n'existe pas dans la bibliotheque standard de Windows : sans
        lui on s'en passe, en silence -- une commodite absente ne doit pas
        ressembler a une panne."""
        if not self.reglages["historique"]:
            return
        try:
            import atexit
            import readline
        except ImportError:
            return
        chemin = reglages.dossier() / "historique"
        try:
            chemin.parent.mkdir(parents=True, exist_ok=True)
            if chemin.exists():
                readline.read_history_file(str(chemin))
            readline.set_history_length(500)
            atexit.register(readline.write_history_file, str(chemin))
        except OSError:
            pass          # disque en lecture seule, dossier interdit : tant pis

    # --------------------------------------------------------------- boucle
    def handle(self, *args, **opts):
        # Console Windows en cp1252 : on force l'UTF-8 tolerant pour ne jamais
        # planter sur la sortie d'une commande (accents, caracteres speciaux).
        for flux in (sys.stdout, sys.stderr):
            try:
                flux.reconfigure(encoding="utf-8", errors="replace")
            except (AttributeError, ValueError):
                pass

        # Reglages de l'utilisateur (~/.mael/reglages.json), puis la ligne
        # de commande par-dessus : ce qu'on tape maintenant gagne toujours
        # sur ce qu'on a enregistre avant.
        self.reglages, plaintes = reglages.charger()
        self.reglages = reglages.appliquer_options(self.reglages, {
            "profil": opts.get("profil"), "niveau": opts.get("niveau"),
            "perimetre": opts.get("perimetre"), "role": opts.get("role"),
            "executer": opts.get("executer"), "theme": opts.get("theme"),
            "largeur_max": opts.get("largeur_max"),
        })
        if opts.get("sans_couleur"):
            self.reglages["couleurs"] = False
        self._appliquer_apparence()
        for plainte in plaintes:
            self.stderr.write(f"  ! reglages : {plainte}")

        backend = obtenir_backend()
        role = self.reglages["role"]
        # Le modele ecrit dans la configuration n'est qu'une intention : ce qui
        # tourne depend de ce que l'utilisateur a REELLEMENT installe. S'il
        # manque, brain/modeles.py choisit parmi ce qui est la ou dit la
        # commande a copier -- jamais une trace d'appel Python.
        impose = opts.get("modele")
        if impose:
            # Ce qu'on tape maintenant gagne sur ce qui est enregistre, et rien
            # ne lui est substitue en silence : le backend doit voir le meme.
            from django.conf import settings as _reglages_projet
            _reglages_projet.BRAIN["MODELES"][role] = impose
            _reglages_projet.BRAIN["MODELE_EXACT"] = True
        try:
            choix_modele = modeles.resoudre(
                role, valeurs=self.reglages, enregistrer=not impose)
        except modeles.ProblemeDeModele as souci:
            self.stderr.write("\n" + souci.humain() + "\n")
            return
        modele = self.modele = choix_modele.nom
        for message in choix_modele.messages:
            self.stderr.write(f"  ! {message}")
        self.executer = self.reglages["executer"]
        self.bash = _bash() if self.executer else None
        self.perimetre = self.reglages["perimetre"] or None
        self.hote = os.environ.get("COMPUTERNAME") or "poste-audit"
        from django.conf import settings
        self.profil = self.reglages["profil"]
        self.derniere_fiche = None   # continuite de la recuperation (2.2)
        # Budget du savoir injecte : plus serre en profil court (machine lente).
        self.budget_savoir = settings.BRAIN.get(
            "BUDGET_SAVOIR", 700 if self.profil == "court" else 1200)
        self.savoir = None
        self.niveau = _niveau(self.reglages["niveau"])

        # Memoire d'audit : un fichier JSON par audit. On reprend s'il existe.
        identifiant = opts["audit"] or time.strftime("audit-%Y%m%d-%H%M%S")
        self.memoire = MemoireAudit.ouvrir(
            identifiant, dossier_par_defaut(),
            perimetre=self.perimetre, hote=self.hote,
        )

        self.contexte = self._etablir_contexte(opts["systeme"])
        self._historique()

        # Le modele se charge et LIT le mode d'emploi pendant que l'utilisateur
        # regarde l'ecran d'accueil et tape sa premiere question. Sur une
        # machine sans carte graphique, c'est presque une minute d'attente qui
        # disparait (mesure du 22/09 : 25,7 s de chargement + 27,7 s de
        # lecture du prompt, contre 4 s quand tout est deja chaud). Rien n'en
        # depend : si ce prechauffage echoue, la premiere question coute ce
        # qu'elle coutait avant.
        modeles.prechauffer(modele, mode_emploi.construire(
            perimetre=self.perimetre, hote=self.hote,
            etat=self.memoire.resume_pour_prompt(), profil=self.profil))

        # L'interface plein ecran (ecran alterne, conversation qui defile,
        # barre de saisie fixe en bas) si la console sait faire ; sinon le
        # mode classique, ligne a ligne, reste ce qu'il a toujours ete.
        self.interface = None
        if (self.reglages.get("interface") and self.style.couleur
                and animation.vt_pret()):
            self.interface = interface.Interface(self.style)
        stdout_direct = self.stdout
        try:
            if self.interface:
                self.interface.__enter__()
                self.stdout = interface.FluxZone(self.interface)
            self._entete(modele, self.executer, self.bash, self.perimetre)
            self._boucle(backend, role)
        finally:
            if self.interface:
                self.stdout = stdout_direct
                self.interface.__exit__(None, None, None)
            self.stdout.write(GRIS + "Fin de session." + RESET)

    # ------------------------------------------------------------- boucle
    def _boucle(self, backend, role):
        messages: list[dict] = []

        while True:
            try:
                entree = self._saisir()
            except (EOFError, KeyboardInterrupt):
                return
            if not entree:
                continue
            if entree in {"/quit", "/q", "exit"}:
                return
            if entree in {"/etat", "/état", "/e"}:
                self.stdout.write("\n" + self.memoire.resume_humain())
                continue
            if entree.startswith("/preuve"):
                texte = entree[len("/preuve"):].strip()
                if not texte:
                    self.stdout.write("Usage : /preuve <observation, ex. "
                                      "sortie de commande collee>")
                    continue
                self.memoire.ajouter_preuve(texte)
                self.stdout.write(f"{GRIS}  preuve enregistree.{RESET}")
                self._annoncer_confirmes()
                continue
            if entree in {"/ecarts", "/écarts"}:
                self._afficher_mesures()
                continue
            if entree.startswith("/corriger"):
                self._corriger(entree[len("/corriger"):].strip())
                continue
            if entree.startswith("/revenir"):
                self._revenir(entree[len("/revenir"):].strip())
                continue
            if entree in {"/contexte", "/systeme"}:
                self.stdout.write("\nsysteme : " + self.contexte.libelle())
                continue
            if entree == "/detecter":
                self.contexte = self._etablir_contexte(None, forcer=True)
                self.stdout.write("\nsysteme : " + self.contexte.libelle())
                continue
            if entree.startswith("/rapport"):
                self._rapport(entree[len("/rapport"):].strip())
                continue
            if entree.startswith("/audit"):
                # le CODE audite (outils en conteneur + juges) ; le modele
                # recoit le resume et explique, il ne decide rien (13/10)
                entree = self._audit_depot(entree[len("/audit"):].strip())
                if not entree:
                    continue
            if entree in {"/aide", "/help", "/?", "/h"}:
                self._aide()
                continue
            if entree.startswith(("/parametres", "/paramètres", "/reglages",
                                  "/réglages")):
                self._parametres(entree.split(" ", 1)[1].strip()
                                 if " " in entree else "")
                continue
            if entree in {"/effacer", "/nouveau"}:
                messages.clear()
                self.savoir = None
                self.derniere_fiche = None
                self.stdout.write(f"{GRIS}  conversation effacee. L'audit "
                                  f"« {self.memoire.id} » et ses constats, "
                                  f"eux, sont gardes.{RESET}")
                continue
            if entree in {"/fiches", "/f"}:
                fiches = bibliotheque.toutes()
                self.stdout.write(f"\n{len(fiches)} fiche(s) dans la bibliotheque :")
                for f in fiches:
                    self.stdout.write(f"  - {f.id} ({f.domaine}) : {f.titre}")
                continue

            # Bibliotheque (recuperation, etape 2.2) : trouver la/les fiches
            # pertinentes, avec continuite (une relance garde le sujet du tour
            # precedent). L'IA lit un savoir verifie au lieu d'inventer.
            # Injection ciblee (etape 4) : 1 fiche principale compacte + fiches
            # proches en une ligne, sous un budget en jetons.
            from brain.bibliotheque import injection, recherche
            trouvailles, themes, _ = recherche.chercher(
                entree, contexte=self.contexte, n=6)
            if trouvailles:
                fiches = [t.fiche for t in trouvailles]
                source = trouvailles          # avec scores : tri des proches
            else:                             # continuite du tour precedent
                fiches, _ = bibliotheque.recuperer(
                    entree, precedent=getattr(self, "derniere_fiche", None),
                    contexte=self.contexte)
                source = fiches
            savoir = injection.construire(source, self.contexte, themes,
                                          budget_jetons=self.budget_savoir)
            self.savoir = savoir.texte or None
            # Connaissances generales (etape 2 du plan) : savoir de fond
            # (langages, sciences...) ajoute sobrement au savoir d'audit. Le
            # bloc le dit lui-meme : ce n'est PAS un constat, et rien ici ne
            # modifie un verdict — le code decide, comme partout.
            from brain import connaissances
            bloc = connaissances.pour_prompt(entree)
            if bloc:
                self.savoir = ((self.savoir + "\n\n" + bloc)
                               if self.savoir else bloc)
                self.stdout.write(f"{GRIS}  (connaissance — savoir general "
                                  f"injecte){RESET}")
            # Etape 10 : un exemple de reference (ton et conduite), borne en
            # jetons, etiquette comme tel — jamais des faits de l'audit.
            from brain import dialogues
            exemple = dialogues.pour_prompt(entree)
            if exemple:
                self.savoir = ((self.savoir + "\n\n" + exemple)
                               if self.savoir else exemple)
                self.stdout.write(f"{GRIS}  (exemple de reference — ton, "
                                  f"pas des faits){RESET}")
            self.derniere_fiche = fiches[0] if fiches else self.derniere_fiche
            if fiches:
                coupe = (f", reduit : {', '.join(savoir.retraits)}"
                         if savoir.retraits else "")
                self.stdout.write(f"{GRIS}  (bibliotheque — {fiches[0].titre} ; "
                                  f"{len(savoir.proches)} fiche(s) proche(s) ; "
                                  f"~{savoir.jetons} jetons{coupe}){RESET}")

            messages.append({"role": "user", "content": entree})
            self._tour(backend, role, messages)

    # ---------------------------------------------------------- un echange
    def _tour(self, backend, role, messages):
        """Un echange complet : le modele parle, propose peut-etre une
        commande ; on la traite ; on reboucle tant qu'il enchaine.

        Le systeme est reconstruit a chaque appel : la memoire d'audit (etape,
        constats deja etablis) y est reinjectee pour que le modele sache
        toujours ou il en est."""
        deja_vues: set[str] = set()  # anti-repetition dans le tour
        correction_demandee = False  # une seule relance de verification par tour
        relance_fondement = False    # une seule relance « observe d'abord »
        for _ in range(6):  # borne dure : pas de boucle infinie d'outils
            systeme = mode_emploi.construire(
                perimetre=self.perimetre, hote=self.hote,
                etat=self.memoire.resume_pour_prompt(), profil=self.profil,
                savoir=getattr(self, "savoir", None),
            )
            t0 = time.perf_counter()
            try:
                # Pas d'appel d'outil natif : un petit modele le rate quand le
                # prompt grossit (reponse vide). On passe par un bloc ```bash,
                # deterministe a extraire. Cf. _extraire_bloc.
                with self._attente():
                    rep = backend.completer(
                        systeme=systeme, messages=messages, role_modele=role,
                    )
            except Exception as exc:  # noqa: BLE001
                # Le diagnostic est dans brain/modeles.py : un modele LENT
                # n'est pas un modele injoignable, et chaque cas a sa
                # conduite a tenir (epreuve L3 du 22/09).
                self.stderr.write("\n" + modeles.expliquer_echec(
                    exc, modele=getattr(self, "modele", ""),
                    profil=getattr(self, "profil", "")))
                return
            dt = int((time.perf_counter() - t0) * 1000)

            if rep.texte.strip():
                # La reponse est mise en page ici (largeur du terminal, listes,
                # blocs de code jamais replies) : une reponse longue doit
                # rester lisible ET recopiable telle quelle.
                self.stdout.write(f"\n{self.style.assistant}mael ›{RESET}")
                self.stdout.write(console.rendre(
                    rep.texte.strip(), self.style,
                    largeur_utile=self.largeur, retrait="  "))
                if self.reglages["details"]:
                    self.stdout.write(f"{GRIS}  ({rep.modele}, {dt} ms){RESET}")
                messages.append({"role": "assistant", "content": rep.texte})
                # Memoire : detecter et enregistrer les constats formules,
                # en jugeant s'ils reposent sur une observation.
                n = self.memoire.enregistrer_constats(
                    rep.texte, juge=fondement.juge_pour(self.memoire))
                if n:
                    self.stdout.write(f"{GRIS}  ({n} constat(s) memorise(s) ou "
                                      f"requalifie(s) — etape : "
                                      f"{self.memoire.etape}){RESET}")
                for c in self.memoire.derniers_non_fondes:
                    self.stdout.write(
                        f"  {COULEURS[NIVEAU.MODIFICATION]}[hypothese non "
                        f"fondee]{RESET} {c.resume[:90]} "
                        f"{GRIS}— {c.fondement}{RESET}")

            # Le modele peut proposer via l'outil, ou en bloc ```bash.
            propositions = list(rep.appels_outils)
            if not propositions:
                bloc = self._extraire_bloc(rep.texte)
                if bloc:
                    propositions = [{"nom": "proposer_commande",
                                     "arguments": {"commande": bloc, "but": ""}}]

            if (self.memoire.derniers_non_fondes and not propositions
                    and not relance_fondement):
                # Constat affirme sans observation et aucune commande
                # proposee : on renvoie le modele observer, une fois.
                relance_fondement = True
                sujets = "; ".join(c.resume[:80]
                                   for c in self.memoire.derniers_non_fondes)
                messages.append({"role": "user", "content": (
                    "[verification] Tu as presente comme un constat ce qui "
                    f"n'a pas ete observe ({sujets}). Aucune commande n'a ete "
                    "executee sur ce sujet : c'est une hypothese. Ne conclus "
                    "pas. Propose d'abord UNE commande de lecture dans un bloc "
                    "```bash pour le verifier.")})
                self.stdout.write(f"{GRIS}  (modele renvoye observer avant "
                                  f"de conclure){RESET}")
                continue

            if not propositions:
                return  # tour termine : reponse en texte, rien a executer

            nouvelles = 0
            a_corriger = False
            for appel in propositions:
                if appel.get("nom") != "proposer_commande":
                    continue
                cmd = (appel.get("arguments") or {}).get("commande", "")
                but = (appel.get("arguments") or {}).get("but", "")
                cle = " ".join(cmd.lower().split())
                if not cle or cle in deja_vues:
                    continue  # commande vide ou deja proposee dans ce tour
                nouvelles += 1

                # Anti-invention (2.3) : le code compare aux fiches. Premiere
                # derive -> on renvoie les commandes verifiees au modele, sans
                # rien executer. La commande n'est pas marquee « vue » : s'il
                # la maintient, elle sera traitee (avec validation humaine).
                verif = verification.verifier(cmd)
                if (verif.statut is verification.STATUT.NON_VERIFIE
                        and not correction_demandee):
                    correction_demandee = True
                    a_corriger = True
                    self.stdout.write(f"\n  $ {GRAS}{cmd}{RESET}")
                    self.stdout.write(f"  {COULEURS[NIVEAU.MODIFICATION]}"
                                      f"[non verifiee]{RESET} {verif.motif}")
                    self.stdout.write(f"{GRIS}  (correction demandee au "
                                      f"modele, rien n'est execute){RESET}")
                    messages.append({"role": "user",
                                     "content": verif.message_correction()})
                    continue

                deja_vues.add(cle)
                observation = self._traiter_commande(cmd, but, verif)
                messages.append({"role": "user",
                                 "content": f"[resultat] {observation}"})

            if nouvelles == 0:
                return  # rien de neuf : on n'entretient pas la boucle
            if a_corriger:
                continue  # le modele reformule, meme en simulation
            if not self.executer:
                # En simulation, aucune commande n'a produit de vrai resultat :
                # le modele n'a rien de nouveau a analyser. On s'arrete la.
                self.stdout.write(GRIS + "  (simulation : relancer avec "
                                  "--executer pour poursuivre sur les "
                                  "resultats reels)" + RESET)
                return
            # En reel, on reboucle : le modele lit le resultat et continue.
        self.stderr.write(GRIS + "  (limite d'enchainement atteinte)" + RESET)

    # --------------------------------------------------- classement + exec
    def _traiter_commande(self, cmd, but, verif=None) -> str:
        v = classer(cmd)
        verif = verif or verification.verifier(cmd)
        non_verifiee = verif.statut is verification.STATUT.NON_VERIFIE
        couleur = COULEURS[v.niveau]
        self.stdout.write("")
        self.stdout.write(console.regle("commande proposee", self.style,
                                        self.largeur))
        if but:
            self.stdout.write(f"{GRIS}  but : {but}{RESET}")
        self.stdout.write(f"  $ {GRAS}{cmd}{RESET}")
        self.stdout.write(f"  {couleur}[{v.niveau.value}]{RESET} {v.motif}")
        couleur_verif = (COULEURS[NIVEAU.MODIFICATION] if non_verifiee
                         else GRIS)
        self.stdout.write(f"  {couleur_verif}[{verif.statut.value}]{RESET} "
                          f"{GRIS}{verif.motif}{RESET}")

        # Trace mnesique : la commande est memorisee, executee ou non. C'est
        # elle qui fait avancer l'etape de l'audit (le code decide).
        def _memoriser(executee: bool):
            self.memoire.enregistrer_commande(
                cmd, v.niveau.value, but=but, executee=executee,
                verification=verif.statut.value)

        if v.niveau is NIVEAU.INTERDIT:
            self.stdout.write(f"  {couleur}Commande bloquee. Non executee.{RESET}")
            _memoriser(False)
            return f"BLOQUEE ({v.motif}) : commande refusee, non executee."

        if v.niveau is NIVEAU.MODIFICATION:
            if not self.executer:
                _memoriser(False)
                return ("MODIFICATION non executee (mode simulation). "
                        "En reel, l'humain validerait avant execution.")
            rep = self._demander(f"  {COULEURS[NIVEAU.MODIFICATION]}Valider "
                                 f"cette modification ? [o/N]{RESET} ").lower()
            if rep not in {"o", "oui", "y"}:
                _memoriser(False)
                return "REFUSEE par l'humain : modification non appliquee."
            sortie = self._executer(cmd, self.bash)
            _memoriser(True)
            return sortie

        # LECTURE
        if not self.executer:
            _memoriser(False)
            return ("LECTURE non executee (mode simulation ; relancer avec "
                    "--executer pour voir le resultat reel).")
        if non_verifiee:
            # Le modele a maintenu une option absente des fiches : meme une
            # lecture passe par l'humain.
            rep = self._demander(f"  {COULEURS[NIVEAU.MODIFICATION]}Commande "
                                 f"non verifiee par les fiches. L'executer ? "
                                 f"[o/N]{RESET} ").lower()
            if rep not in {"o", "oui", "y"}:
                _memoriser(False)
                return ("REFUSEE par l'humain : commande non verifiee, non "
                        "executee. Utilise une commande des fiches.")
        sortie = self._executer(cmd, self.bash)
        _memoriser(True)
        sortie += self._evaluer(cmd)
        self._annoncer_confirmes()
        return sortie

    # ------------------------------------------------ etape 5 : le code juge
    def _evaluer(self, cmd) -> str:
        """Verdicts du code sur la sortie standard de la commande. Rend le
        texte a joindre au resultat pour le modele ("" si aucune fiche ne
        sait juger cette commande)."""
        verdicts = ecarts.evaluer_commande(
            cmd, getattr(self, "_stdout", ""), self.contexte,
            niveau=getattr(self, "niveau", ecarts.NIVEAU_DEFAUT))
        if not verdicts:
            return ""
        bilan = self.memoire.enregistrer_verdicts(verdicts)
        self.stdout.write(console.regle("mesures du code", self.style,
                                        self.largeur))
        rouge, vert = COULEURS[NIVEAU.INTERDIT], COULEURS[NIVEAU.LECTURE]
        conformes = 0
        for v in verdicts:
            if v.statut is ecarts.STATUT.ECART:
                self.stdout.write(f"  {rouge}[ecart {v.gravite}]{RESET} "
                                  f"{v.titre} {GRIS}— lu : {v.constate}{RESET}")
            elif v.statut is ecarts.STATUT.INDETERMINE:
                self.stdout.write(f"  {GRIS}[indetermine] {v.titre} — "
                                  f"{v.motif}{RESET}")
            else:
                conformes += 1
        if conformes:
            self.stdout.write(f"  {vert}[conforme]{RESET} {conformes} "
                              f"controle(s)")
        for c in bilan["corriges"]:
            self.stdout.write(f"  {vert}[corrige]{RESET} {c.resume[:90]}")
        return "\n\n" + ecarts.message_modele(verdicts)

    def _afficher_mesures(self):
        mesures = self.memoire.evaluations
        if not mesures:
            self.stdout.write("\nAucune mesure du code pour l'instant (les "
                              "lectures des fiches sont jugees une fois "
                              "executees).")
            return
        ordre = {"ecart": 0, "indetermine": 1, "conforme": 2}
        self.stdout.write(f"\n{len(mesures)} controle(s) mesure(s) :")
        for m in sorted(mesures.values(),
                        key=lambda m: (ordre.get(m["statut"], 3), m["titre"])):
            detail = m["motif"] if m["statut"] == "indetermine" else \
                f"lu : {m['constate']}"
            g = f" {m['gravite']}" if m["statut"] == "ecart" else ""
            self.stdout.write(f"  [{m['statut']}{g}] {m['titre']} "
                              f"{GRIS}— {detail}{RESET}")

    # ------------------------------------------ etape 2.6 : boucle de correction
    _RANG = {"critique": 0, "elevee": 1, "élevée": 1, "moyenne": 2, "faible": 3}

    def _corrigeables(self) -> list[dict]:
        return sorted((m for m in self.memoire.evaluations.values()
                       if m.get("statut") == "ecart" and m.get("playbook")),
                      key=lambda m: (self._RANG.get(m.get("gravite"), 9),
                                     m["titre"]))

    def _rapport(self, argument: str):
        """Le document qu'on remet au client, depuis la memoire de l'audit."""
        from pathlib import Path

        from brain import rapport as rapport_mod
        sortie = Path(argument) if argument else (
            self.memoire.dossier / f"rapport-{self.memoire.id}.html")
        audit = json.loads(self.memoire.fichier.read_text(encoding="utf-8"))
        tri = rapport_mod.trier(audit)
        sortie.parent.mkdir(parents=True, exist_ok=True)
        sortie.write_text(rapport_mod.construire(audit, tri), encoding="utf-8")
        self.stdout.write(f"\n{GRAS}rapport{RESET} : {sortie}")
        self.stdout.write(
            f"{GRIS}  {len(tri['ecarts'])} ecart(s) ouvert(s), "
            f"{len(tri['ecarts_corriges'])} corrige(s), "
            f"{len(tri['conformes'])} conforme(s), "
            f"{len(tri['indetermines'])} indetermine(s){RESET}")
        if not tri["mesure"]:
            self.stdout.write(
                f"  {COULEURS[NIVEAU.MODIFICATION]}aucune mesure dans cet "
                f"audit{RESET}{GRIS} — le rapport le dit en premiere page "
                f"plutot que de faire bonne figure.{RESET}")

    def _audit_depot(self, argument: str) -> str:
        """/audit [dossier] : `mael audit` depuis le terminal. Rend la
        question a poser au modele (resume borne du rapport), ou '' si rien
        a lui demander."""
        from pathlib import Path

        from brain import audit
        dossier = Path(argument or ".").expanduser().resolve()
        if not dossier.is_dir():
            self.stdout.write(f"  {dossier} n'est pas un dossier.")
            return ""
        self.stdout.write(f"{GRIS}  audit de {dossier} : secrets, "
                          f"dependances, code...{RESET}")
        with self._attente():
            r = audit.auditer(dossier)
        sortie = dossier / ".mael" / "AUDIT-SECURITE.md"
        sortie.parent.mkdir(parents=True, exist_ok=True)
        sortie.write_text(audit.en_markdown(r), encoding="utf-8")
        self.stdout.write(audit.resume_humain(r, sortie))
        return audit.question(r)

    def _aide(self):
        """Toutes les commandes, groupees par ce qu'elles servent a faire."""
        groupes = (
            ("Conduire l'audit", (
                ("/etat", "ou en est l'audit : etape, constats, preuves"),
                ("/preuve <texte>", "apporter une observation (sortie de "
                                    "commande collee)"),
                ("/ecarts", "les mesures du code : conforme, ecart, indetermine"),
                ("/corriger [fiche]", "corriger un ecart : simulation, code de "
                                      "confirmation, verification, re-mesure"),
                ("/revenir [fiche]", "annuler une correction appliquee"),
                ("/rapport [fichier]", "ecrire le rapport d'audit remis au "
                                       "client (HTML, imprimable)"),
                ("/audit [dossier]", "auditer un depot : secrets, "
                                     "dependances, code ; MAEL explique"),
            )),
            ("Savoir et contexte", (
                ("/fiches", "lister les fiches de la bibliotheque"),
                ("/contexte", "le systeme audite, tel que MAEL le voit"),
                ("/detecter", "redetecter le systeme audite"),
            )),
            ("Reglages et session", (
                ("/parametres", "voir les reglages"),
                ("/parametres <nom> <valeur>", "changer un reglage "
                                               "(pour cette session)"),
                ("/parametres enregistrer", "garder les reglages pour les "
                                            "prochaines fois"),
                ("/effacer", "repartir sur une conversation vide"),
                ("/aide", "cet ecran"),
                ("/q", "quitter"),
            )),
        )
        self.stdout.write("")
        for titre, entrees in groupes:
            self.stdout.write(f"{GRAS}{titre}{RESET}")
            for commande, quoi in entrees:
                self.stdout.write(f"  {commande:<28s} {GRIS}{quoi}{RESET}")
            self.stdout.write("")
        self.stdout.write(
            f"{GRIS}Tout le reste est une question posee a MAEL. Les commandes "
            f"qu'il propose sont classees avant d'etre lancees : une lecture "
            f"s'execute, une modification vous est soumise, le reste est "
            f"refuse.{RESET}")

    def _parametres(self, argument: str):
        """Voir, changer, enregistrer les reglages -- sans quitter MAEL."""
        if not argument:
            self.stdout.write(f"\n{GRAS}Reglages{RESET} "
                              f"{GRIS}(fichier : {reglages.fichier()}){RESET}")
            for ligne in reglages.decrire(self.reglages):
                self.stdout.write("  " + ligne)
            self.stdout.write(f"{GRIS}  /parametres <nom> <valeur> pour "
                              f"changer, /parametres enregistrer pour "
                              f"garder.{RESET}")
            return
        if argument in {"enregistrer", "garder", "sauver"}:
            chemin = reglages.enregistrer(self.reglages)
            self.stdout.write(f"{GRIS}  reglages enregistres : {chemin}{RESET}")
            return
        if argument in {"defaut", "defauts", "remise a zero"}:
            self.reglages = reglages.defauts()
            self._appliquer_apparence()
            self.stdout.write(f"{GRIS}  reglages revenus aux valeurs par "
                              f"defaut (non enregistres).{RESET}")
            return
        nom, _, valeur = argument.partition(" ")
        if not valeur.strip():
            self.stdout.write("Usage : /parametres <nom> <valeur> "
                              "(ex. /parametres theme clair)")
            return
        self.reglages, message = reglages.modifier(self.reglages, nom.strip(),
                                                   valeur.strip())
        self._appliquer_apparence()
        # Ce qui doit suivre immediatement le reglage, sans redemarrage.
        self.profil = self.reglages["profil"]
        self.niveau = _niveau(self.reglages["niveau"])
        self.executer = self.reglages["executer"]
        self.bash = _bash() if self.executer else None
        self.stdout.write(f"{GRIS}  {message}{RESET}")

    def _montrer(self, titre, r):
        couleur = GRIS if r.ok else COULEURS[NIVEAU.MODIFICATION]
        etat = "ok" if r.ok else (f"refuse : {r.refuse}" if r.refuse
                                  else f"code {r.code}")
        self.stdout.write(f"  {couleur}[{titre} — {etat}]{RESET}")
        if r.sortie:
            self.stdout.write(f"{GRIS}{r.sortie[:1500]}{RESET}")

    def _confirmer(self, action: str) -> bool:
        """Confirmation forte : un code aleatoire a retaper (un « o » reflexe
        ne suffit pas a modifier une machine)."""
        import secrets
        code = secrets.token_hex(2).upper()
        rep = self._demander(f"  {COULEURS[NIVEAU.MODIFICATION]}Pour {action}, "
                             f"tapez le code {code} (autre chose = annuler) :"
                             f"{RESET} ")
        return rep.upper() == code

    def _remesurer(self, fiche_id: str, controle: str):
        """Relance les lectures de la fiche et laisse le CODE juger : c'est la
        seule preuve qu'un ecart est corrige."""
        from brain.bibliotheque import ecarts as ec
        fiche = next((f for f in bibliotheque.toutes() if f.id == fiche_id), None)
        if fiche is None:
            return None
        c = next((c for c in fiche.controles if c.controle == controle), None)
        if c is None or not c.evaluation:
            return None
        sorties = {}
        for i in sorted({e["commande"] for e in c.evaluation}):
            cmd = fiche.observer[i].commande
            self.stdout.write(f"  $ {GRAS}{cmd}{RESET}")
            self._executer(cmd, self.bash)
            self.memoire.enregistrer_commande(cmd, NIVEAU.LECTURE.value,
                                              but="re-mesure apres correction",
                                              executee=True)
            sorties[i] = getattr(self, "_stdout", "")
        verdicts = [v for v in ec.evaluer_fiche(fiche, sorties,
                                                commande="re-mesure")
                    if v.controle == controle]
        self.memoire.enregistrer_verdicts(verdicts)
        return verdicts[0] if verdicts else None

    def _corriger(self, argument: str):
        from brain import playbooks as pbs
        candidats = self._corrigeables()
        if not candidats:
            self.stdout.write("\nAucun ecart corrigeable par playbook pour "
                              "l'instant (les ecarts viennent des mesures du "
                              "code : /ecarts).")
            return
        if not argument.isdigit() or not 1 <= int(argument) <= len(candidats):
            self.stdout.write(f"\n{len(candidats)} ecart(s) corrigeable(s) :")
            for n, m in enumerate(candidats, 1):
                self.stdout.write(f"  [{n}] [{m.get('gravite')}] {m['titre']} "
                                  f"{GRIS}— playbook {m['playbook']} "
                                  f"{m.get('parametres')}{RESET}")
            self.stdout.write(f"{GRIS}/corriger N : simulation, puis "
                              f"confirmation par code.{RESET}")
            return
        m = candidats[int(argument) - 1]
        pid, params = m["playbook"], dict(m.get("parametres") or {})
        trace = {"fiche": m["fiche"], "controle": m["controle"],
                 "playbook": pid, "parametres": params, "applique": False}
        pb = pbs.obtenir(pid)
        bash = self.bash or _bash()
        alteres = pbs.controler_sceau(pid) if pb else ["playbook inconnu"]
        erreurs = pbs.valider_parametres(pid, params) if pb else []
        if alteres or erreurs or not bash:
            raison = ("sceau rompu : " + ", ".join(alteres) if alteres else
                      "; ".join(erreurs) if erreurs else "aucun bash disponible")
            self.stdout.write(f"  {COULEURS[NIVEAU.INTERDIT]}Correction "
                              f"refusee : {raison}{RESET}")
            self.memoire.enregistrer_correction(dict(trace, refus=raison))
            return
        mf = pb.manifeste
        self.stdout.write(f"\n{GRAS}{mf.get('titre')}{RESET}  ({pid})")
        self.stdout.write(f"{GRIS}  ecart : {m['titre']} — lu : "
                          f"{m.get('constate')}\n  parametres : {params}\n"
                          f"  risque : {mf.get('risque')} ; indisponibilite : "
                          f"{mf.get('indisponibilite')} ; redemarrage : "
                          f"{'oui' if mf.get('redemarrage') else 'non'} ; "
                          f"reversible : {'oui' if mf.get('reversible') else 'NON'}"
                          f"\n  source : {(mf.get('source') or {}).get('gabarit')}"
                          f" ; sceau intact{RESET}")
        self._montrer("etat actuel", pbs.executer(pid, "detecter", params, bash))
        sim = pbs.executer(pid, "appliquer", params, bash, simulation=True)
        self._montrer("SIMULATION", sim)
        trace["simulation"] = sim.sortie[:2000]
        if not sim.ok:
            self.memoire.enregistrer_correction(dict(trace, refus="simulation "
                                                     "en echec"))
            return
        if not self.executer:
            self.stdout.write(f"{GRIS}  (mode simulation : relancer le "
                              f"terminal avec --executer pour appliquer){RESET}")
            self.memoire.enregistrer_correction(trace)
            return
        if not self._confirmer("appliquer cette correction"):
            self.stdout.write(f"{GRIS}  Correction annulee.{RESET}")
            self.memoire.enregistrer_correction(dict(trace, annule=True))
            return
        trace["confirme"] = True
        app = pbs.executer(pid, "appliquer", params, bash)
        self._montrer("APPLICATION", app)
        self.memoire.enregistrer_commande(
            pbs.commande_lisible(pid, "appliquer", params),
            NIVEAU.MODIFICATION.value, but="correction validee",
            executee=True)
        trace.update(applique=app.ok, code_application=app.code)
        if not app.ok:
            if app.code not in (2, 3, 4, 5, 64):   # 3 = deja revenu seul
                self._montrer("RETOUR ARRIERE", pbs.executer(pid, "revenir",
                                                             params, bash))
                trace["revenu"] = True
            self.memoire.enregistrer_correction(trace)
            return
        ver = pbs.executer(pid, "verifier", params, bash)
        self._montrer("VERIFICATION du playbook", ver)
        trace["verifie"] = ver.ok
        if not ver.ok:
            self._montrer("RETOUR ARRIERE automatique",
                          pbs.executer(pid, "revenir", params, bash))
            trace.update(revenu=True, applique=False)
            self.memoire.enregistrer_correction(trace)
            return
        v = self._remesurer(m["fiche"], m["controle"])
        statut = getattr(getattr(v, "statut", None), "value", None)
        trace["remesure"] = statut
        rouge, vert = COULEURS[NIVEAU.INTERDIT], COULEURS[NIVEAU.LECTURE]
        if statut == "conforme":
            self.stdout.write(f"  {vert}CORRIGE — mesure conforme par le "
                              f"code : {v.constate}{RESET}")
        elif statut == "ecart":
            self.stdout.write(f"  {rouge}Le code mesure encore un ecart "
                              f"({v.constate}) : retour arriere.{RESET}")
            self._montrer("RETOUR ARRIERE automatique",
                          pbs.executer(pid, "revenir", params, bash))
            trace.update(revenu=True, applique=False)
        else:
            self.stdout.write(f"  {COULEURS[NIVEAU.MODIFICATION]}Correction "
                              f"gardee, mais la re-mesure est indeterminee "
                              f"({getattr(v, 'motif', '?')}) : relancer les "
                              f"lectures avec sudo.{RESET}")
        self.memoire.enregistrer_correction(trace)

    def _revenir(self, argument: str):
        from brain import playbooks as pbs
        faites = [c for c in self.memoire.corrections
                  if c.get("applique") and not c.get("revenu")]
        if not argument.isdigit() or not 1 <= int(argument) <= len(faites):
            if not faites:
                self.stdout.write("\nAucune correction appliquee a annuler.")
                return
            self.stdout.write(f"\n{len(faites)} correction(s) appliquee(s) :")
            for n, c in enumerate(faites, 1):
                self.stdout.write(f"  [{n}] {c['playbook']} {c['parametres']} "
                                  f"{GRIS}({c['fiche']}){RESET}")
            self.stdout.write(f"{GRIS}/revenir N pour annuler.{RESET}")
            return
        c = faites[int(argument) - 1]
        bash = self.bash or _bash()
        if not self.executer or not bash:
            self.stdout.write("  Retour arriere impossible en simulation.")
            return
        if not self._confirmer("revenir en arriere"):
            self.stdout.write(f"{GRIS}  Annule.{RESET}")
            return
        r = pbs.executer(c["playbook"], "revenir", c["parametres"], bash)
        self._montrer("RETOUR ARRIERE", r)
        if r.ok:
            c["revenu"] = True
            self._remesurer(c["fiche"], c["controle"])
            self.memoire.sauver()

    def _etablir_contexte(self, declaration, forcer=False):
        """Contexte du systeme audite, du plus sur au moins sur : detection
        (en --executer), declaration --systeme, contexte deja memorise,
        indice dans le perimetre. Inconnu -> aucun filtrage."""
        ctx = ctx_mod.Contexte()
        if declaration:
            ctx = ctx_mod.depuis_declaration(declaration)
        elif self.memoire.contexte and not forcer:
            ctx = ctx_mod.Contexte.depuis_dict(self.memoire.contexte)
        if self.executer and self.bash and (forcer or ctx.origine != "detection"):
            detecte = ctx_mod.detecter(self._lire_silencieux)
            if detecte.connu:
                if declaration and ctx.connu and (detecte.os_id, detecte.famille) \
                        != (ctx.os_id, ctx.famille):
                    self.stderr.write(f"  ! --systeme {declaration} contredit la "
                                      f"detection ({detecte.os_id} "
                                      f"{detecte.version}) : detection retenue.")
                ctx = detecte
        if not ctx.connu and self.perimetre:
            ctx = ctx_mod.depuis_declaration(self.perimetre, origine="perimetre")
        self.memoire.fixer_contexte(ctx)
        return ctx

    def _lire_silencieux(self, cmd):
        """Execute une commande de detection. Elle passe par le garde-fou comme
        toute autre : si elle n'etait pas une LECTURE, on ne la lance pas."""
        if classer(cmd).niveau is not NIVEAU.LECTURE:
            return None
        try:
            r = subprocess.run([self.bash, "-lc", cmd], capture_output=True,
                               timeout=20)
        except Exception:  # noqa: BLE001
            return None
        if r.returncode != 0:
            return None
        return (r.stdout or b"").decode("utf-8", "replace")

    def _annoncer_confirmes(self):
        """Apres une observation, les hypotheses liees deviennent fondees."""
        for c in self.memoire.reevaluer(fondement.juge_pour(self.memoire)):
            self.stdout.write(f"{GRIS}  (hypothese desormais fondee : "
                              f"{c.resume[:80]} — {c.fondement}){RESET}")

    def _executer(self, cmd, bash) -> str:
        self._stdout = ""
        if not bash:
            return "Aucun bash disponible sur cette machine : execution impossible."
        try:
            # text=False : on decode nous-memes, tolerant. Sinon la sortie
            # Windows (cp1252/OEM) fait planter le decodeur et perd stdout.
            r = subprocess.run([bash, "-lc", cmd], capture_output=True,
                               timeout=60)
        except subprocess.TimeoutExpired:
            self._stdout = ecarts.IMPOSSIBLE     # jamais jugee comme vide
            return "Delai depasse (60 s) : commande interrompue."
        except Exception as exc:  # noqa: BLE001
            self._stdout = ecarts.IMPOSSIBLE
            return f"Echec d'execution : {exc}"
        out = (r.stdout or b"").decode("utf-8", "replace")
        # seule la sortie standard est jugee ; commande introuvable (127) ou
        # non executable (126) -> indetermine, pas « aucune valeur ».
        self._stdout = ecarts.sortie_a_juger(r.returncode, out)
        err = (r.stderr or b"").decode("utf-8", "replace")
        sortie = (out + err).strip()
        apercu = sortie[:4000] if sortie else "(aucune sortie)"
        self.stdout.write(f"{GRIS}{apercu[:1200]}{RESET}")
        return f"code={r.returncode}\n{apercu}"

    # ----------------------------------------------------------- utilitaires
    @staticmethod
    def _extraire_bloc(texte: str) -> str | None:
        m = re.search(r"```(?:bash|sh|shell)?\s*\n(.+?)```", texte or "",
                      re.DOTALL)
        if not m:
            return None
        lignes = [l for l in m.group(1).strip().splitlines()
                  if l.strip() and not l.strip().startswith("#")]
        return lignes[0].strip() if lignes else None

    def _entete(self, modele, executer, bash, perimetre):
        """Le logo, puis une seule ligne : le mode (info de securite), le
        modele, l'audit. Le detail (perimetre, memoire, reglages) reste
        disponible via /etat et /parametres — l'accueil n'est pas un bilan."""
        from brain import banniere
        if self.reglages.get("animation") and console.couleurs_possibles():
            # sys.stdout brut : le wrapper de Django ajoute un saut de ligne
            # a chaque write, ce qui doublerait l'interligne de la banniere.
            banniere.devoler(sys.stdout, couleurs=bool(self.style.couleur))
        else:
            self.stdout.write("\n" + banniere.texte(
                couleurs=bool(self.style.couleur)))
        mode = (f"{COULEURS[NIVEAU.LECTURE]}execution reelle{RESET}" if executer
                else f"{COULEURS[NIVEAU.MODIFICATION]}simulation{RESET}")
        self.stdout.write(f"\n{GRIS}{modele} · mode {mode}{GRIS} · "
                          f"{self.memoire.id} · "
                          f"{RESET}{GRAS}/aide{RESET}{GRIS} pour les "
                          f"commandes{RESET}")
        if executer and not bash:
            self.stderr.write("  ! aucun bash trouve : les lectures ne pourront "
                              "pas s'executer.")
