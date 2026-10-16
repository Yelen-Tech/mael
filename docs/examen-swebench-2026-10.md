# Examen SWE-bench Lite — répétitions des 15 et 16 octobre 2026

Transparence : ce document dit ce qui s'est **réellement** passé, sans
embellir. Deux répétitions du même examen, sur Kaggle (GPU T4 ×2), avec le
même tirage fixe de **20 tickets** pris dans les 300 de SWE-bench Lite, le
même modèle (Qwen3-Coder-30B-A3B, Q4_K_M, 32 768 jetons de contexte), la
même règle : **le ticket seul** (sans les indices des mainteneurs), **un
seul essai**, et un verdict honnête — MAEL ne dit « résolu et vérifié » que
s'il l'a prouvé par les tests.

- **v8** (15/10) : MAEL `3bf819c`, llama.cpp `5cdadfc`.
- **v9** (16/10) : MAEL `2075341` — avec trois corrections faites entre les
  deux : les outils de construction d'un projet compilé sont installés à la
  date du code avant lui ; les motifs de refus des reproductions sont
  consignés ; les voisinages sont montrés quand un texte à remplacer est
  ambigu.

## Verdicts ticket par ticket

| Ticket | v8 | v9 | Note v9 |
|---|---|---|---|
| django-13230 | **résolu-vérifié** | **résolu-vérifié** | tenu |
| pytest-9359 | échec | échec | reproduction validée cette fois (au 2e essai) |
| matplotlib-25433 | modifié-non-vérifié | échec | **env réparé** : reproduction validée ; correctif faux, dit honnêtement |
| seaborn-3010 | modifié-non-vérifié | échec | reproduction validée ; correctif faux, dit honnêtement |
| sympy-12236 | échec (0 ligne) | modifié-non-vérifié | le feedback « texte ambigu » a débloqué le correctif (16 lignes) |
| pylint-7114 | échec | modifié-non-vérifié | 25 lignes |
| django-15695 | échec | modifié-non-vérifié | 19 lignes |
| sympy-21627 | modifié-non-vérifié | modifié-non-vérifié | env de l'agent sans mpmath (voir ci-dessous) |
| sympy-12454 | modifié-non-vérifié | modifié-non-vérifié | idem |
| sympy-13031 | modifié-non-vérifié | modifié-non-vérifié | idem |
| sympy-14308 | modifié-non-vérifié | modifié-non-vérifié | idem |
| sympy-14774 | modifié-non-vérifié | modifié-non-vérifié | idem |
| sympy-22005 | modifié-non-vérifié | modifié-non-vérifié | idem |
| django-15202 | modifié-non-vérifié | modifié-non-vérifié | reproduction refusée (3 essais, motifs visibles) |
| scikit-learn-25747 | modifié-non-vérifié | modifié-non-vérifié | env de l'agent sans le module compilé `_check_build` |
| django-14787 | échec | échec | reproduction validée en v8, perdue en v9 (motifs visibles) |
| django-11422 | échec (0 ligne) | échec (0 ligne) | format du correctif, encore |
| django-11742 | échec | échec | |
| django-15819 | échec (0 ligne) | échec (0 ligne) | format du correctif, encore |
| xarray-4248 | échec | échec | reproduction validée |
| astropy-6938 | environnement impossible | environnement impossible | contrôle sous Linux ; la récupération du sous-module git est faite côté MAEL, la construction reste à confirmer |

## Compteurs

| | v8 | v9 |
|---|---|---|
| Résolu-vérifié | 1 | 1 |
| Reproductions exécutées et confirmées (échec avant correction) | 9 | 8 (matplotlib et seaborn en plus, 3 Django en moins) |
| Modifié-non-vérifié | 10 | 11 |
| Échec dit honnêtement | 9 | 8 |

## Ce que v9 a prouvé

1. **Les projets compilés sont testables** : matplotlib est passé de
   « 0 test sur 55 » (imports cassés par un numpy incohérent) à un contrôle
   **VALIDE**, et l'agent y a validé une reproduction pour la première fois.
2. **Les motifs de refus changent tout au diagnostic** : ils ont montré que
   les 7 tickets sympy échouent pour une raison unique et **indépendante du
   modèle** — l'environnement de test de l'agent n'a pas `mpmath`, le
   conftest de sympy ne s'importe pas, chaque reproduction meurt à la
   collecte. C'était la cause invisible du 0/7 de v8.
3. **L'honnêteté tient** : aucun faux « résolu » ; les correctifs faux sont
   testés, vus échouer, et dits.

## La note, sans détour

- **Auto-notation stricte de MAEL : 1 / 20 résolu-vérifié (5 %).** C'est la
  seule note mesurée à ce jour. « Modifié-non-vérifié » ne compte pas :
  certains de ces correctifs sont peut-être bons, mais non prouvés.
- **La note officielle SWE-bench (sb-cli, conteneurs) n'a pas encore été
  calculée** sur ce lot ; elle exige de rejouer `predictions.jsonl` dans
  les conteneurs de l'équipe SWE-bench.
- Le tirage de 20 tickets n'est pas le benchmark entier : il contient 7
  tickets sympy bloqués par l'environnement de l'agent (cause identifiée,
  correction en cours) — le taux sur les 300 ne peut pas en être déduit.

## Prochaines étapes (dans l'ordre)

1. Réparer l'environnement de test de l'agent pour sympy (mpmath) et
   scikit-learn (`_check_build`) — 8 tickets du tirage concernés.
2. Confirmer sous Linux la construction d'astropy 2017 (sous-module git
   désormais récupéré).
3. Calculer la note officielle sb-cli sur `predictions.jsonl`.
4. Nouvelle répétition (v10), même tirage, pour mesurer l'effet de ces
   corrections avant l'examen des 300.
