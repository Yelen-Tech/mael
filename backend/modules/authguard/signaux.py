"""Les signaux de risque d'une tentative de connexion.

Chaque signal est une fonction pure : elle recoit un contexte, elle rend un
`Signal` ou None. Aucun signal ne decide -- ils s'additionnent, et la decision
est prise a la fin, une seule fois, par `evaluer()`.

Pourquoi separer ainsi : on peut activer, desactiver ou repondre d'un signal
sans toucher aux autres, et le banc d'essai peut tester chacun isolement.

Le vol de compte est le vecteur numero un de vol de donnees. Les quatre
premiers signaux couvrent les quatre formes d'attaque reelles, et il est
important de les distinguer parce qu'elles n'appellent pas la meme reponse :

  force brute            1 compte,     beaucoup d'essais  -> bloquer le compte
  bourrage d'identifiants 1 IP,        beaucoup de comptes -> bloquer l'IP
  pulverisation          beaucoup d'IP, 1 jeu de comptes   -> exiger le 2e facteur
  reprise de session     1 succes,     contexte anormal    -> re-authentifier
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import fenetres

# --------------------------------------------------------------------- fenetres
COURTE = 300        # 5 min
MOYENNE = 3600      # 1 h
LONGUE = 86400      # 24 h
MEMOIRE = 90 * 86400  # profil : 90 jours

# --------------------------------------------------------------------- seuils
SEUIL_ECHECS_COMPTE = 5        # sur COURTE
SEUIL_ECHECS_IP = 20           # sur COURTE
SEUIL_COMPTES_PAR_IP = 8       # comptes distincts vises par une IP sur MOYENNE
SEUIL_IP_PAR_COMPTE = 6        # IP distinctes visant un compte sur MOYENNE


@dataclass
class Signal:
    code: str
    poids: float
    resume: str
    details: dict = field(default_factory=dict)


@dataclass
class Contexte:
    """Tout ce qu'on sait de la tentative. Rien d'identifiant en clair."""

    organisation: object
    empreinte_compte: str
    ip: str
    empreinte_appareil: str
    succes: bool
    pays: str = ""
    appareils_connus: list[str] = field(default_factory=list)
    pays_connus: list[str] = field(default_factory=list)
    premiere_connexion: bool = False
    # Reseau declare par le client (bureau, VPN d'entreprise). Les signaux
    # agreges par IP y sont neutralises : vingt employes derriere un seul
    # routeur NAT ne sont pas une attaque.
    reseau_de_confiance: bool = False


# ===================================================================== signaux
def force_brute_compte(ctx: Contexte) -> Signal | None:
    """Beaucoup d'echecs sur un seul compte : on essaie de casser ce compte."""
    echecs = fenetres.lire("echec_compte", ctx.empreinte_compte, fenetre=COURTE)
    if echecs < SEUIL_ECHECS_COMPTE:
        return None
    # Calibrage : des le seuil (5 echecs) on atteint SEUIL_DEFI, parce qu'un
    # utilisateur reel ne se trompe pas cinq fois de suite. A 20 echecs on
    # atteint SEUIL_REFUS -- c'est un verrouillage de compte, la bonne reponse.
    # Le poids plafonne : 50 echecs ne sont pas deux fois pires que 20.
    poids = min(0.80, 0.40 + 0.027 * (echecs - SEUIL_ECHECS_COMPTE))
    return Signal(
        code="force_brute_compte",
        poids=poids,
        resume=f"{echecs} echecs sur ce compte en 5 minutes",
        details={"echecs": echecs, "fenetre_s": COURTE, "reponse": "bloquer_le_compte"},
    )


def force_brute_ip(ctx: Contexte) -> Signal | None:
    """Beaucoup d'echecs depuis une IP, tous comptes confondus."""
    if ctx.reseau_de_confiance:
        return None
    echecs = fenetres.lire("echec_ip", ctx.ip, fenetre=COURTE)
    if echecs < SEUIL_ECHECS_IP:
        return None
    poids = min(0.45, 0.15 + 0.02 * (echecs - SEUIL_ECHECS_IP))
    return Signal(
        code="force_brute_ip",
        poids=poids,
        resume=f"{echecs} echecs depuis cette adresse en 5 minutes",
        details={"echecs": echecs, "reponse": "limiter_l_ip"},
    )


def bourrage_identifiants(ctx: Contexte) -> Signal | None:
    """Une IP essaie beaucoup de comptes differents.

    Signature d'identifiants voles ailleurs et rejoues en masse. Tres
    different de la force brute : peu d'essais par compte, donc les compteurs
    par compte ne voient rien. C'est le nombre de comptes *distincts* qui
    trahit l'attaque.

    Deux garde-fous contre le faux positif sur un bureau derriere NAT :
    seuls les ECHECS alimentent ce compteur (cote vue), et les reseaux
    declares par le client sont exclus.
    """
    if ctx.reseau_de_confiance:
        return None
    comptes = fenetres.compter_distinct("comptes_par_ip", ctx.ip, fenetre=MOYENNE)
    if comptes < SEUIL_COMPTES_PAR_IP:
        return None
    # Une adresse qui vise 18 comptes distincts en une heure n'a aucune
    # explication legitime : on doit atteindre SEUIL_REFUS.
    poids = min(0.85, 0.35 + 0.05 * (comptes - SEUIL_COMPTES_PAR_IP))
    return Signal(
        code="bourrage_identifiants",
        poids=poids,
        resume=f"cette adresse a vise {comptes} comptes differents en 1 heure",
        details={"comptes_distincts": comptes, "reponse": "bloquer_l_ip"},
    )


def pulverisation(ctx: Contexte) -> Signal | None:
    """Beaucoup d'IP differentes visent le meme compte.

    Signature d'un reseau de machines qui repartit les essais pour passer
    sous les seuils par IP. Aucun compteur par IP ne se declenche ; c'est la
    dispersion qui trahit.
    """
    sources = fenetres.compter_distinct("ip_par_compte", ctx.empreinte_compte,
                                        fenetre=MOYENNE)
    if sources < SEUIL_IP_PAR_COMPTE:
        return None
    poids = min(0.65, 0.30 + 0.045 * (sources - SEUIL_IP_PAR_COMPTE))
    return Signal(
        code="pulverisation",
        poids=poids,
        resume=f"{sources} adresses differentes ont vise ce compte en 1 heure",
        details={"ip_distinctes": sources, "reponse": "exiger_second_facteur"},
    )


def ip_malveillante(ctx: Contexte) -> Signal | None:
    """Reutilise la base du module Reputation : rien a collecter en plus."""
    from modules.reputation.models import Indicateur, Plage

    ind = Indicateur.objects.filter(type=Indicateur.Type.IP, valeur=ctx.ip).first()
    correspondance = "exacte"
    if ind is None:
        plage = Plage.contenant(ctx.ip)
        if plage is None:
            return None
        score, verdict, categories = plage.score, plage.verdict, plage.categories
        correspondance = f"plage {plage.cidr}"
    else:
        if ind.verdict == Indicateur.Verdict.BENIN:
            return None
        score, verdict, categories = ind.score, ind.verdict, ind.categories

    if verdict == Indicateur.Verdict.INCONNU:
        # Tor seul tombe ici : contexte utile, poids faible.
        if "tor" in (categories or []):
            return Signal(
                code="reseau_anonymisant",
                poids=0.15,
                resume="connexion depuis un noeud de sortie Tor",
                details={"categories": categories},
            )
        return None

    poids = 0.50 if verdict == Indicateur.Verdict.MALVEILLANT else 0.25
    return Signal(
        code="ip_signalee",
        poids=poids,
        resume=f"adresse {verdict} (score {score:.2f})",
        details={"score": score, "categories": categories,
                 "correspondance": correspondance},
    )


def appareil_inconnu(ctx: Contexte) -> Signal | None:
    """Premier usage de cet appareil pour ce compte.

    Poids faible a dessein : changer de telephone est normal. Ce signal ne
    vaut que combine a un autre -- c'est exactement le role de l'addition.
    """
    if ctx.premiere_connexion or not ctx.appareils_connus:
        return None
    if ctx.empreinte_appareil in ctx.appareils_connus:
        return None
    return Signal(
        code="appareil_inconnu",
        poids=0.18,
        resume="appareil jamais vu pour ce compte",
        details={"appareils_connus": len(ctx.appareils_connus)},
    )


def changement_de_pays(ctx: Contexte) -> Signal | None:
    """Connexion depuis un pays jamais vu, peu apres une autre ailleurs.

    Version « pays » du voyage impossible. La version geographique fine
    demande une base de geolocalisation (MaxMind) : le resolveur est
    remplacable, la logique ne change pas.
    """
    if not ctx.pays or ctx.premiere_connexion:
        return None
    if ctx.pays in ctx.pays_connus:
        return None

    dernier = fenetres.rappeler("dernier_pays", ctx.empreinte_compte)
    if dernier and dernier != ctx.pays:
        return Signal(
            code="voyage_impossible",
            poids=0.45,
            resume=f"connexion depuis {ctx.pays} alors que la precedente venait "
                   f"de {dernier}, en moins d'une heure",
            details={"pays": ctx.pays, "pays_precedent": dernier,
                     "reponse": "exiger_second_facteur"},
        )
    return Signal(
        code="pays_inhabituel",
        poids=0.20,
        resume=f"premiere connexion depuis {ctx.pays}",
        details={"pays": ctx.pays, "pays_connus": ctx.pays_connus},
    )


TOUS_LES_SIGNAUX = [
    force_brute_compte,
    force_brute_ip,
    bourrage_identifiants,
    pulverisation,
    ip_malveillante,
    appareil_inconnu,
    changement_de_pays,
]


# ==================================================================== decision
SEUIL_REFUS = 0.75
SEUIL_DEFI = 0.40


@dataclass
class Evaluation:
    score: float
    decision: str            # autoriser | defier | refuser
    signaux: list[Signal]
    degrade: bool = False

    def en_json(self) -> dict:
        return {
            "score": round(self.score, 3),
            "decision": self.decision,
            "signaux": [
                {"code": s.code, "poids": round(s.poids, 3),
                 "resume": s.resume, "details": s.details}
                for s in sorted(self.signaux, key=lambda s: -s.poids)
            ],
            "degrade": self.degrade,
        }


def combiner(poids: list[float]) -> float:
    """Combinaison probabiliste, pas une somme.

    Une somme depasse 1 des trois signaux et sature. On combine les
    complementaires : chaque signal reduit la probabilite que la tentative
    soit legitime. Trois signaux a 0.3 donnent 0.657, pas 0.9 -- et jamais
    plus de 1 quel qu'en soit le nombre.
    """
    legitime = 1.0
    for p in poids:
        legitime *= (1.0 - max(0.0, min(1.0, p)))
    return round(1.0 - legitime, 4)


def decider(score: float) -> str:
    if score >= SEUIL_REFUS:
        return "refuser"
    if score >= SEUIL_DEFI:
        return "defier"
    return "autoriser"


def evaluer(ctx: Contexte) -> Evaluation:
    """Applique tous les signaux et rend une evaluation. Ne leve jamais."""
    signaux: list[Signal] = []
    for detecteur in TOUS_LES_SIGNAUX:
        try:
            signal = detecteur(ctx)
        except Exception:  # noqa: BLE001 -- un signal casse n'invalide pas les autres
            continue
        if signal is not None:
            signaux.append(signal)

    score = combiner([s.poids for s in signaux])
    return Evaluation(
        score=score,
        decision=decider(score),
        signaux=signaux,
        degrade=not fenetres.disponible(),
    )
