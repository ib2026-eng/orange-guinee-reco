---
title: "Système de recommandation de pass — Orange Guinée"
subtitle: "Rapport d'audit : fuite de données et dépendance à la popularité"
date: "30 août 2026"
---

# 1. Contexte et déclencheur

Les métriques obtenues (Precision@1 = 0,970 pour le ranker, AUC = 0,960
pour le classifieur calibré) sont sensiblement au-dessus des repères
usuels pour ce type de tâche de recommandation (repères réalistes
généralement cités : 0,80-0,85 d'AUC, 35-45 % de Precision@1). Un chiffre
inhabituellement élevé n'est pas en soi une preuve d'erreur, mais impose
une vérification explicite avant d'être considéré comme fiable — c'est
l'objet de cet audit.

L'audit a porté sur le pipeline réellement exécuté (code d'entraînement,
schéma effectif des données livrées), et non uniquement sur la
documentation produite en amont.

# 2. Vérification de fuite de données explicite

Le fichier `LEAKAGE_COLUMNS_a_exclure.txt` livré avec le jeu de données
identifie cinq colonnes à proscrire comme features (`mnt_pass_total`,
`nb_pass_total`, `nb_pass_distincts`, `nb_sources_distinctes`,
`nb_canaux_achat_distincts`), car dérivées du même historique d'achats que
la cible à prédire.

**Vérification effectuée** : inspection du schéma réel du fichier
`training_ranking.parquet` (45 colonnes) et de la fonction
`feature_columns()` du code d'entraînement partagé
(`scripts/common.py`), utilisée par les deux scripts d'entraînement
(Modèle A et Modèle B).

**Résultat** : les cinq colonnes interdites sont **absentes du fichier
livré lui-même** — elles ont été exclues en amont de la livraison, donc
structurellement impossibles à utiliser. La fonction `feature_columns()`
n'exclut par ailleurs que quatre colonnes non prédictives (`num`,
`nom_pass_regroupe`, `label`, `flag_date_incoherente`) ; toutes les autres
colonnes du dataset deviennent des features, sans filtrage supplémentaire
susceptible de masquer un oubli.

**Conclusion** : aucune fuite de données explicite identifiée.

# 3. Feature importance du Modèle B (analyse inédite)

La feature importance du Modèle A avait été calculée et documentée dès
son entraînement. Celle du **Modèle B n'avait en revanche jamais été
calculée** avant cet audit — un angle mort identifié et corrigé.

| Feature | Modèle A (% du gain) | Modèle B (% du gain) |
|---|---|---|
| `popularite_n_clients` | 53,8 % | **60,2 %** |
| `n_pass_distincts_verif` | 12,5 % | 15,2 % |
| `type_ressource_prefere` | 9,1 % | 6,1 % |
| **Cumul des 3 premières features** | **75,4 %** | **81,6 %** |

Les deux modèles présentent une structure de dépendance très similaire,
concentrée sur trois variables. Deux d'entre elles ne relèvent pas d'une
personnalisation fine : `popularite_n_clients` décrit la popularité du
pass indépendamment du client, et `n_pass_distincts_verif` décrit le
niveau d'activité générale du client (nombre de pass déjà achetés), pas
son affinité avec un pass précis.

# 4. Piste de quasi-fuite : correspondance de type de ressource

Hypothèse testée : la variable `type_ressource_prefere` (côté client) et
`type_ressource` (côté pass candidat) pourraient produire une règle
quasi-triviale lorsqu'elles coïncident.

**Mesure effectuée** : taux d'achat réel (`label = 1`) sur l'ensemble du
dataset d'entraînement, selon la correspondance entre les deux variables.

| Correspondance `type_ressource_prefere` / `type_ressource` | Taux de positif | Volume |
|---|---|---|
| Oui | 29,5 % | 23 299 719 lignes |
| Non | 21,9 % | 17 551 365 lignes |

**Conclusion** : l'effet est réel et statistiquement notable (+7,6 points,
soit environ +35 % en relatif), mais d'une ampleur modérée — il
n'explique pas, à lui seul, une precision de 97 %. L'hypothèse d'une
quasi-fuite dominante par cette seule variable est écartée.

# 5. Décomposition de l'AUC : popularité seule contre modèle complet

Pour isoler la part du signal réellement attribuable à la
personnalisation, une baseline minimale a été construite : un score basé
**uniquement** sur `popularite_n_clients`, sans aucune information sur le
client, évaluée sur le même jeu de test que le Modèle B officiel
(9 366 765 lignes).

| Configuration | AUC |
|---|---|
| Baseline popularité seule | 0,8749 |
| **Modèle B complet** | **0,9596** |

**Interprétation** : la popularité seule produit déjà un AUC élevé
(0,8749), ce qui explique une large part du niveau global observé — un
catalogue restreint (65 pass) avec une forte concentration des achats (4
pass concentrant environ 50 % du volume) rend la tâche intrinsèquement
plus facile qu'un scénario à catalogue large et diffus, indépendamment de
la qualité du modèle. Le modèle complet ajoute néanmoins un **gain net et
mesuré de +0,085 point d'AUC**, non négligeable, qui constitue la preuve
d'une personnalisation réelle au-delà de la simple popularité.

Ce résultat est cohérent avec la comparaison aux baselines déjà réalisée
pour le Modèle A (ranker), qui affichait un gain de +23,8 points de
NDCG@1 par rapport à la meilleure baseline non-ML (popularité pondérée
par segment).

# 6. Split, taille d'échantillon et cold-start

- **Split train/test** : groupé par client et stratifié (aucun client
  présent à la fois en train et en test, garanti par construction),
  453 355 clients et 9 366 765 lignes côté test — un volume large,
  éliminant tout risque de non-représentativité par sous-échantillonnage.
- **Comparaison aux baselines** : déjà réalisée pour le Modèle A (section
  5), cohérente avec les résultats de décomposition d'AUC du Modèle B
  obtenus dans cet audit.
- **Cold-start** (205 223 clients sans historique) : reste non évaluable
  avec les données disponibles, aucun changement par rapport au
  diagnostic initial — ces clients n'ont, par construction, aucun achat
  observé permettant de vérifier après coup la pertinence d'une
  recommandation.

# 7. Verdict

**Aucune fuite de données n'a été identifiée**, ni explicite (colonnes
proscrites absentes du fichier livré) ni indirecte (aucune variable ne
recalcule une information dérivée de la cible après la période de
prédiction).

Les métriques élevées s'expliquent principalement par une
**caractéristique du domaine** — un catalogue restreint et fortement
concentré — et non par un artefact méthodologique. Le socle de
performance apporté par la popularité seule est important (AUC = 0,875),
mais les modèles ajoutent un gain de personnalisation réel et quantifié
au-dessus de ce socle (+0,085 d'AUC pour le Modèle B, +23,8 points de
NDCG@1 pour le Modèle A face aux meilleures baselines non-ML).

# 8. Recommandation pour la suite

Ne jamais présenter l'AUC ou la Precision de façon isolée dans les
communications futures (rapport, soutenance) : toujours l'accompagner du
chiffre de la baseline de popularité correspondante, pour distinguer
explicitement la part de performance "facile" (propre au domaine) de la
part de performance réellement apportée par le modèle. C'est cette
mise en contexte, absente des métriques brutes initiales, qui a permis de
lever le doute sur une possible fuite de données.
