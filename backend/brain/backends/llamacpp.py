"""Backend LLAMA.CPP -- le moteur de MAEL, lance par MAEL lui-meme.

Pourquoi (decision du responsable, 09/10/2026, apres l'examen des 100
missions) : Ollama, laisse des heures sans etre relance, s'est abime
(charabia, erreurs 500, delais de 20 minutes) et 75 missions ont ete
perdues. Ollama n'est qu'une enveloppe : a l'interieur tourne deja
llama.cpp. Ici MAEL tient le moteur lui-meme :
  - il demarre `llama-server` (llama.cpp officiel) sur 127.0.0.1, avec SES
    reglages : contexte fixe (pas de rechargement selon la consigne), cache
    des consignes borne (Ollama en gardait jusqu'a 8 Go — toute la memoire
    de la machine : « making room for prompt cache entry » juste avant le
    charabia), nombre de fils mesure ;
  - il le RELANCE vraiment (processus arrete, memoire rendue) quand la sonde
    ou le detecteur de charabia le trouvent abime ;
  - la sortie se CONTRAINT par schema (grammaire de llama.cpp) : un plan ne
    peut plus etre une page HTML ;
  - il l'arrete en partant : la machine retrouve sa memoire.
Les fichiers : %LOCALAPPDATA%/MAEL/moteur/llama-*/llama-server.exe et
%LOCALAPPDATA%/MAEL/modeles/*.gguf (le modele de l'utilisateur, lie sans
copie depuis Ollama s'il l'avait deja).
"""
from __future__ import annotations

import atexit
import json
import os
import re
import subprocess
import time
from pathlib import Path

import httpx
from django.conf import settings

from .base import FluxReponse, LLMBackend, Reponse
from .sante import SONDE, SONDE_SYSTEME, MoteurEnPanne, charabia, sonde_juste

DEMARRAGE_MAX = 300           # secondes pour charger le modele (disque lent)


def _racine_mael() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "MAEL"


def trouver_serveur(reglage: str = "") -> Path | None:
    """Le llama-server.exe a utiliser : celui du reglage, sinon la version
    la plus recente rangee dans MAEL/moteur."""
    if reglage:
        return Path(reglage) if Path(reglage).exists() else None
    candidats = sorted(
        (_racine_mael() / "moteur").glob("llama-b*/llama-server*"),
        key=lambda p: int(re.sub(r"\D", "", p.parent.name) or 0))
    return candidats[-1] if candidats else None


def trouver_modele(reglage: str = "", voulu: str = "") -> Path | None:
    """Le fichier .gguf : celui du reglage, sinon celui que `mael
    installer` a pose, sinon celui dont le nom ressemble au modele voulu,
    sinon le seul present."""
    if reglage:
        return Path(reglage) if Path(reglage).exists() else None
    # celui que `mael installer` a pose (MAEL-Coder), s'il est la
    try:
        pose = json.loads((_racine_mael() / "installe.json").read_text(
            encoding="utf-8")).get("fichier", "")
    except (OSError, ValueError):
        pose = ""
    if pose and (_racine_mael() / "modeles" / pose).exists():
        return _racine_mael() / "modeles" / pose
    tous = sorted((_racine_mael() / "modeles").glob("*.gguf"))
    if voulu:
        base = voulu.split(":")[0].lower()
        memes = [p for p in tous if p.stem.lower().startswith(base)]
        if memes:
            return memes[0]
    return tous[0] if len(tous) == 1 else None


class LlamaCppBackend(LLMBackend):
    nom = "llamacpp"
    accepte_max_jetons = True
    _entetes: dict = {}          # llama-server : aucun (vllm.py : cle facultative)

    def __init__(self):
        from brain.modeles import ProblemeDeModele
        r = settings.BRAIN.get("LLAMACPP", {})
        self.serveur = trouver_serveur(r.get("SERVEUR", ""))
        self.fichier = trouver_modele(
            r.get("MODELE", ""), settings.BRAIN["MODELES"].get("codeur", ""))
        if self.serveur is None or self.fichier is None:
            manque = ("llama-server (le moteur)" if self.serveur is None
                      else "le fichier du modele (.gguf)")
            raise ProblemeDeModele(
                f"Moteur llama.cpp : {manque} introuvable.",
                [f"Le ranger dans {_racine_mael() / ('moteur' if self.serveur is None else 'modeles')}",
                 "ou le designer : BRAIN_LLAMA_SERVEUR / BRAIN_LLAMA_MODELE",
                 "ou revenir a Ollama : BRAIN_BACKEND=ollama"])
        self.port = int(r.get("PORT", 8089))
        self.base = f"http://127.0.0.1:{self.port}"
        # 0 = d'apres la machine (envergure.contexte_pour_la_machine) : un
        # grand modele sur une grande machine a droit a un grand contexte.
        from brain.codage.envergure import contexte_pour_la_machine
        self.contexte = int(r.get("CONTEXTE", 0)) or contexte_pour_la_machine()
        self.fils = int(r.get("FILS", 0)) or (os.cpu_count() or 4)
        self.cache_ram = int(r.get("CACHE_RAM", 256))
        self.gpu = int(r.get("GPU", 0))
        self.timeout = settings.BRAIN["TIMEOUT"]
        self.journal = _racine_mael() / "moteur" / "serveur.log"
        self.fichier_pid = _racine_mael() / "moteur" / "serveur.pid"
        self.processus: subprocess.Popen | None = None
        self.relances = 0
        atexit.register(self.arreter)

    # ------------------------------------------------------------ processus
    def modele_pour(self, role: str) -> str:
        super().modele_pour(role)          # valide le role, rien de plus
        return self.fichier.stem

    def _sain(self) -> bool:
        try:
            r = httpx.get(f"{self.base}/health", timeout=3)
            return r.status_code == 200 and r.json().get("status") == "ok"
        except (httpx.HTTPError, ValueError):
            return False

    def _tuer_orphelin(self) -> None:
        """Un serveur laisse par une session precedente (pid enregistre)."""
        try:
            pid = int(self.fichier_pid.read_text().strip())
        except (OSError, ValueError):
            return
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           capture_output=True)
        else:
            try:
                os.kill(pid, 9)
            except OSError:
                pass
        self.fichier_pid.unlink(missing_ok=True)

    def demarrer(self) -> None:
        if self.processus is not None and self.processus.poll() is None \
                and self._sain():
            return
        if self.processus is None and self._sain():
            return                          # deja lance (autre session) : on s'en sert
        self._tuer_orphelin()
        self.journal.parent.mkdir(parents=True, exist_ok=True)
        commande = [str(self.serveur), "-m", str(self.fichier),
                    "-c", str(self.contexte), "-t", str(self.fils),
                    "-np", "1", "--host", "127.0.0.1",
                    "--port", str(self.port),
                    "--cache-ram", str(self.cache_ram)]
        if self.gpu:
            commande += ["-ngl", str(self.gpu)]
        sortie = open(self.journal, "ab")
        self.processus = subprocess.Popen(
            commande, stdout=sortie, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.fichier_pid.write_text(str(self.processus.pid))
        debut = time.monotonic()
        while time.monotonic() - debut < DEMARRAGE_MAX:
            if self.processus.poll() is not None:
                raise MoteurEnPanne("llama-server s'est arrete au demarrage "
                                    f"(code {self.processus.returncode}) — "
                                    f"voir {self.journal}")
            if self._sain():
                return
            time.sleep(1)
        self.arreter()
        raise MoteurEnPanne(f"llama-server pas pret en {DEMARRAGE_MAX} s")

    def arreter(self) -> None:
        p, self.processus = self.processus, None
        if p is not None and p.poll() is None:
            p.terminate()
            try:
                p.wait(timeout=20)
            except subprocess.TimeoutExpired:
                p.kill()
            self.fichier_pid.unlink(missing_ok=True)

    def relancer(self, modele: str = "") -> None:
        """Arreter le processus (sa memoire abimee part avec lui) et en
        demarrer un neuf."""
        self.relances += 1
        self.arreter()
        self._tuer_orphelin()
        self.demarrer()

    def decharger(self) -> bool:
        """Rendre la memoire (avant les tests en conteneur) ; la prochaine
        question redemarre le moteur."""
        self.arreter()
        return True

    def envergure(self):
        """Taille et contexte du modele CHARGE, dits par llama-server : les
        reglages du chantier en decoulent (envergure.py)."""
        from brain.codage.envergure import Envergure
        self.demarrer()
        meta = httpx.get(f"{self.base}/v1/models", timeout=10).json()[
            "data"][0].get("meta") or {}
        return Envergure(modele=self.fichier.stem,
                         milliards=meta.get("n_params", 0) / 1e9,
                         contexte=int(meta.get("n_ctx") or self.contexte))

    # ---------------------------------------------------------------- appels
    @property
    def _delais(self) -> httpx.Timeout:
        return httpx.Timeout(self.timeout, connect=5.0, write=15.0, pool=5.0)

    def _corps(self, systeme: str, messages: list[dict], schema, outils,
               flux: bool, max_jetons: int | None) -> dict:
        corps: dict = {
            "messages": [{"role": "system", "content": systeme}, *messages],
            "stream": flux,
            "temperature": 0.1,
            "max_tokens": max_jetons or settings.BRAIN.get("NUM_PREDICT",
                                                           2048),
        }
        if schema is not None:
            # Grammaire de llama.cpp : le decodage ne peut sortir du schema.
            corps["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "reponse", "schema": schema}}
        if outils:
            corps["tools"] = outils       # deja au format OpenAI, comme pour Ollama
        return corps

    @staticmethod
    def _outils_de(message: dict) -> list[dict]:
        appels = []
        for a in message.get("tool_calls") or []:
            f = a.get("function", {})
            arguments = f.get("arguments", {})
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments or "{}")
                except json.JSONDecodeError:
                    arguments = {}
            appels.append({"nom": f.get("name", ""), "arguments": arguments})
        return appels

    def sonde(self, modele: str = "") -> bool:
        try:
            self.demarrer()
            with httpx.Client(timeout=self._delais, headers=self._entetes) as client:
                corps = self._corps(SONDE_SYSTEME,
                                    [{"role": "user", "content": SONDE}],
                                    None, None, False, 16)
                corps["temperature"] = 0
                r = client.post(f"{self.base}/v1/chat/completions",
                                json=corps)
                r.raise_for_status()
                texte = r.json()["choices"][0]["message"].get("content") or ""
        except (httpx.HTTPError, KeyError, ValueError, MoteurEnPanne):
            return False
        return sonde_juste(texte)

    def verifier_sante(self, role_modele: str = "codeur") -> str:
        if self.sonde():
            return ""
        try:
            self.relancer()
        except MoteurEnPanne:
            raise
        if self.sonde():
            return "relance"
        raise MoteurEnPanne(f"{self.fichier.stem} ne repond plus juste, meme "
                            "relance (sonde « 2 + 3 » ratee deux fois)")

    def completer(self, *, systeme: str, messages: list[dict],
                  role_modele: str = "analyste", schema: dict | None = None,
                  outils: list[dict] | None = None,
                  max_jetons: int | None = None) -> Reponse:
        modele = self.modele_pour(role_modele)
        corps = self._corps(systeme, messages, schema, outils, False,
                            max_jetons)
        panne = ""
        for essai in range(2):
            try:
                self.demarrer()
                with httpx.Client(timeout=self._delais, headers=self._entetes) as client:
                    r = client.post(f"{self.base}/v1/chat/completions",
                                    json=corps)
                    r.raise_for_status()
                    data = r.json()
            except httpx.TimeoutException:
                panne = "delai depasse"
            except httpx.TransportError:
                panne = "moteur injoignable"
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code < 500:
                    raise
                panne = f"erreur {exc.response.status_code} du moteur"
            else:
                message = data["choices"][0]["message"]
                texte = message.get("content") or ""
                appels = self._outils_de(message)
                panne = "" if appels else charabia(texte)
                if not panne:
                    break
            if essai == 0:
                self.relancer()
        else:
            raise MoteurEnPanne(f"{modele} : {panne}, meme apres relance")
        usage = data.get("usage", {})
        return Reponse(
            texte=texte,
            donnees=self._json_tolerant(texte) if schema is not None else None,
            appels_outils=appels, modele=modele,
            jetons_entree=usage.get("prompt_tokens", 0),
            jetons_sortie=usage.get("completion_tokens", 0))

    def flux(self, **arguments) -> FluxReponse:
        if arguments.get("outils"):
            return super().flux(**arguments)     # outils : reponse d'un bloc
        return FluxReponse(self._flux(**arguments))

    def _flux(self, *, systeme: str, messages: list[dict],
              role_modele: str = "analyste", schema: dict | None = None,
              outils: list[dict] | None = None,
              max_jetons: int | None = None):
        modele = self.modele_pour(role_modele)
        corps = self._corps(systeme, messages, schema, None, True,
                            max_jetons)
        morceaux: list[str] = []
        usage: dict = {}
        try:
            self.demarrer()
            with httpx.Client(timeout=self._delais, headers=self._entetes) as client:
                with client.stream("POST", f"{self.base}/v1/chat/completions",
                                   json=corps) as rep:
                    rep.raise_for_status()
                    for ligne in rep.iter_lines():
                        if not ligne.startswith("data:"):
                            continue
                        donnee = ligne[5:].strip()
                        if donnee == "[DONE]":
                            break
                        try:
                            bloc = json.loads(donnee)
                        except json.JSONDecodeError:
                            continue
                        usage = bloc.get("usage") or usage
                        for choix in bloc.get("choices") or []:
                            fragment = (choix.get("delta") or {}).get(
                                "content") or ""
                            if fragment:
                                morceaux.append(fragment)
                                yield fragment
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            self.relancer()
            raise MoteurEnPanne(f"{modele} : {type(exc).__name__} (flux)") \
                from exc
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code < 500:
                raise
            self.relancer()
            raise MoteurEnPanne(f"{modele} : erreur "
                                f"{exc.response.status_code} (flux)") from exc
        texte = "".join(morceaux)
        panne = charabia(texte) if len(texte) > 200 else ""
        if panne:
            self.relancer()
            raise MoteurEnPanne(f"{modele} : {panne} (flux)")
        return Reponse(
            texte=texte,
            donnees=self._json_tolerant(texte) if schema is not None else None,
            appels_outils=[], modele=modele,
            jetons_entree=usage.get("prompt_tokens", 0),
            jetons_sortie=usage.get("completion_tokens", 0))
