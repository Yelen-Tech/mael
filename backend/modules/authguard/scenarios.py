"""Scenarios d'attaque et de trafic legitime pour le module Connexions.

Lancement : python -m modules.authguard.scenarios

Nomme « scenarios » et non « tests_… » a dessein : le motif de
decouverte de Django est « test*.py ». Sous l'ancien nom, le lanceur
importait ce fichier et son faux client Redis global polluait la
suite de tests.

Ce n'est pas la suite de tests unitaires : c'est le banc de demonstration,
celui qui montre qu'une attaque est detectee *pour la bonne raison* et qu'un
utilisateur normal n'est pas gene. Les seuils se recalent ici.
"""
import os
import statistics
import time

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()


# --------------------------------------------------------------- Redis simule
class FauxRedis:
    """Transport Redis en memoire. On ne remplace que le client, pas le code."""

    def __init__(self):
        self.k, self.s, self.l = {}, {}, {}

    def pipeline(self):
        parent = self

        class Tube:
            def __init__(self):
                self.ops = []

            def incr(self, cle):
                self.ops.append(("incr", cle)); return self

            def expire(self, cle, t):
                self.ops.append(("exp", cle)); return self

            def sadd(self, cle, membre):
                self.ops.append(("sadd", cle, membre)); return self

            def scard(self, cle):
                self.ops.append(("scard", cle)); return self

            def execute(self):
                sortie = []
                for op in self.ops:
                    if op[0] == "incr":
                        parent.k[op[1]] = parent.k.get(op[1], 0) + 1
                        sortie.append(parent.k[op[1]])
                    elif op[0] == "sadd":
                        parent.s.setdefault(op[1], set()).add(op[2])
                        sortie.append(1)
                    elif op[0] == "scard":
                        sortie.append(len(parent.s.get(op[1], set())))
                    else:
                        sortie.append(True)
                return sortie

        return Tube()

    def get(self, cle):
        v = self.k.get(cle)
        return str(v).encode() if v is not None else None

    def set(self, cle, v, ex=None):
        self.k[cle] = v
        return True

    def scard(self, cle):
        return len(self.s.get(cle, set()))

    def delete(self, cle):
        self.k.pop(cle, None)
        return 1

    def rpush(self, cle, v):
        self.l.setdefault(cle, []).append(v)
        return 1

    def lpop(self, cle, n=1):
        x = self.l.get(cle, [])
        pris, self.l[cle] = x[:n], x[n:]
        return pris or None

    def llen(self, cle):
        return len(self.l.get(cle, []))

    def incr(self, cle):
        self.k[cle] = self.k.get(cle, 0) + 1
        return self.k[cle]

    def expire(self, cle, t):
        return True


from django.test import Client  # noqa: E402

from billing import journal  # noqa: E402
from billing.models import ApiKey, Module, Quota  # noqa: E402
from core.models import Organisation  # noqa: E402
from modules.authguard import fenetres  # noqa: E402
from modules.authguard.models import (  # noqa: E402
    MotDePasseCompromis,
    ProfilCompte,
    ReseauDeConfiance,
)
from modules.authguard.views import empreinte_sha1  # noqa: E402
from modules.reputation.models import Indicateur  # noqa: E402


def brancher_redis():
    """Vrai Redis s'il repond, simulateur sinon. Le code teste est le meme :
    on ne remplace que le transport."""
    from django.conf import settings

    if settings.REDIS_URL:
        try:
            import redis

            vrai = redis.Redis.from_url(settings.REDIS_URL, socket_timeout=1)
            vrai.ping()
            fenetres._client = vrai
            fenetres._indisponible = False
            journal._client = vrai
            # on part d'un etat propre : les compteurs d'un essai precedent
            # fausseraient le calibrage
            for motif in ("sentinelle:auth:*", "sentinelle:journal:*"):
                cles = list(vrai.scan_iter(match=motif, count=500))
                if cles:
                    vrai.delete(*cles)
            return "Redis reel"
        except Exception:
            pass

    faux = FauxRedis()
    fenetres._client = faux
    fenetres._indisponible = False
    journal._client = faux
    return "simulateur en memoire (Redis indisponible)"


TRANSPORT = brancher_redis()

UA_PC = "Mozilla/5.0 (Windows NT 10.0) Chrome/120"
UA_TEL = "Mozilla/5.0 (Linux; Android 14) Chrome/120"
TITRE = "=" * 74


def titre(texte):
    print("\n" + TITRE)
    print(texte)
    print(TITRE)


def montrer(d, libelle):
    print(f"  {libelle:38s} score {d['score']:.3f}  {d['decision'].upper()}")
    for s in d["signaux"]:
        reponse = s["details"].get("reponse", "")
        suffixe = f"  -> {reponse}" if reponse else ""
        print(f"      [{s['poids']:.2f}] {s['code']:22s} {s['resume']}{suffixe}")


def executer():
    print(f"Transport des compteurs : {TRANSPORT}")
    org = Organisation.objects.create(nom="Banque de demonstration SA")
    _, clair = ApiKey.generer(
        organisation=org, libelle="Demo", portee=[Module.AUTHGUARD]
    )
    Quota.objects.create(
        organisation=org, module=Module.AUTHGUARD, plafond_mensuel=10_000_000
    )
    client = Client()
    entetes = {"HTTP_X_API_KEY": clair}

    def essai(ident, ip, succes=False, ua=UA_PC, pays=""):
        return client.post(
            "/v1/auth/check",
            {"identifiant": ident, "ip": ip, "succes": succes,
             "user_agent": ua, "pays": pays},
            content_type="application/json",
            **entetes,
        ).json()

    # ------------------------------------------------------------------------
    titre("LE TEST LE PLUS IMPORTANT : L'UTILISATEUR LEGITIME\n"
          "(un produit qui gene les vrais utilisateurs ne sera pas garde)")
    d = essai("marie@banque.bf", "41.203.10.5", succes=True, pays="BF")
    montrer(d, "1re connexion (compte inconnu)")
    for _ in range(6):
        d = essai("marie@banque.bf", "41.203.10.5", succes=True, pays="BF")
    montrer(d, "connexions habituelles (x6)")
    d = essai("marie@banque.bf", "41.203.11.9", succes=True, pays="BF")
    montrer(d, "meme pays, autre IP (4G -> wifi)")
    d = essai("marie@banque.bf", "41.203.10.5", succes=True, ua=UA_TEL, pays="BF")
    montrer(d, "nouveau telephone")

    print("\n  -- elle se trompe 4 fois puis reussit --")
    for _ in range(4):
        essai("marie@banque.bf", "41.203.10.5")
    montrer(essai("marie@banque.bf", "41.203.10.5"), "5e essai encore rate")
    essai("marie@banque.bf", "41.203.10.5", succes=True, pays="BF")
    montrer(essai("marie@banque.bf", "41.203.10.5"),
            "nouvel echec apres le succes")
    print("      ^ compteur remis a zero par la connexion reussie")

    # ------------------------------------------------------------------------
    titre("ATTAQUE 1 - FORCE BRUTE : 1 compte, beaucoup d'essais")
    for n, marque in [(5, "e"), (10, "f"), (20, "g"), (50, "h")]:
        compte, ip = f"cible{marque}@banque.bf", f"197.28.9.{ord(marque)}"
        for _ in range(n - 1):
            essai(compte, ip)
        d = essai(compte, ip)
        signal = next(
            (s for s in d["signaux"] if s["code"] == "force_brute_compte"), None
        )
        poids = signal["poids"] if signal else 0
        print(f"  {n:3d} echecs   poids {poids:.2f}   score {d['score']:.3f}   "
              f"{d['decision'].upper()}")

    # ------------------------------------------------------------------------
    titre("ATTAQUE 2 - BOURRAGE D'IDENTIFIANTS : 1 IP, beaucoup de comptes\n"
          "(identifiants voles ailleurs, 1 essai par compte : aucun compteur\n"
          " par compte ne bouge -- c'est le nombre de comptes qui trahit)")
    for n in [8, 12, 18, 30]:
        ip = f"45.155.{n}.1"
        for i in range(n):
            d = essai(f"vol{n}_{i}@banque.bf", ip)
        signal = next(
            (s for s in d["signaux"] if s["code"] == "bourrage_identifiants"), None
        )
        poids = signal["poids"] if signal else 0
        print(f"  {n:3d} comptes vises   poids {poids:.2f}   score {d['score']:.3f}   "
              f"{d['decision'].upper()}")

    # ------------------------------------------------------------------------
    titre("FAUX POSITIF A EVITER : LE BUREAU DERRIERE UN ROUTEUR NAT\n"
          "(20 employes, une seule adresse publique -- c'est du trafic normal)")
    for i in range(20):
        d = essai(f"bureau{i}@banque.bf", "41.203.50.7", succes=True, pays="BF")
    montrer(d, "20 comptes, 1 IP, tous en succes")
    print("      ^ les agregats par IP ne comptent que les ECHECS")
    for i in range(14):
        d = essai(f"bureau{i}@banque.bf", "41.203.50.7", succes=False, pays="BF")
    montrer(d, "14 de ces comptes en echec (mdp oublie)")
    ReseauDeConfiance.objects.create(
        organisation=org, cidr="41.203.50.0/24", libelle="Siege Ouaga")
    for i in range(14, 20):
        d = essai(f"bureau{i}@banque.bf", "41.203.50.7", succes=False, pays="BF")
    montrer(d, "apres declaration du reseau du siege")
    print("      ^ signaux par IP neutralises, signaux par compte conserves")

    # ------------------------------------------------------------------------
    titre("ATTAQUE 3 - PULVERISATION : beaucoup d'IP, 1 compte\n"
          "(reseau de machines qui repartit pour passer sous les seuils par IP)")
    for i in range(8):
        d = essai("directeur@banque.bf", f"102.64.{i}.{i + 10}")
    montrer(d, "8 adresses sur le meme compte")

    # ------------------------------------------------------------------------
    titre("ATTAQUE 4 - IP DEJA CONNUE (reutilise le module Reputation)")
    mal = Indicateur.objects.filter(type="ip", verdict="malveillant").first()
    if mal:
        montrer(essai("paul@banque.bf", mal.valeur), f"depuis {mal.valeur}")
    tor = Indicateur.objects.filter(type="ip", verdict="inconnu").first()
    if tor:
        montrer(essai("paul@banque.bf", tor.valeur), f"depuis {tor.valeur} (Tor)")

    # ------------------------------------------------------------------------
    titre("VOYAGE IMPOSSIBLE")
    essai("pdg@banque.bf", "41.203.1.1", succes=True, pays="BF")
    montrer(essai("pdg@banque.bf", "91.132.1.1", pays="RU"),
            "connexion BF puis RU dans l'heure")

    # ------------------------------------------------------------------------
    titre("PSEUDONYMISATION : ce qui est reellement en base")
    profil = ProfilCompte.objects.filter(organisation=org).first()
    print(f"  empreinte        {profil.empreinte}")
    print(f"  appareils connus {profil.appareils_connus}")
    print(f"  pays connus      {profil.pays_connus}")
    print(f"  connexions       {profil.connexions_reussies}")
    fuite = ProfilCompte.objects.filter(empreinte__contains="banque.bf").count()
    print(f"\n  occurrences d'un identifiant en clair en base : {fuite}")
    print("  -> seules des empreintes HMAC-SHA256, salees par organisation")

    # ------------------------------------------------------------------------
    titre("MOTS DE PASSE COMPROMIS (protocole k-anonymat)")
    for mdp, occ in [("123456", 9_500_000), ("password", 3_700_000),
                     ("Motdepasse2024!", 12)]:
        e = empreinte_sha1(mdp)
        MotDePasseCompromis.objects.get_or_create(
            prefixe=e[:5], suffixe=e[5:], defaults={"occurrences": occ}
        )
    e = empreinte_sha1("123456")
    r = client.post("/v1/password/check", {"prefixe": e[:5]},
                    content_type="application/json", **entetes).json()
    print(f"  le client envoie 5 caracteres ({e[:5]}) et recoit "
          f"{len(r['suffixes'])} suffixe(s)")
    print("  il compare chez lui : nous n'apprenons pas quel mot de passe "
          "a ete teste")
    r = client.post("/v1/password/check", {"mot_de_passe": "123456"},
                    content_type="application/json", **entetes)
    print(f"\n  envoi en clair : refuse ({r.status_code})")
    print(f"  {r.json()['detail'][:70]}...")

    # ------------------------------------------------------------------------
    titre("LATENCE - cycle HTTP complet, plan bloquant (budget 100 ms)")
    mal_ip = mal.valeur if mal else "41.203.10.5"
    cas = [
        ("compte connu, contexte normal",
         lambda i: essai("marie@banque.bf", "41.203.10.5", pays="BF")),
        ("compte inconnu",
         lambda i: essai(f"neuf{i}@banque.bf", "41.203.10.5")),
        ("IP signalee (requete Reputation)",
         lambda i: essai("marie@banque.bf", mal_ip)),
        ("verification de mot de passe",
         lambda i: client.post("/v1/password/check", {"prefixe": e[:5]},
                               content_type="application/json", **entetes)),
    ]
    for libelle, fonction in cas:
        for i in range(3):
            fonction(i)
        mesures = []
        for i in range(60):
            t0 = time.perf_counter()
            fonction(i)
            mesures.append((time.perf_counter() - t0) * 1000)
        mesures.sort()
        print(f"  {libelle:36s} median {statistics.median(mesures):6.2f} ms"
              f"   p95 {mesures[56]:6.2f} ms")

    print(f"\n  journal en tampon : {journal.en_attente()} lignes non ecrites")
    print(f"  vidage groupe     : {journal.vider(limite=10**6)} lignes")


if __name__ == "__main__":
    executer()
