# Audit — fuite de données et dépendance à la popularité

Déclenché par une question légitime : nos métriques (Precision@1 = 0,970,
AUC = 0,960) sont-elles trop belles pour être vraies ? Cet audit vérifie
le code d'entraînement réel (pas seulement la documentation) et quantifie
la part de popularité dans les résultats.

## 1. Fuite explicite — absente

Les 5 colonnes de `LEAKAGE_COLUMNS_a_exclure.txt` (`mnt_pass_total`,
`nb_pass_total`, `nb_pass_distincts`, `nb_sources_distinctes`,
`nb_canaux_achat_distincts`) sont **absentes du fichier
`training_ranking.parquet` lui-même** (vérifié sur le schéma réel, 45
colonnes au total) — exclues en amont de la livraison, donc structurellement
impossibles à utiliser. `scripts/common.py::feature_columns()` (utilisée par
les scripts 03 et 04) n'exclut par ailleurs que `num`, `nom_pass_regroupe`,
`label`, `flag_date_incoherente` — tout le reste devient feature.

## 2. Feature importance — jamais vérifiée pour le Modèle B avant cet audit

| Feature | Modèle A (% gain) | Modèle B (% gain) |
|---|---|---|
| `popularite_n_clients` | 53,8% | 60,2% |
| `n_pass_distincts_verif` | 12,5% | 15,2% |
| `type_ressource_prefere` | 9,1% | 6,1% |
| **Cumul top 3** | **75,4%** | **81,6%** |

Concentration très forte sur 3 features pour les deux modèles, dont deux
(`popularite_n_clients`, `n_pass_distincts_verif`) ne sont pas des signaux
de personnalisation fine mais des indicateurs globaux (popularité du
produit, niveau d'activité du client).

## 3. Piste de quasi-fuite : `type_ressource_prefere` vs `type_ressource`

Taux d'achat réel (`label=1`) selon que le type préféré du client
correspond au type du pass candidat :

| Correspondance | Taux de positif | N lignes |
|---|---|---|
| Oui | 29,5% | 23 299 719 |
| Non | 21,9% | 17 551 365 |

Effet réel (+7,6 points, ~35% relatif) mais modéré — n'explique pas à lui
seul une precision de 97%.

## 4. Décomposition de l'AUC du Modèle B — popularité seule vs modèle complet

Baseline construite avec **uniquement** `popularite_n_clients` comme score
(aucune feature client), évaluée sur le même test set (9 366 765 lignes)
que le Modèle B officiel :

| | AUC |
|---|---|
| Baseline popularité seule | 0,8749 |
| **Modèle B complet** | **0,9596** |

**Lecture** : la popularité seule explique une large part du signal
(AUC=0,875, déjà loin du hasard à 0,5), mais le modèle complet ajoute un
gain réel et non négligeable de **+0,085 d'AUC**. Les deux lectures
extrêmes ("c'est de la fuite" / "c'est un excellent modèle personnalisé")
sont incorrectes — la réalité est intermédiaire et maintenant quantifiée.

## 5. Split et échantillon — déjà solides, pas de changement nécessaire

- Split principal : groupé par client, stratifié, 453 355 clients test /
  9 366 765 lignes — aucun chevauchement d'identifiants entre train et
  test (garanti par construction, cf. `scripts/01_build_splits.py`).
- Volume très largement représentatif (comparé à un scénario hypothétique
  à 367 clients évoqué en discussion, non applicable à ce projet).
- Comparaison à baseline déjà réalisée pour le Modèle A :
  **+23,8 points de NDCG@1** vs la meilleure baseline non-ML (popularité
  par segment) — cohérent avec le gain d'AUC mesuré ici pour le Modèle B.

## 6. Cold-start — inchangé

Toujours non évaluable avec les données disponibles (aucun achat observé
pour ces clients pour vérifier après coup) — cf. journal principal.

## Verdict

Pas de fuite de données identifiée. Les modèles s'appuient fortement sur
la popularité des pass (attendu et légitime en recommandation implicite),
mais apportent un gain de personnalisation réel et mesuré au-delà de ce
signal seul (+0,085 AUC pour le Modèle B, +23,8 points de NDCG@1 pour le
Modèle A vs baselines). À documenter clairement dans le rapport : la
performance n'est pas "trop belle pour être vraie" sans explication, elle
est en grande partie portée par un signal de popularité fort — ce qui est
une caractéristique connue du domaine (catalogue restreint à 65 pass,
concentration des achats), pas une anomalie de méthodologie.
