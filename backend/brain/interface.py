"""Interface plein ecran du terminal MAEL (ecran alterne, barre fixe).

Le mode classique imprime tout a la suite : la barre de saisie se redessine
a chaque tour et l'historique part vers le haut. Ici, comme les clients
modernes (opencode et consorts) :

  - l'ecran alterne est pris pendant la session, rendu a la sortie ;
  - la conversation occupe une ZONE DE DEFILEMENT : seule elle bouge ;
  - la barre de saisie est FIXEE en bas, dessinee une fois, reutilisee ;
  - la saisie est lue TOUCHE PAR TOUCHE (msvcrt sous Windows) : c'est nous
    qui dessinons le champ, donc le texte ne peut pas en sortir — contraire-
    ment a input(), dont l'echo echappe a tout controle.

Ce que l'utilisateur tape est re-ecrit dans la zone (« vous › ... ») pour
que l'historique le garde quand le champ est reinitialise.

Pre-requis : le mode « terminal virtuel » (voir animation.vt_pret). Sans
lui, terminal.py retombe sur le mode classique — jamais l'inverse.
"""
from __future__ import annotations

import os
import shutil
import sys

# Reserve en bas de l'ecran : tete de barre, champ, pied — plus une ligne
# de marge entre la zone qui defile et la barre.
LIGNES_BARRE = 3
MARGE = 1


class Interface:
    def __init__(self, style, flux=None):
        self.style = style
        self.flux = flux or sys.stdout
        self._mesurer()

    def _mesurer(self):
        taille = shutil.get_terminal_size()
        self.largeur = taille.columns
        self.hauteur = taille.lines
        # Derniere ligne de la zone de defilement.
        self.bas_zone = self.hauteur - LIGNES_BARRE - MARGE

    # ------------------------------------------------------------ cycle
    def __enter__(self) -> "Interface":
        w, s = self.flux.write, self.style
        w("\033[?1049h\033[2J\033[H")          # ecran alterne, propre
        w(f"\033[1;{self.bas_zone}r")          # zone de defilement
        w(f"\033[{self.bas_zone};1H")          # curseur en bas de zone
        w(s.reset)
        self.flux.flush()
        return self

    def __exit__(self, *exc) -> None:
        # Tout rendre : zone complete, couleurs, ecran d'origine.
        self.flux.write("\033[0m\033[r\033[?1049l")
        self.flux.flush()

    # ---------------------------------------------------------- affichage
    def ecrire(self, texte: str):
        """Ecrit en bas de la zone de defilement : la barre ne bouge pas."""
        self.flux.write(f"\033[{self.bas_zone};1H{texte}")
        self.flux.flush()

    def dessiner_barre(self, invite: str = "vous"):
        """La barre fixe : ╭─ vous ─╮ / │ › _ / ╰──╯, aux trois dernieres
        lignes de l'ecran. Redessinable a volonte — memes lignes, meme
        place : elle ne se deplace ni ne se multiplie jamais. La region de
        defilement est re-mesuree a chaque appel (redimensionnement)."""
        self._mesurer()
        c, r = self.style.utilisateur, self.style.reset
        bas = self.hauteur
        tete = f"╭─ {invite} " + "─" * max(2, self.largeur - len(invite) - 6) + "╮"
        pied = "╰" + "─" * (self.largeur - 2) + "╯"
        self.flux.write(f"\033[1;{self.bas_zone}r"          # region a jour
                        f"\033[{bas - 2};1H\033[2K{c}{tete}{r}"
                        f"\033[{bas};1H\033[2K{c}{pied}{r}")
        self._champ("")
        self.flux.flush()

    def _champ(self, contenu: str, prompt: str = ""):
        """Le contenu du champ, a sa ligne — jamais plus large que l'ecran :
        un texte long defile horizontalement au lieu de deborder sur le
        pied de la barre."""
        bas = self.hauteur
        c, r = self.style.utilisateur, self.style.reset
        if prompt:
            corps = prompt + contenu          # les prompts sont courts
        else:
            dispo = max(8, self.largeur - 5)
            visible = contenu[-dispo:] if len(contenu) > dispo else contenu
            corps = f"{c}│{r} › {visible}"
        self.flux.write(f"\033[{bas - 1};1H\033[2K{corps}")
        self.flux.flush()

    # ------------------------------------------------------------ saisie
    def lire(self, prompt: str = "") -> str:
        """Lit une ligne dans la barre fixe.

        Sous Windows, les touches sont lues une a une (msvcrt) et le champ
        est redessine par nous : ni l'echo du terminal ni un texte long ne
        peuvent faire sortir la saisie de la barre. Ailleurs, input() dans
        le champ — les consoles POSIX gerent leur echo correctement."""
        if os.name == "nt":
            return self._lire_touches(prompt)
        self.dessiner_barre()
        if prompt:
            self._champ("", prompt=prompt)
        else:
            self.flux.write(f"\033[{self.hauteur - 1};5H")
            self.flux.flush()
        return input()

    def _lire_touches(self, prompt: str = "") -> str:
        import msvcrt
        self.dessiner_barre()
        if prompt:
            self._champ("", prompt=prompt)
        tampon: list[str] = []
        while True:
            touche = msvcrt.getwch()
            if touche in ("\r", "\n"):
                break
            if touche == "\x03":
                raise KeyboardInterrupt
            if touche == "\x1a" and not tampon:      # Ctrl+Z = fin de saisie
                raise EOFError
            if touche == "\x08":                     # retour arriere
                if tampon:
                    tampon.pop()
                    self._champ("".join(tampon), prompt=prompt)
                continue
            if touche in ("\x00", "\xe0"):           # touches etendues
                msvcrt.getwch()                      # (fleches, F1…) : lues
                continue                             # et ignorees
            if touche >= " " and touche != "\x7f":
                tampon.append(touche)
                self._champ("".join(tampon), prompt=prompt)
        return "".join(tampon)


class FluxZone:
    """Remplace self.stdout en mode interface : tout ce qui est « ecrit »
    atterrit en bas de la zone de defilement, jamais sur la barre.

    Meme convention que l'OutputWrapper de Django : write() ajoute un
    saut de ligne si l'appelant n'en a pas mis."""

    def __init__(self, interface: Interface):
        self.interface = interface

    def write(self, texte, ending: str = "\n"):
        if texte is None:
            return
        corps = str(texte)
        if ending and not corps.endswith(ending):
            corps += ending
        self.interface.ecrire(corps)
