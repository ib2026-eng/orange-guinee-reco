"""
Etape 3 (entrainement final) : Modele A = LightGBM lambdarank a pleine
echelle sur le split principal (37,4M lignes train / 9,37M lignes test).

Hyperparametres reutilises tels quels depuis le bake-off (02_bakeoff_ranking.py) :
200 arbres, learning_rate=0.05, num_leaves=63 -- pas de nouvelle recherche
d'hyperparametres a ce stade (decision validee avec l'utilisateur).
"""
import time
import numpy as np
import pandas as pd
import duckdb
import lightgbm as lgb

DATA_DIR = "/Users/ibrahimabarry/Projects/orange-guinee-reco/data"
SPLITS_DIR = "/Users/ibrahimabarry/Projects/orange-guinee-reco/splits"
MODELS_DIR = "/Users/ibrahimabarry/Projects/orange-guinee-reco/models"
DOCS_DIR = "/Users/ibrahimabarry/Projects/orange-guinee-reco/docs"
RANDOM_STATE = 42

DROP_COLS = {"num", "nom_pass_regroupe", "label", "flag_date_incoherente"}
CATEGORICAL_COLS = [
    "segment", "region", "device_type", "type_client_dominant",
    "type_ressource_prefere", "type_ressource", "type_client_cible",
]
BOOL_COLS = ["flag_age_moins_15ans", "a_deja_achete_pass", "ambigu"]

# Colonnes entieres SANS valeur manquante -> downcast direct pour limiter la RAM
INT_DOWNCAST = {
    "jours_depuis_dernier_achat": "int16",
    "n_pass_distincts_verif": "int16",
    "popularite_n_clients": "int32",
    "n_lignes_interaction": "int32",
}
# Colonnes entieres AVEC valeurs manquantes (age_estime ~3.7% NA,
# anciennete_jours ~2.6% NA) -> float32 pour preserver NaN (LightGBM le
# gere nativement), pas de downcast en int qui echouerait sur les NA
FLOAT_DOWNCAST_NULLABLE = ["age_estime", "anciennete_jours"]

con = duckdb.connect()

def load_split(split_value):
    print(f"Chargement split '{split_value}'...")
    t0 = time.time()
    df = con.execute(f"""
        SELECT t.*
        FROM read_parquet('{DATA_DIR}/training_ranking.parquet') t
        JOIN read_parquet('{SPLITS_DIR}/client_split_group.parquet') g
            ON t.num = g.num
        WHERE g.split_group = '{split_value}'
        ORDER BY t.num
    """).fetchdf()
    print(f"  {len(df)} lignes / {df['num'].nunique()} clients chargees en {time.time()-t0:.1f}s")
    return df

def downcast(df):
    df["region"] = df["region"].replace({"NULL": "inconnu", "A_METTRE_A_JOUR": "inconnu"})
    df["device_type"] = df["device_type"].replace({"NULL": "inconnu"})
    for c in CATEGORICAL_COLS:
        df[c] = df[c].fillna("inconnu").astype("category")
    for c in BOOL_COLS:
        df[c] = df[c].fillna(False).astype("int8")
    for c, dtype in INT_DOWNCAST.items():
        df[c] = df[c].astype(dtype)
    for c in FLOAT_DOWNCAST_NULLABLE:
        df[c] = df[c].astype("float32")
    float_cols = df.select_dtypes(include=["float64"]).columns
    for c in float_cols:
        df[c] = df[c].astype("float32")
    df["label"] = df["label"].astype("int8")
    return df

train_df = load_split("train")
test_df = load_split("test")

train_df = downcast(train_df)
test_df = downcast(test_df)

for c in CATEGORICAL_COLS:
    cats = pd.api.types.union_categoricals([train_df[c], test_df[c]]).categories
    train_df[c] = train_df[c].cat.set_categories(cats)
    test_df[c] = test_df[c].cat.set_categories(cats)

feature_cols = [c for c in train_df.columns if c not in DROP_COLS]
print(f"\n{len(feature_cols)} features utilisees")

def build_groups(df):
    return df.groupby("num", sort=False).size().values

train_groups = build_groups(train_df)
test_groups = build_groups(test_df)

X_train, y_train = train_df[feature_cols], train_df["label"].values
X_test, y_test = test_df[feature_cols], test_df["label"].values
test_pass_names = test_df["nom_pass_regroupe"].reset_index(drop=True)
n_total_pass = train_df["nom_pass_regroupe"].nunique()

print(f"\nRAM approx train_df: {train_df.memory_usage(deep=True).sum() / 1e9:.2f} GB")
print(f"RAM approx test_df:  {test_df.memory_usage(deep=True).sum() / 1e9:.2f} GB")

# ---------------------------------------------------------------------------
# Entrainement (memes hyperparametres que le bake-off)
# ---------------------------------------------------------------------------
print("\nEntrainement LightGBM lambdarank (pleine echelle)...")
t0 = time.time()
model = lgb.LGBMRanker(
    objective="lambdarank",
    metric="ndcg",
    n_estimators=200,
    learning_rate=0.05,
    num_leaves=63,
    random_state=RANDOM_STATE,
    verbosity=-1,
)
model.fit(X_train, y_train, group=train_groups, categorical_feature=CATEGORICAL_COLS)
train_time = time.time() - t0
print(f"Entrainement termine en {train_time:.1f}s ({train_time/60:.1f} min)")

model_path = f"{MODELS_DIR}/model_a_lgbm_ranker.txt"
model.booster_.save_model(model_path)
print(f"Modele sauvegarde -> {model_path}")

# ---------------------------------------------------------------------------
# Evaluation sur le test set complet (9,37M lignes)
# ---------------------------------------------------------------------------
print("\nEvaluation sur le test set complet...")
t0 = time.time()
scores = model.predict(X_test)
infer_time = time.time() - t0
print(f"Inference: {infer_time:.1f}s")

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

metrics = ranking_metrics(scores, y_test, test_groups)
metrics["coverage@5"] = coverage_at_k(scores, test_pass_names, test_groups, 5, n_total_pass)
metrics["train_time_s"] = train_time
metrics["infer_time_s"] = infer_time
metrics["n_train_rows"] = len(train_df)
metrics["n_test_rows"] = len(test_df)

print("\n" + "=" * 80)
print("RESULTATS MODELE A (LightGBM ranker, pleine echelle)")
for k, v in metrics.items():
    print(f"  {k}: {v}")

pd.DataFrame([metrics]).to_csv(f"{DOCS_DIR}/model_a_fullscale_results.csv", index=False)
print(f"\nSauvegarde -> {DOCS_DIR}/model_a_fullscale_results.csv")

# Feature importance
importance = pd.DataFrame({
    "feature": feature_cols,
    "importance": model.booster_.feature_importance(importance_type="gain"),
}).sort_values("importance", ascending=False)
importance.to_csv(f"{DOCS_DIR}/model_a_feature_importance.csv", index=False)
print(f"Sauvegarde -> {DOCS_DIR}/model_a_feature_importance.csv")
print("\nTop 15 features (gain) :")
print(importance.head(15).to_string(index=False))
