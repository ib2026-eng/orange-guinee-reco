"""
Etape 3 (bake-off) : compare XGBoost / LightGBM / CatBoost en mode
learning-to-rank sur un echantillon de training_ranking, pour choisir
l'algorithme du Modele A (ranker, modes next-best-offer / top-N) avec des
chiffres a l'appui plutot qu'un choix par defaut.

Echantillonnage par CLIENT (pas par ligne) pour preserver l'integrite des
groupes de ranking (tout un client va entierement dans l'echantillon ou pas).
"""
import time
import numpy as np
import pandas as pd
import duckdb

DATA_DIR = "/Users/ibrahimabarry/Projects/orange-guinee-reco/data"
SPLITS_DIR = "/Users/ibrahimabarry/Projects/orange-guinee-reco/splits"
RANDOM_STATE = 42

N_TRAIN_CLIENTS = 150_000
N_TEST_CLIENTS = 30_000

# Colonnes a exclure : identifiants, cible, et colonnes de nature purement
# qualite ambigues (flag_date_incoherente = incoherence logique pure, cf.
# note du prompt). segment/type_ressource_prefere etc. sont conservees.
DROP_COLS = {"num", "nom_pass_regroupe", "label", "flag_date_incoherente"}

CATEGORICAL_COLS = [
    "segment", "region", "device_type", "type_client_dominant",
    "type_ressource_prefere", "type_ressource", "type_client_cible",
]
BOOL_COLS = ["flag_age_moins_15ans", "a_deja_achete_pass", "ambigu"]

con = duckdb.connect()

# ---------------------------------------------------------------------------
# Echantillonnage par client, en gardant le regroupement (order by num)
# ---------------------------------------------------------------------------
print("Echantillonnage...")

def sample_split(split_value, n_clients, seed):
    all_clients = con.execute(f"""
        SELECT num FROM read_parquet('{SPLITS_DIR}/client_split_group.parquet')
        WHERE split_group = '{split_value}'
    """).fetchdf()
    sampled_ids = all_clients["num"].sample(n=n_clients, random_state=seed).to_frame()
    con.register("sampled_ids", sampled_ids)
    df = con.execute(f"""
        SELECT t.*
        FROM read_parquet('{DATA_DIR}/training_ranking.parquet') t
        JOIN sampled_ids s ON t.num = s.num
        ORDER BY t.num
    """).fetchdf()
    con.unregister("sampled_ids")
    return df

train_df = sample_split("train", N_TRAIN_CLIENTS, RANDOM_STATE)
test_df = sample_split("test", N_TEST_CLIENTS, RANDOM_STATE + 1)
print(f"Train sample: {len(train_df)} lignes / {train_df['num'].nunique()} clients")
print(f"Test sample:  {len(test_df)} lignes / {test_df['num'].nunique()} clients")

# ---------------------------------------------------------------------------
# Nettoyage / encodage minimal, coherent entre les 3 librairies
# ---------------------------------------------------------------------------
def clean(df):
    df = df.copy()
    df["region"] = df["region"].replace({"NULL": "inconnu", "A_METTRE_A_JOUR": "inconnu"})
    df["device_type"] = df["device_type"].replace({"NULL": "inconnu"})
    for c in CATEGORICAL_COLS:
        df[c] = df[c].fillna("inconnu").astype("category")
    for c in BOOL_COLS:
        df[c] = df[c].fillna(False).astype("int8")
    return df

train_df = clean(train_df)
test_df = clean(test_df)

# Codes categoriels partages entre train/test (memes categories)
for c in CATEGORICAL_COLS:
    cats = pd.api.types.union_categoricals([train_df[c], test_df[c]]).categories
    train_df[c] = train_df[c].cat.set_categories(cats)
    test_df[c] = test_df[c].cat.set_categories(cats)

feature_cols = [c for c in train_df.columns if c not in DROP_COLS]

def build_groups(df):
    sizes = df.groupby("num", sort=False).size().values
    return sizes

train_groups = build_groups(train_df)
test_groups = build_groups(test_df)

X_train, y_train = train_df[feature_cols], train_df["label"].values
X_test, y_test = test_df[feature_cols], test_df["label"].values

print(f"\nFeatures utilisees ({len(feature_cols)}): {feature_cols}")

# ---------------------------------------------------------------------------
# Metriques de ranking (calcul manuel, par groupe client)
# ---------------------------------------------------------------------------
def ranking_metrics(scores, labels, group_sizes, k_list=(1, 3, 5)):
    results = {f"ndcg@{k}": [] for k in k_list}
    results.update({f"precision@{k}": [] for k in k_list})
    results.update({f"recall@{k}": [] for k in k_list})
    idx = 0
    for size in group_sizes:
        s = scores[idx:idx+size]
        l = labels[idx:idx+size]
        idx += size
        order = np.argsort(-s)
        l_sorted = l[order]
        n_pos = l.sum()
        if n_pos == 0:
            continue
        for k in k_list:
            kk = min(k, size)
            top_k = l_sorted[:kk]
            # DCG
            discounts = 1.0 / np.log2(np.arange(2, kk + 2))
            dcg = (top_k * discounts).sum()
            ideal = np.sort(l)[::-1][:kk]
            idcg = (ideal * discounts).sum()
            ndcg = dcg / idcg if idcg > 0 else 0.0
            results[f"ndcg@{k}"].append(ndcg)
            results[f"precision@{k}"].append(top_k.sum() / kk)
            results[f"recall@{k}"].append(top_k.sum() / n_pos)
    return {k: np.mean(v) for k, v in results.items()}

def coverage_at_k(scores, pass_names, group_sizes, k, n_total_pass):
    idx = 0
    recommended = set()
    for size in group_sizes:
        s = scores[idx:idx+size]
        names = pass_names[idx:idx+size]
        idx += size
        order = np.argsort(-s)[:k]
        recommended.update(names.iloc[order].tolist())
    return len(recommended) / n_total_pass

n_total_pass = train_df["nom_pass_regroupe"].nunique()
test_pass_names = test_df["nom_pass_regroupe"].reset_index(drop=True)

# ---------------------------------------------------------------------------
# Bake-off
# ---------------------------------------------------------------------------
results_summary = []

# ---- LightGBM ----
import lightgbm as lgb
print("\n" + "=" * 80)
print("LightGBM (lambdarank)")
t0 = time.time()
model_lgb = lgb.LGBMRanker(
    objective="lambdarank",
    metric="ndcg",
    n_estimators=200,
    learning_rate=0.05,
    num_leaves=63,
    random_state=RANDOM_STATE,
    verbosity=-1,
)
model_lgb.fit(
    X_train, y_train, group=train_groups,
    categorical_feature=CATEGORICAL_COLS,
)
train_time_lgb = time.time() - t0
t0 = time.time()
scores_lgb = model_lgb.predict(X_test)
infer_time_lgb = time.time() - t0
m = ranking_metrics(scores_lgb, y_test, test_groups)
m["coverage@5"] = coverage_at_k(scores_lgb, test_pass_names, test_groups, 5, n_total_pass)
m["train_time_s"] = train_time_lgb
m["infer_time_s"] = infer_time_lgb
m["model"] = "LightGBM"
results_summary.append(m)
print(f"Train: {train_time_lgb:.1f}s | Infer: {infer_time_lgb:.2f}s")
print({k: round(v, 4) for k, v in m.items() if k != "model"})

# ---- XGBoost ----
import xgboost as xgb
print("\n" + "=" * 80)
print("XGBoost (rank:pairwise)")
X_train_xgb = X_train.copy()
X_test_xgb = X_test.copy()
t0 = time.time()
model_xgb = xgb.XGBRanker(
    objective="rank:pairwise",
    n_estimators=200,
    learning_rate=0.05,
    max_depth=6,
    tree_method="hist",
    enable_categorical=True,
    random_state=RANDOM_STATE,
)
model_xgb.fit(X_train_xgb, y_train, group=train_groups)
train_time_xgb = time.time() - t0
t0 = time.time()
scores_xgb = model_xgb.predict(X_test_xgb)
infer_time_xgb = time.time() - t0
m = ranking_metrics(scores_xgb, y_test, test_groups)
m["coverage@5"] = coverage_at_k(scores_xgb, test_pass_names, test_groups, 5, n_total_pass)
m["train_time_s"] = train_time_xgb
m["infer_time_s"] = infer_time_xgb
m["model"] = "XGBoost"
results_summary.append(m)
print(f"Train: {train_time_xgb:.1f}s | Infer: {infer_time_xgb:.2f}s")
print({k: round(v, 4) for k, v in m.items() if k != "model"})

# ---- CatBoost ----
from catboost import CatBoostRanker, Pool
print("\n" + "=" * 80)
print("CatBoost (YetiRank)")
cat_idx = [X_train.columns.get_loc(c) for c in CATEGORICAL_COLS]
X_train_cb = X_train.copy()
X_test_cb = X_test.copy()
for c in CATEGORICAL_COLS:
    X_train_cb[c] = X_train_cb[c].astype(str)
    X_test_cb[c] = X_test_cb[c].astype(str)

train_pool = Pool(X_train_cb, label=y_train, group_id=train_df["num"].values, cat_features=cat_idx)
test_pool = Pool(X_test_cb, group_id=test_df["num"].values, cat_features=cat_idx)

t0 = time.time()
model_cb = CatBoostRanker(
    loss_function="YetiRank",
    iterations=200,
    learning_rate=0.05,
    depth=6,
    random_seed=RANDOM_STATE,
    verbose=False,
)
model_cb.fit(train_pool)
train_time_cb = time.time() - t0
t0 = time.time()
scores_cb = model_cb.predict(test_pool)
infer_time_cb = time.time() - t0
m = ranking_metrics(scores_cb, y_test, test_groups)
m["coverage@5"] = coverage_at_k(scores_cb, test_pass_names, test_groups, 5, n_total_pass)
m["train_time_s"] = train_time_cb
m["infer_time_s"] = infer_time_cb
m["model"] = "CatBoost"
results_summary.append(m)
print(f"Train: {train_time_cb:.1f}s | Infer: {infer_time_cb:.2f}s")
print({k: round(v, 4) for k, v in m.items() if k != "model"})

# ---------------------------------------------------------------------------
# Tableau final
# ---------------------------------------------------------------------------
print("\n" + "=" * 80)
print("RESUME BAKE-OFF")
summary_df = pd.DataFrame(results_summary).set_index("model")
cols_order = ["ndcg@1", "ndcg@3", "ndcg@5", "precision@1", "precision@3", "precision@5",
              "recall@1", "recall@3", "recall@5", "coverage@5", "train_time_s", "infer_time_s"]
print(summary_df[cols_order].round(4).to_string())
summary_df[cols_order].round(4).to_csv(
    "/Users/ibrahimabarry/Projects/orange-guinee-reco/docs/bakeoff_results.csv"
)
print("\nSauvegarde -> docs/bakeoff_results.csv")
