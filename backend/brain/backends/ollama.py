"""Backend Ollama -- mode developpement.

Installation minimale sur la machine de dev :
    ollama pull qwen3:8b
    ollama pull qwen3:30b-a3b   (si assez de VRAM)
    ollama serve

En production on bascule sur vLLM : meme interface, meilleur debit, et
les memes garanties de sortie contrainte.
"""
from __future__ import annotations

import json
import time

import httpx
from django.conf import settings

from .base import FluxReponse, LLMBackend, Reponse
from .sante import SONDE, SONDE_SYSTEME, MoteurEnPanne, charabia, sonde_juste

CONTEXTE_MAX = 8192       # au-dela, une machine de 8 Go sans carte graphique etouffe


class OllamaBackend(LLMBackend):
    nom = "ollama"
    # Le chantier peut borner la longueur d'une reponse (plan : ~700 jetons).
    accepte_max_jetons = True

    def __init__(self):
        self.base = settings.BRAIN["BASE_URL"].rstrip("/")
        self.timeout = settings.BRAIN["TIMEOUT"]
        self.relances = 0             # combien de fois le modele a ete relance

    def modele_pour(self, role: str) -> str:
        """Le modele du role, confronte a ce qui est REELLEMENT installe.

        Le nom ecrit dans la configuration est une intention ; ici on rend ce
        qui va tourner. Si l'intention est absente de la machine, brain.modeles
        choisit parmi ce qui est la (et l'enregistre) ; s'il n'y a rien, il
        leve un ProblemeDeModele qui dit quoi installer."""
        from brain import modeles

        super().modele_pour(role)   # valide le role, rien de plus
        return modeles.resoudre(role).nom

    def _corps(self, modele: str, systeme: str, messages: list[dict],
               schema: dict | None, outils: list[dict] | None,
               flux: bool, max_jetons: int | None = None) -> dict:
        corps: dict = {
            "model": modele,
            "messages": [{"role": "system", "content": systeme}, *messages],
            "stream": flux,
            # Garder le modele en memoire entre deux questions. Sans cela,
            # Ollama le decharge au bout de cinq minutes et le RECHARGE depuis
            # le disque a la question suivante : sur une machine sans carte
            # graphique, ce rechargement coute plus cher que la reponse
            # elle-meme. Une session d'audit est faite de silences.
            "keep_alive": settings.BRAIN.get("GARDER_EN_MEMOIRE", "30m"),
            "options": {
                # Deterministe autant que possible : on veut des verdicts
                # reproductibles, pas de la creativite.
                "temperature": 0.1,
                "num_ctx": settings.BRAIN.get("NUM_CTX", 8192),
                # Toujours une longueur maximale (examen du 09/10 : un plan
                # de 3 800 jetons en boucle, 20 minutes, puis coupure).
                "num_predict": max_jetons or settings.BRAIN.get(
                    "NUM_PREDICT", 2048),
            },
        }
        # La consigne doit TENIR dans le contexte, reponse comprise : sinon
        # Ollama en coupe le debut en silence — la consigne systeme d'abord
        # (examen du 09/10 : « truncating input prompt », 4 392 jetons pour
        # 4 096). Estimation prudente (3 caracteres par jeton), contexte
        # agrandi pour CET appel seulement, plafonne. Seulement quand la
        # consigne elle-meme deborde : changer de contexte fait recharger le
        # modele, on ne le paie pas a chaque appel.
        options = corps["options"]
        texte = systeme + "".join(str(m.get("content", "")) for m in messages)
        besoin = len(texte) // 3 + 512
        if besoin > options["num_ctx"]:
            options["num_ctx"] = min(-(-besoin // 1024) * 1024, CONTEXTE_MAX)
        # Mecanisme 3 : la sortie est contrainte par le schema, pas suggeree.
        if schema is not None:
            corps["format"] = schema
        if outils:
            corps["tools"] = outils
        return corps

    @property
    def _delais(self) -> httpx.Timeout:
        """Deux delais, pas un seul. Sur une machine sans carte graphique, un
        petit modele met deux a cinq MINUTES a repondre : lui laisser le temps
        est indispensable (mesure du 22/09 : 130 s en profil court, 295 s en
        complet). Mais attendre aussi longtemps une CONNEXION qui ne viendra
        jamais serait absurde : Ollama absent se voit en 5 s."""
        return httpx.Timeout(self.timeout, connect=5.0, write=15.0, pool=5.0)

    @staticmethod
    def _recolter(message: dict) -> list[dict]:
        return [
            {
                "nom": a["function"]["name"],
                "arguments": a["function"].get("arguments", {}),
            }
            for a in message.get("tool_calls", []) or []
        ]

    # ------------------------------------------------------------- sante
    def relancer(self, modele: str) -> None:
        """Decharger le modele : Ollama arrete son processus (et sa memoire
        abimee) ; la question suivante le recharge a neuf."""
        self.relances += 1
        try:
            with httpx.Client(timeout=httpx.Timeout(60.0, connect=5.0)) as c:
                c.post(f"{self.base}/api/generate",
                       json={"model": modele, "keep_alive": 0})
                for _ in range(30):              # attendre le dechargement
                    ps = c.get(f"{self.base}/api/ps").json()
                    if not any(modele in (m.get("name"), m.get("model"))
                               for m in ps.get("models") or []):
                        break
                    time.sleep(1)
        except (httpx.HTTPError, ValueError):
            pass

    def sonde(self, modele: str) -> bool:
        """Le moteur repond-il juste a une question dont on sait la reponse ?"""
        corps = self._corps(modele, SONDE_SYSTEME,
                            [{"role": "user", "content": SONDE}], None, None,
                            flux=False, max_jetons=16)
        corps["options"]["temperature"] = 0
        try:
            with httpx.Client(timeout=self._delais) as client:
                rep = client.post(f"{self.base}/api/chat", json=corps)
                rep.raise_for_status()
                texte = (rep.json().get("message") or {}).get("content", "")
        except httpx.HTTPError:
            return False
        return sonde_juste(texte)

    def envergure(self, role_modele: str = "codeur"):
        """Taille du modele (dite par Ollama) et contexte demande."""
        from brain.codage.envergure import Envergure
        modele = self.modele_pour(role_modele)
        with httpx.Client(timeout=httpx.Timeout(30.0, connect=5.0)) as c:
            info = c.post(f"{self.base}/api/show",
                          json={"model": modele}).json().get("model_info", {})
        return Envergure(modele=modele,
                         milliards=info.get("general.parameter_count", 0) / 1e9,
                         contexte=settings.BRAIN.get("NUM_CTX", 8192))

    def verifier_sante(self, role_modele: str = "codeur") -> str:
        """"" si le moteur est sain ; "relance" s'il a fallu le relancer
        (et qu'il va bien ensuite) ; MoteurEnPanne sinon."""
        modele = self.modele_pour(role_modele)
        if self.sonde(modele):
            return ""
        self.relancer(modele)
        if self.sonde(modele):
            return "relance"
        raise MoteurEnPanne(f"{modele} ne repond plus juste, meme relance "
                            "(sonde « 2 + 3 » ratee deux fois)")

    def completer(
        self,
        *,
        systeme: str,
        messages: list[dict],
        role_modele: str = "analyste",
        schema: dict | None = None,
        outils: list[dict] | None = None,
        max_jetons: int | None = None,
    ) -> Reponse:
        """Une reponse vide, du charabia, une erreur 500 ou un delai depasse :
        le modele est relance et la question reposee UNE fois ; si le moteur
        reste abime, MoteurEnPanne (ce n'est pas un echec de MAEL)."""
        modele = self.modele_pour(role_modele)
        corps = self._corps(modele, systeme, messages, schema, outils,
                            flux=False, max_jetons=max_jetons)
        panne = ""
        for essai in range(2):
            try:
                with httpx.Client(timeout=self._delais) as client:
                    rep = client.post(f"{self.base}/api/chat", json=corps)
                    rep.raise_for_status()
                    data = rep.json()
            except httpx.TimeoutException:
                panne = "delai depasse"
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code < 500:
                    raise
                panne = f"erreur {exc.response.status_code} du moteur"
            else:
                message = data.get("message", {})
                texte = message.get("content", "") or ""
                panne = "" if (outils and message.get("tool_calls")) \
                    else charabia(texte)
                if not panne:
                    break
            if essai == 0:
                self.relancer(modele)
        else:
            raise MoteurEnPanne(f"{modele} : {panne}, meme apres relance")

        return Reponse(
            texte=texte,
            donnees=self._json_tolerant(texte) if schema is not None else None,
            appels_outils=self._recolter(message),
            modele=modele,
            jetons_entree=data.get("prompt_eval_count", 0),
            jetons_sortie=data.get("eval_count", 0),
        )

    def flux(self, **arguments) -> FluxReponse:
        """Ollama sait diffuser : on en profite."""
        return FluxReponse(self._flux(**arguments))

    def _flux(
        self,
        *,
        systeme: str,
        messages: list[dict],
        role_modele: str = "analyste",
        schema: dict | None = None,
        outils: list[dict] | None = None,
        max_jetons: int | None = None,
    ):
        """La meme reponse, mais rendue morceau par morceau.

        Pourquoi : sur le portable vise, une reponse complete demande deux
        minutes. Attendre la derniere ligne pour afficher la premiere, c'est
        deux minutes d'ecran muet -- l'outil parait bloque alors qu'il
        travaille. En flux, les premiers mots arrivent des que le modele a
        fini de LIRE la question (mesure du 22/09 : environ 15 a 20 s au lieu
        de 130).

        Rend un generateur : chaque valeur est un fragment de texte, et la
        DERNIERE valeur rendue (attribut `.reponse` du generateur epuise)
        est la Reponse complete, identique a celle de `completer`. Le
        classement des commandes, lui, ne se fait jamais sur un fragment :
        la garde juge toujours le texte entier, une fois le flux termine.
        """
        modele = self.modele_pour(role_modele)
        corps = self._corps(modele, systeme, messages, schema, outils,
                            flux=True, max_jetons=max_jetons)
        try:
            reponse = yield from self._flux_brut(modele, corps, schema)
        except httpx.TimeoutException as exc:
            self.relancer(modele)
            raise MoteurEnPanne(f"{modele} : delai depasse (flux)") from exc
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code < 500:
                raise
            self.relancer(modele)
            raise MoteurEnPanne(f"{modele} : erreur "
                                f"{exc.response.status_code} (flux)") from exc
        # En flux, le chantier coupe souvent la reponse en route : on ne
        # juge que ce qui a eu le temps d'etre long.
        panne = charabia(reponse.texte) if len(reponse.texte) > 200 else ""
        if panne and not reponse.appels_outils:
            self.relancer(modele)
            raise MoteurEnPanne(f"{modele} : {panne} (flux)")
        return reponse

    def _flux_brut(self, modele: str, corps: dict, schema: dict | None):
        morceaux: list[str] = []
        message_final: dict = {}
        entree = sortie = 0

        with httpx.Client(timeout=self._delais) as client:
            with client.stream("POST", f"{self.base}/api/chat",
                               json=corps) as flux:
                flux.raise_for_status()
                for ligne in flux.iter_lines():
                    if not ligne.strip():
                        continue
                    try:
                        bloc = json.loads(ligne)
                    except json.JSONDecodeError:
                        # Une ligne illisible n'interrompt pas la reponse :
                        # on la laisse tomber et on continue a lire.
                        continue
                    message = bloc.get("message") or {}
                    fragment = message.get("content") or ""
                    if fragment:
                        morceaux.append(fragment)
                        yield fragment
                    if message.get("tool_calls"):
                        message_final = message
                    if bloc.get("done"):
                        entree = bloc.get("prompt_eval_count", 0)
                        sortie = bloc.get("eval_count", 0)
                        if not message_final:
                            message_final = message

        texte = "".join(morceaux)
        return Reponse(
            texte=texte,
            donnees=self._json_tolerant(texte) if schema is not None else None,
            appels_outils=self._recolter(message_final),
            modele=modele,
            jetons_entree=entree,
            jetons_sortie=sortie,
        )
