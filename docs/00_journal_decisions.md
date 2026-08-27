# Journal de décisions — Système de recommandation Orange Guinée

Ce document trace les choix méthodologiques faits à chaque étape, avec leur
justification, pour alimenter le rapport de stage.

## Étape 1 — Évaluation des données

Fichiers livrés (voir `Prompt_entrainement_modele.md` et
`LEAKAGE_COLUMNS_a_exclure.txt` dans `data/`) : vérifiés conformes au
dictionnaire de données fourni. Points confirmés par exploration directe :

- 2 471 994 clients dans `features_client.parquet`, dont 205 223 en
  cold-start (`a_deja_achete_pass=False`), 100% cohérent avec
  `jours_depuis_dernier_achat==9999`.
- 65 pass distincts, cohérents entre `features_pass`,
  `interactions_client_pass` et `training_ranking`.
- `training_ranking.parquet` (46 819 581 lignes) : 0 doublon
  (num, nom_pass_regroupe), ratio négatifs/positifs = 3.0 exactement
  **par client** (pas seulement en moyenne globale) — le sampling est propre.
- Les 205 223 clients cold-start **n'apparaissent pas du tout** dans
  `training_ranking` → à traiter à 100% par la stratégie de repli séparée
  (pas de risque de fuite involontaire du cold-start dans l'entraînement
  principal).
- Données sales confirmées (déjà signalées dans le prompt) : `region`
  contient "NULL" et "A_METTRE_A_JOUR" (3 644 lignes), `device_type`
  contient "NULL" textuel (547 385 lignes, ~22%) → à filtrer/imputer avant
  modélisation.
- Anomalie non documentée dans le prompt : `training_ranking` contient deux
  colonnes dupliquées `n_achats_international_1` / `n_achats_pour_tiers_1`
  (collision de nom lors de la jointure features_client × features_pass qui
  ont chacun une colonne de ce nom) → à clarifier laquelle est fiable avant
  de les utiliser comme features.
- `volume_mo_moyen` : 45,8% de valeurs manquantes dans `training_ranking`,
  cohérent avec les pass de type sms/voix/mixte pour lesquels un volume Mo
  n'a pas de sens (pas un défaut de qualité, mais à gérer explicitement en
  feature engineering, ex. imputation par type_ressource).

## Étape 2 — Split train/test

**Contrainte clé découverte** : `training_ranking.parquet` ne contient
**aucune colonne date** — `dernier_achat` existe seulement dans
`interactions_client_pass.parquet`. Un split temporel nécessite donc une
jointure explicite sur (num, nom_pass_regroupe) pour la récupérer.

### Split principal (référence pour l'entraînement/évaluation des 4 modes)

Groupé par client (`num`), stratifié sur `type_client_dominant`, 80/20.

- Pourquoi groupé : les modèles de ranking group-wise (LambdaMART etc.)
  raisonnent par groupe de candidats pour un même client — couper un
  client entre train et test casserait la structure de groupe et fausserait
  l'évaluation par requête (le prompt lui-même signalait ce risque).
- Pourquoi stratifié sur `type_client_dominant` : B2B (19 clients) et M2M
  (15 clients) sont si minoritaires qu'un split aléatoire simple pourrait
  les éliminer complètement d'un des deux côtés. La stratification garantit
  leur présence dans train ET test (~80/20 vérifié : B2B 78,9/21,1%,
  M2M 80/20%, box_fixe 80,1/19,9%, grand_public 80/20%).
- Résultat : 1 813 416 clients train / 453 355 clients test →
  37 452 816 lignes train / 9 366 765 lignes test dans `training_ranking`,
  ratio positifs/négatifs préservé des deux côtés (~1:3).
- Fichier : `splits/client_split_group.parquet` (num, type_client_dominant,
  segment, split_group).

### Split temporel (contrôle de sensibilité — PAS une simulation de production)

Calculé initialement comme : pour chaque client, date de sa dernière
interaction positive (`MAX(dernier_achat)` par client), cutoff au quantile
80% → train/test.

**Biais découvert en validant la distribution** : la date du dernier achat
n'est pas indépendante de l'intensité d'achat. 858 362 clients (38%) ont
leur dernier achat exactement le dernier jour de la fenêtre (2026-08-20),
et ce groupe a un profil très différent : 165,9 achats / 6,4 pass distincts
en moyenne contre 57,8 / 4,4 pour les autres. C'est un effet de censure à
droite normal (un client qui achète souvent a mécaniquement plus de chances
que son achat le plus récent tombe near la fin de la fenêtre observée),
**pas un défaut des données**, mais ça signifie que le groupe "test
temporel" sur-représente les clients les plus actifs — non représentatif de
la population générale.

**Limite structurelle plus fondamentale** : `features_client` et
`features_pass` sont des agrégats statiques calculés sur toute la fenêtre
de 6 mois, pas des features "au jour T". Un vrai split temporel de
production (entraîner avec l'information disponible à T, évaluer sur ce qui
se passe après T) demanderait de recalculer les features au moment du
cutoff, ce qui n'est pas possible avec les fichiers livrés en l'état.

**Décision** : conserver ce split tel que calculé (train=1 408 409 / 
test=858 362 clients) mais le présenter dans le rapport comme un **contrôle
de sensibilité documenté**, avec le biais de sur-représentation des gros
acheteurs explicitement mentionné — pas comme une validation temporelle de
production rigoureuse. Le split principal groupé/stratifié reste la seule
référence pour le choix et la comparaison des modèles.

Fichier : `splits/client_split_temporal.parquet` (num,
derniere_interaction_positive, split_temporal).

## Étape 3 — Modèles et algorithmes

### Architecture retenue

| Modèle | Type | Entraîné sur | Sert à |
|---|---|---|---|
| A — Ranker | LightGBM `lambdarank` (LTR) | `training_ranking` (split principal) | Modes 1 & 2 : next-best-offer, top-N |
| B — Classifieur calibré | LightGBM `binary` + calibration isotonique | `training_ranking` (split principal) | Mode 4 : P(achat) fiable pour le ROI |
| C — ALS implicite | Factorisation matricielle (`implicit`) | `interactions_client_pass` | Mode 3 : filtrage collaboratif |
| Fallback cold-start | Popularité pondérée par segment | `features_client` + `features_pass` | 205 223 clients sans historique |

Pourquoi A et B sont deux modèles distincts (pas un seul détourné) : un score
`lambdarank` n'est valide qu'en ordre relatif *à l'intérieur d'un groupe
client* — ce n'est pas une probabilité comparable entre clients. Le mode
hybride ROI a besoin de `P(achat) x prix_catalogue`, donc d'une vraie
probabilité calibrée, d'où un classifieur binaire séparé plutôt que de
réutiliser le score du ranker hors de son contexte de groupe.

### Bake-off XGBoost / LightGBM / CatBoost (Modèle A)

Comparaison sur un échantillon groupé par client (150 000 clients train /
30 000 clients test, échantillonnage par client pour préserver l'intégrité
des groupes de ranking), mêmes features, mêmes hyperparamètres de base
(200 arbres, learning_rate=0.05, profondeur~6) :

| Modèle | NDCG@5 | Precision@5 | Recall@5 | Coverage@5 | Train | Infer |
|---|---|---|---|---|---|---|
| **LightGBM** | **0.9175** | **0.6965** | **0.7746** | **0.677** | **13.1s** | 0.75s |
| XGBoost | 0.9054 | 0.6875 | 0.7649 | 0.646 | 29.4s | 0.27s |
| CatBoost | 0.9091 | 0.6905 | 0.7683 | 0.631 | 148.0s | 0.04s |

**Décision : LightGBM `lambdarank` retenu pour le Modèle A.** Meilleur sur
toutes les métriques de ranking (NDCG/precision/recall/coverage) ET le plus
rapide à entraîner (facteur ~11x vs CatBoost, ~2.2x vs XGBoost) — décisif
puisque le modèle final sera entraîné sur les 37,4M lignes du split
principal complet, et potentiellement réentraîné périodiquement en
production. CatBoost n'a l'avantage qu'en latence d'inférence (0.04s), non
déterminant ici vu les volumes d'inférence attendus. Détails :
`docs/bakeoff_results.csv`.

Note technique : encodage catégoriel natif par librairie (category dtype
pandas partagé entre train/test pour des codes cohérents), valeurs
manquantes laissées telles quelles (gérées nativement par les 3
librairies), `region`="NULL"/"A_METTRE_A_JOUR" et `device_type`="NULL"
renormalisés en catégorie "inconnu" avant entraînement. Colonnes dupliquées
`n_achats_international_1`/`n_achats_pour_tiers_1` conservées comme
features distinctes (l'une est l'agrégat client, l'autre l'agrégat pass —
pas une vraie redondance, cf. étape 1) ; `flag_date_incoherente` exclu des
features (incohérence logique pure, conforme à la note du prompt).

### Entraînement pleine échelle du Modèle A

Mêmes hyperparamètres que le bake-off (200 arbres, lr=0.05, num_leaves=63),
entraînés sur les 37 452 816 lignes du split train / évalués sur les
9 366 765 lignes du split test complet (`scripts/03_train_model_a_ranker.py`).

- Chargement (DuckDB, jointure + tri par client) : train 198s, test 13s.
- Entraînement : 144,8s (2,4 min). Inférence sur le test complet : 11,9s.
- **Résultats quasi identiques à l'échantillon du bake-off** (NDCG@5=0.918
  vs 0.9175 sur l'échantillon) → pas de surprise d'échelle, le modèle est
  stable. Coverage@5 monte à 84,6% sur le test complet (contre 67,7% sur
  l'échantillon réduit, cohérent avec un catalogue mieux couvert sur plus
  de clients).
- Métriques complètes : NDCG@1/3/5 = 0.970/0.930/0.918 ;
  Precision@1/3/5 = 0.970/0.816/0.697 ; Recall@1/3/5 = 0.296/0.606/0.775.
  Détails : `docs/model_a_fullscale_results.csv`.
- **Feature importance (gain)** : `popularite_n_clients` domine très
  largement (4,46e7, ~4x la 2e feature `n_pass_distincts_verif` à 1,04e7).
  C'est un biais de popularité classique en recommandation implicite (les
  pass populaires sont mécaniquement plus souvent achetés) — attendu vu que
  cette colonne est validée non-fuyante (absente de
  `LEAKAGE_COLUMNS_a_exclure.txt`, agrégat au niveau pass, pas au niveau
  client). À surveiller pour le mode hybride ROI et la diversité : le
  modèle pourrait sur-recommander les pass déjà populaires si les features
  clients n'apportent pas assez de signal différentiel — la coverage@5 de
  84,6% suggère que ce n'est pas (encore) un problème dominant, mais à
  garder en tête pour l'analyse de diversité de l'étape 4.
  Détails : `docs/model_a_feature_importance.csv`.
- Modèle sauvegardé : `models/model_a_lgbm_ranker.txt` (format natif
  LightGBM Booster).

### Comparaison à des baselines non-ML (validation du gain réel)

Question posée après coup : les métriques du Modèle A sont bonnes en
absolu, mais est-ce que le ML apporte vraiment quelque chose par rapport à
une heuristique simple sans modèle ? (`scripts/07_baseline_comparison.py`)

Deux baselines évaluées sur **exactement le même test set** (9 366 765
lignes) avec les **mêmes fonctions de métriques** que le Modèle A, pour une
comparaison strictement équitable :
- **Popularité globale** : score = `popularite_n_clients` (aucune info
  client utilisée).
- **Popularité pondérée par segment** : score = popularité du pass au sein
  du segment du client (même table que le fallback cold-start).

| | NDCG@1 | NDCG@5 | Precision@1 | Recall@5 | Coverage@5 |
|---|---|---|---|---|---|
| Baseline popularité globale | 0,732 | 0,769 | 0,732 | 0,707 | 75,4% |
| Baseline popularité par segment | 0,741 | 0,782 | 0,741 | 0,713 | 75,4% |
| **Modèle A (LightGBM)** | **0,970** | **0,918** | **0,970** | **0,775** | **84,6%** |

**Conclusions :**
- Le `segment` seul (heuristique sans ML) n'apporte quasiment rien
  (+0,9 pt de NDCG@1 vs popularité pure) — la segmentation CRM ne
  contient pas beaucoup plus de signal prédictif que la popularité brute.
- **Le Modèle A apporte un gain net et important** : +23,8 points de
  NDCG@1 et +22,9 points vs la meilleure des deux baselines. Ce n'est donc
  pas un modèle qui se contente de reproduire la popularité (ce que son
  feature importance dominé par `popularite_n_clients` aurait pu laisser
  craindre, cf. section précédente) — il capture un vrai signal
  personnalisé.
- Le Modèle A est aussi **plus diversifié** que les deux baselines
  (coverage@5 84,6% vs 75,4%), ce qui écarte l'hypothèse d'un modèle qui
  sur-concentrerait ses recommandations sur quelques pass populaires au
  détriment de la couverture du catalogue.
- Détails : `docs/model_a_vs_baselines.csv`.

### Modèle B (classifieur binaire calibré)

Calibration choisie : **isotonique** (validé avec l'utilisateur — volume de
données largement suffisant pour éviter l'overfitting isotonique, plus
flexible que Platt/sigmoïde). Split additionnel dans le train principal
pour éviter une calibration optimiste : `train_fit` (90% des clients train,
33 715 874 lignes, entraînement du classifieur) / `train_calib` (10%,
3 736 942 lignes, jamais vu par le classifieur, sert uniquement à ajuster
l'IsotonicRegression). Évaluation finale sur le split test complet, jamais
vu ni par le classifieur ni par le calibrateur.
(`scripts/04_train_model_b_classifier.py`)

- **AUC = 0.9596** (identique avant/après calibration, transformation
  monotone — attendu).
- **Brier score : 0.06774 (brut) → 0.06752 (calibré)**.
- Courbe de fiabilité : le modèle brut était déjà globalement correct mais
  systématiquement trop confiant dans les déciles bas/moyens et pas assez
  dans les déciles hauts (ex. décile 88,4-99,9% : prédit 0,949 vs observé
  0,968). Après calibration isotonique, la courbe est quasi parfaite sur
  les 10 déciles (ex. même décile : prédit 0,969 vs observé 0,969).
  Détails : `docs/model_b_results.csv`,
  `docs/model_b_calibration_curve_{raw,calibrated}.csv`.
- Modèle + calibrateur sauvegardés : `models/model_b_lgbm_classifier.txt`,
  `models/model_b_isotonic_calibrator.joblib`.

### Modèle C (ALS implicite, filtrage collaboratif)

Méthodologie validée avec l'utilisateur (différente du split groupe A/B,
nécessaire structurellement) : entraînement sur **100% des 2 266 771
clients actifs** (chaque client doit avoir un vecteur latent pour servir le
mode 3 en production), évaluation par **leave-one-out par client** : achat
le plus récent masqué pour les clients ayant ≥2 pass distincts achetés
(2 049 686 clients évalués), entraînement sur le reste (9 658 868
interactions), puis vérification si l'item masqué réapparaît dans le
top-K recommandé. (`scripts/05_train_model_c_als.py`)

Hyperparamètres : `implicit.als.AlternatingLeastSquares`, confiance =
`1 + 40 × nb_achats` (formule standard Hu et al.), 64 facteurs,
régularisation 0,01, 15 itérations — valeurs de départ raisonnables, pas de
tuning à ce stade (cohérent avec la décision prise pour A/B).

- **Entraînement : 58,1s**. Inférence (recommandations pour 2,05M clients
  évalués) : 18,7s.
- **Hit-rate@1/3/5/10 : 53,0% / 86,6% / 92,9% / 98,1%** ; NDCG@1/3/5/10 :
  0,530 / 0,721 / 0,747 / 0,765. Très au-dessus du hasard (baseline @10
  ≈ 15,4% avec 65 pass au total) — signal collaboratif fort.
- **Coverage@10 = 100%** : les 65 pass sont tous recommandés à au moins un
  client, aucun problème de repli sur un sous-ensemble populaire pour ce
  modèle (contraste avec le biais de popularité observé sur le Modèle A).
- Modèle sauvegardé : `models/model_c_als_user_factors.npy`,
  `models/model_c_als_item_factors.npy` + mappings
  `model_c_{user,item}_categories.csv`.
  Détails : `docs/model_c_results.csv`.

### Fallback cold-start (205 223 clients sans historique)

Ni l'ALS (aucune interaction) ni les modèles A/B (features de comportement
pass à `aucun_achat`/NaN) ne s'appliquent aux clients
`a_deja_achete_pass=False`. `segment`/`region`/`device_type` sont les
**seuls signaux disponibles** (segment basé sur `mnt_recharge_6m`,
calculable indépendamment de tout achat de pass — vérifié : les 205 223
clients cold-start ont tous un `segment` valide, répartis sur les 11
catégories S00-S09/autre, aucune valeur manquante).
(`scripts/06_build_coldstart_fallback.py`)

Approche : popularité des pass (nombre de clients distincts ayant acheté,
plus robuste qu'un simple volume d'achats dominé par quelques gros
acheteurs) calculée **par segment, à partir des clients actifs**, appliquée
comme recommandation par défaut aux clients cold-start du même segment.
Fallback global (toutes segments confondus) en secours si un segment est
absent/inconnu.

- Les 65 pass sont représentés dans chaque segment (pas de problème de
  sparsité).
- Les tops par segment restent dominés par les mêmes pass très populaires
  globalement (`Pass_230Mo`, `Pass_50Mo`, `Choco_Malin_1/2`), mais avec une
  différenciation réelle en 4e-5e position selon le segment (ex.
  `Pass_My_Friends` remonte dans S02-S05, `Pass_600Mo` dans S06-S08) —
  la segmentation apporte un signal, sans être spectaculaire.
- **Limite assumée et documentée** : contrairement aux modèles A/B/C, ce
  fallback ne peut **pas être évalué** avec les données livrées — les
  clients cold-start n'ont par construction aucun achat observé (ni dans
  `training_ranking`, ni dans `interactions_client_pass`) pour vérifier
  après coup si la recommandation aurait été pertinente. À signaler
  explicitement dans le rapport de stage comme une limite du jeu de
  données, pas un oubli méthodologique.
- Tables sauvegardées : `models/coldstart_popularity_by_segment.csv`,
  `models/coldstart_popularity_global.csv`.

## Étape 6 — API

FastAPI (`api/main.py`), tous les artefacts chargés une seule fois au
démarrage (`lifespan`), pas de rechargement par requête :
`features_client.parquet` indexé par `num`, les 2 boosters LightGBM
natifs (`lgb.Booster(model_file=...)`), le calibrateur isotonique
(joblib), les facteurs ALS (`.npy`) + mappings, les tables de popularité
cold-start, et un index client→pass achetés (pour filtrer les doublons en
mode 3).

Endpoints conformes au prompt d'origine, fallback cold-start transparent
(le routage vers la popularité par segment se fait automatiquement selon
`a_deja_achete_pass`, l'appelant n'a rien à spécifier) :
- `POST /recommend/next-best-offer/{client_id}`
- `POST /recommend/top-n/{client_id}?n=5`
- `POST /recommend/similar-clients/{client_id}?n=5`
- `POST /recommend/hybrid-roi/{client_id}?n=5`
- `GET /health`

**Point technique clé découvert en implémentant** : LightGBM sérialise et
restaure automatiquement le mapping catégoriel (`booster.pandas_categorical`)
dans le fichier modèle sauvegardé. Il suffit donc de passer les colonnes en
dtype `category` (n'importe quelles catégories présentes dans la requête) —
`_data_from_pandas` réaligne automatiquement via
`.cat.set_categories(...)` sur les codes appris à l'entraînement. Pas besoin
de gérer manuellement les mappings catégoriels côté API.

**Bug rencontré et corrigé** : `features_client.loc[client_id]` (index
scalaire) renvoie une `Series` unifiée en dtype `object` (mélange
str/bool/float d'une ligne), ce que LightGBM refuse en prédiction — corrigé
en utilisant `.loc[[client_id]]` (liste) qui renvoie un `DataFrame` et
préserve le dtype propre de chaque colonne. Egalement : `flag_date_incoherente`
doit être explicitement exclu des features servies (il l'était déjà à
l'entraînement, mais pas dropé côté API avant la prédiction).

**Validation manuelle effectuée** (serveur de développement, port 8756) :
les 4 endpoints + `/health` testés avec un client actif et un client
cold-start réels. Résultat notable : le mode hybride ROI reclasse
correctement par valeur attendue plutôt que par probabilité brute — ex.
pour un client test, `Pass_600Mo` (proba 0,85 × prix 6945 = valeur
attendue 5913) passe devant `Pass_230Mo` (proba 0,999 × prix 3223 = valeur
attendue 3221) alors que `Pass_230Mo` était classé 1er en pur ranking —
le mode hybride change bien l'ordre, pas juste un alias du ranking.
Latence mesurée : ~10-20ms par requête (65 candidats scorés par appel,
modèles déjà en mémoire).

### Dockerisation

`Dockerfile` + `docker-compose.yml` + `.dockerignore` ajoutés
(`api/requirements.txt` avec versions figées d'après l'environnement local
qui a servi à entraîner/valider). Image volontairement légère : ne contient
que le code (`api/main.py`, `scripts/common.py`) — `data/` et `models/`
sont montés en volume au lancement plutôt que copiés dans l'image, pour ne
pas avoir à reconstruire l'image à chaque réentraînement et éviter
d'embarquer des fichiers dont l'API n'a pas besoin (`training_ranking.parquet`,
1,4 Go, sert uniquement à l'entraînement).

`scripts/common.py` modifié pour lire `DATA_DIR`/`SPLITS_DIR`/`MODELS_DIR`/
`DOCS_DIR` depuis des variables d'environnement (`RECO_DATA_DIR` etc.), avec
les chemins absolus locaux comme valeurs par défaut — aucun changement de
comportement pour les scripts existants, mais le conteneur peut pointer
vers `/app/data`/`/app/models` (chemins définis dans le `Dockerfile`).

**Validé en conditions réelles** après installation de Docker Desktop par
l'utilisateur : `docker compose build` puis `docker compose up -d`, les 4
endpoints + `/health` testés dans le vrai conteneur (client actif, client
cold-start, client inconnu → 404), résultats identiques à l'exécution
locale non-conteneurisée.

**Incident de build rencontré et corrigé** : `apt-get update` échouait dans
l'image de base (`Connection failed` sur le port 80) — le réseau utilisé
bloque le HTTP sortant en clair mais laisse passer le HTTPS. Les sources
apt de l'image `python:3.13-slim` (format deb822,
`/etc/apt/sources.list.d/debian.sources`) pointent par défaut en `http://`
; corrigé par un `sed` vers `https://deb.debian.org` avant `apt-get update`
dans le `Dockerfile`. Diagnostiqué en isolant le problème avec un
conteneur `python:3.13-slim` jetable (le `docker pull` de l'image passait
par HTTPS et fonctionnait, seul `apt-get` en HTTP échouait — ce qui a
pointé directement vers la source du blocage).

Pour builder et lancer :
```
cd ~/Projects/orange-guinee-reco
docker compose up --build
# puis : curl -X POST http://localhost:8000/recommend/top-n/<client_id>?n=5
```
