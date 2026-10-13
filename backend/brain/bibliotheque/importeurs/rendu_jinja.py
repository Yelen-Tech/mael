"""Rendu minimal des conditions Jinja des rule.yml de ComplianceAsCode.

Un rule.yml peut porter un gabarit different selon le systeme :

    {{% if 'ubuntu' in product %}}
    template: {name: systemd_dropin_configuration, ...}
    {{% else %}}
    template: {name: shell_lineinfile, ...}
    {{% endif %}}

Retirer seulement les lignes de controle (ancien comportement) garde les DEUX
branches ; YAML retient la derniere cle : on prenait le gabarit des AUTRES
systemes. Ici on evalue les conditions pour un produit donne (ubuntu2204,
debian12...), sans dependance et sans `eval` : un evaluateur d'expressions
restreint (and/or/not, in/not in, ==/!=, chaines, listes, noms connus).

Ce qui n'est pas compris (boucles, macros, set...) est retire comme avant ;
une condition illisible est evaluee a FAUX et comptee (jamais devinee).
"""
from __future__ import annotations

import ast
import re
from functools import lru_cache
from pathlib import Path

import yaml

PRODUITS = ("ubuntu2204", "ubuntu2404", "debian12")

# Proprietes absentes des product.yml mais utilisees par les regles : valeurs
# par defaut de ComplianceAsCode pour les systemes Debian/Ubuntu.
DEFAUTS = {
    "pwquality_path": "/etc/security/pwquality.conf",
    "journald_conf_dir_path": "/etc/systemd/journald.conf.d",
    "sshd_distributed_config": "false",
    # Ajoutes a la relecture du 18/09/2026 (chemins Debian/Ubuntu ; le module
    # ssg qui les porte n'est pas dans la source clonee). Sans eux, le gabarit
    # recevait un chemin vide (« /grub.cfg », « find / »).
    "sshd_config_dir": "/etc/ssh/sshd_config.d",
    "sshd_main_config_file": "/etc/ssh/sshd_config",
    "grub2_boot_path": "/boot/grub",
    "login_defs_path": "/etc/login.defs",
    "ssh_keysign_path": "/usr/lib/openssh/ssh-keysign",
    "unix_chkpwd_binary": "/usr/sbin/unix_chkpwd",
    "aide_default_path": "/etc/default/aide",
    "audisp_conf_path": "/etc/audit",
    "kdump_service": "kdump-tools",
}
# Variable simple sans valeur dans un gabarit : marquee, jamais remplacee par
# du vide. L'importeur ecarte la regle et donne le nom de la variable.
INCONNUE = "SENTINELLE_VARIABLE_INCONNUE:"

_BALISE = re.compile(r"^\s*\{\{%-?\s*(if|elif|else|endif)\b(.*?)-?%\}\}\s*$")
_VARIABLE = re.compile(r"\{\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}\}")


class _Illisible(Exception):
    pass


@lru_cache(maxsize=8)
def proprietes(source: Path, produit: str) -> dict:
    """product, families et proprietes simples du product.yml."""
    props = dict(DEFAUTS)
    chemin = source / "products" / produit / "product.yml"
    if chemin.exists():
        d = yaml.safe_load(chemin.read_text(encoding="utf-8")) or {}
        props.update({k: v for k, v in d.items()
                      if isinstance(v, (str, int, float, bool, list))})
    props["product"] = produit
    props["families"] = list(props.get("families") or [])
    return props


def evaluer(expression: str, props: dict) -> bool:
    try:
        arbre = ast.parse(expression.strip(), mode="eval").body
        return bool(_valeur(arbre, props))
    except (_Illisible, SyntaxError, TypeError, ValueError):
        return False


def _valeur(n, props):
    if isinstance(n, ast.Constant):
        return n.value
    if isinstance(n, (ast.List, ast.Tuple, ast.Set)):
        return [_valeur(e, props) for e in n.elts]
    if isinstance(n, ast.Name):
        return props.get(n.id)
    if isinstance(n, ast.BoolOp):
        valeurs = (_valeur(v, props) for v in n.values)
        return all(valeurs) if isinstance(n.op, ast.And) else any(valeurs)
    if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.Not):
        return not _valeur(n.operand, props)
    if isinstance(n, ast.Compare):
        gauche = _valeur(n.left, props)
        for op, droite_n in zip(n.ops, n.comparators):
            droite = _valeur(droite_n, props)
            if isinstance(op, (ast.In, ast.NotIn)):
                present = droite is not None and gauche in droite
                ok = present if isinstance(op, ast.In) else not present
            elif isinstance(op, ast.Eq):
                ok = gauche == droite
            elif isinstance(op, ast.NotEq):
                ok = gauche != droite
            else:
                raise _Illisible(type(op).__name__)
            if not ok:
                return False
            gauche = droite
        return True
    raise _Illisible(type(n).__name__)


def rendre(texte: str, props: dict | None) -> str:
    """Texte YAML pour un produit. props=None : ancien comportement (toutes
    les branches gardees), pour les fichiers sans produit (.var)."""
    lignes = []
    # pile : (branche parente active, une branche deja prise, active)
    pile: list[list[bool]] = []

    def actif() -> bool:
        return not pile or pile[-1][2]

    dans_gabarit = False
    for ligne in texte.splitlines():
        if ligne[:1].isalpha():
            dans_gabarit = ligne.startswith("template:")
        m = _BALISE.match(ligne) if props is not None else None
        if m:
            mot, expr = m.group(1), m.group(2)
            if mot == "if":
                parent = actif()
                vrai = parent and evaluer(expr, props)
                pile.append([parent, vrai, vrai])
            elif mot == "elif" and pile:
                parent, prise, _ = pile[-1]
                vrai = parent and not prise and evaluer(expr, props)
                pile[-1] = [parent, prise or vrai, vrai]
            elif mot == "else" and pile:
                parent, prise, _ = pile[-1]
                pile[-1] = [parent, True, parent and not prise]
            elif mot == "endif" and pile:
                pile.pop()
            continue
        if not actif():
            continue
        brut = ligne.strip()
        if brut.startswith(("{{{", "{{%", "{{#")):
            continue
        if props is not None:
            ligne = _VARIABLE.sub(
                lambda v: str(props[v.group(1)]) if isinstance(
                    props.get(v.group(1)), (str, int)) else (
                    INCONNUE + v.group(1) if dans_gabarit else v.group(0)),
                ligne)
        lignes.append(re.sub(r"\{\{\{.*?\}\}\}", "", ligne))
    return "\n".join(lignes)
