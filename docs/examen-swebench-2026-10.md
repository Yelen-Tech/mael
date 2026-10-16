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
- **v10** (16/10) : MAEL `fd5fe41` — l'environnement de test est construit
  au niveau qui porte la recette (racine du dépôt), ce qui répare sympy
  (mpmath) et scikit-learn (`_check_build`).

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

## v10 — la chaîne est réparée, le modèle mis à nu

| Ticket | v10 | Note v10 |
|---|---|---|
| sympy-21627 | échec | **reproduction validée** (morte à la collecte en v9) |
| sympy-12236 | modifié-non-vérifié | **reproduction validée** |
| sympy-14774 | échec | **reproduction validée** |
| sympy-12454 | échec | **reproduction validée** |
| sympy-22005 | échec | **reproduction validée** |
| sympy-13031 | échec | le modèle a écrit 3 tests qui passent sur le code buggé |
| sympy-14308 | modifié-non-vérifié | blocs illisibles du modèle (2 essais) |
| django-13230 | modifié-non-vérifié | **perdu** : 3 tests du modèle passent sur le code buggé (il l'avait réussi en v8 et v9 — variance du modèle, la chaîne a refusé ses mauvais tests honnêtement) |
| django-15202, 14787, 15695, pylint-7114, scikit-learn-25747 | modifié-non-vérifié | correctifs appliqués, non prouvés |
| pytest-9359, matplotlib-25433, django-11422, 11742, 15819, xarray-4248, seaborn-3010 | échec | reproductions validées ; correctifs testés et faux, dits honnêtement |

| Compteurs | v8 | v9 | v10 |
|---|---|---|---|
| Résolu-vérifié | 1 | 1 | **0** |
| Reproductions exécutées et confirmées | 9 | 8 | **12 (record, dont 5/7 sympy)** |
| Modifié-non-vérifié | 10 | 11 | 8 |
| Échec dit honnêtement | 9 | 8 | 12 |

**Lecture honnête.** Le correctif d'environnement a pleinement marché :
les tests tournent partout (sauf astropy, construction 2017 toujours à
confirmer, et scikit-learn dont le contrôle reste « à voir »). Le score
baisse à 0/20 **parce que le thermomètre est devenu juste** : en v8/v9,
« modifié-non-vérifié » couvrait des correctifs jamais testés ; en v10 ils
sont testés, et la plupart échouent. Le goulot d'étranglement n'est plus
l'environnement ni la chaîne : c'est le **modèle** (tests écrits « à
l'envers », qui attendent le bug ; correctifs qui ne passent pas ses
propres tests).

## La note, sans détour

- **Auto-notation stricte de MAEL : 1 / 20 en v8 et v9, 0 / 20 en v10.**
  « Modifié-non-vérifié » ne compte pas : certains de ces correctifs sont
  peut-être bons, mais non prouvés.
- **La note officielle SWE-bench (sb-cli, conteneurs) n'a pas encore été
  calculée** sur ce lot ; elle exige de rejouer `predictions.jsonl` dans
  les conteneurs de l'équipe SWE-bench.
- Le tirage de 20 tickets n'est pas le benchmark entier — le taux sur les
  300 ne peut pas en être déduit.

## Prochaines étapes (dans l'ordre)

1. Guider l'écriture des tests de reproduction par le modèle (motif de
   refus n°1 : « ton test réussit sur le code actuel ») et la localisation
   fine — chantier modèle, maintenant que tout s'exécute.
2. Confirmer sous Linux la construction d'astropy 2017 (sous-module git
   désormais récupéré) et le contrôle de scikit-learn.
3. Calculer la note officielle sb-cli sur `predictions.jsonl`.
4. Nouvelle répétition (v11), même tirage, pour mesurer l'effet du
   chantier modèle avant l'examen des 300.
