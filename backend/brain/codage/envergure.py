"""L'ENVERGURE du modele : les reglages du chantier SUIVENT le modele charge.

Decision du responsable (09/10/2026) : phi4-mini n'est que le banc
d'epreuve ; la soumission a l'examen Hugging Face se fera avec de GRANDS
modeles. Or le chantier avait des limites gravees pour un petit modele :
8 fichiers par plan, 9 000 caracteres par fichier, 700 jetons pour un plan.
Avec un modele de 32 milliards et 32 000 jetons de contexte, ces limites le
brideraient — MAEL serait un petit outil, quel que soit le moteur.

Ici les reglages se DEDUISENT de deux mesures que le moteur donne lui-meme
(llama-server : /v1/models ; Ollama : /api/show) :
  - la taille du modele (milliards de parametres) ;
  - le contexte reellement disponible (jetons).
Un modele inconnu (faux moteur des tests, moteur muet) recoit les reglages
du PETIT : ceux qui ont ete mesures sur le portable de 8 Go.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Envergure:
    modele: str = ""
    milliards: float = 0.0          # 0 = inconnu
    contexte: int = 4096            # jetons reellement disponibles

    @property
    def classe(self) -> str:
        if self.milliards >= 20:
            return "grand"
        if self.milliards >= 6:
            return "moyen"
        return "petit"

    @property
    def taches_par_lot(self) -> int:
        """Fichiers par plan (par LOT, quand le chantier aura ses etapes)."""
        return {"petit": 8, "moyen": 16, "grand": 30}[self.classe]

    @property
    def longueur_fichier(self) -> int:
        """Caracteres ecrits d'un coup avant de couper : 9 000 mesures sur
        phi4-mini (au-dela il perd sa consigne) ; un modele plus grand a
        droit a environ 40 % de son contexte (3 caracteres par jeton)."""
        if self.classe == "petit":
            return 9_000
        return max(9_000, min(int(self.contexte * 3 * 0.4), 60_000))

    @property
    def jetons_plan(self) -> int:
        return {"petit": 700, "moyen": 1_500, "grand": 3_000}[self.classe]

    @property
    def jetons_reponse(self) -> int:
        if self.classe == "petit":
            return 2_048
        return max(2_048, min(self.contexte // 2, 16_384))

    @property
    def budget_contrats(self) -> int:
        """Caracteres de contrats (contrats.py) donnes a chaque etape."""
        return {"petit": 1_500, "moyen": 4_000, "grand": 10_000}[self.classe]

    @property
    def budget_extraits(self) -> int:
        """Caracteres de code d'un depot existant montres au modele pour
        corriger un ticket (correctif.py) : le reste du contexte va au
        ticket et a la reponse."""
        if self.classe == "petit":
            return 6_000
        return max(6_000, min(int(self.contexte * 3 * 0.45), 120_000))

    def libelle(self) -> str:
        taille = f"{self.milliards:.1f} milliards" if self.milliards else \
            "taille inconnue"
        return (f"{self.modele or 'modele'} ({taille}, contexte "
                f"{self.contexte}) : envergure {self.classe} — "
                f"{self.taches_par_lot} fichiers par lot, "
                f"{self.longueur_fichier} caracteres par fichier")


PETIT = Envergure()


def lire(backend) -> Envergure:
    """L'envergure que le moteur annonce ; PETIT s'il ne sait pas le dire."""
    mesurer = getattr(backend, "envergure", None)
    if not callable(mesurer):
        return PETIT
    try:
        e = mesurer()
    except Exception:                                   # noqa: BLE001
        return PETIT
    return e if isinstance(e, Envergure) else PETIT


def contexte_pour_la_machine(capa=None) -> int:
    """Le contexte a demander au moteur, d'apres la machine : la memoire du
    contexte (KV) s'ajoute a celle du modele. Mesure du 09/10 : 8 192 tient
    sur 8 Go avec phi4-mini."""
    from brain import machine
    capa = capa or machine.capacite()
    go = 1024 ** 3
    memoire = max(capa.ram_totale, capa.vram)
    if not memoire or memoire < 16 * go:
        return 8_192
    if memoire < 32 * go:
        return 16_384
    if memoire < 64 * go:
        return 32_768
    return 65_536
