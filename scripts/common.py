"""
Fonctions et constantes partagees entre les scripts d'entrainement
(chargement des splits, nettoyage/encodage, metriques de ranking).
"""
import os
import time
import numpy as np
import pandas as pd
import duckdb

_PROJECT_ROOT = "/Users/ibrahimabarry/Projects/orange-guinee-reco"

# Surchargeables par variable d'environnement (utilise dans le conteneur
# Docker de l'API, ou` data/ et models/ sont montes a des chemins differents
# du projet local, ex. /app/data et /app/models).
DATA_DIR = os.environ.get("RECO_DATA_DIR", f"{_PROJECT_ROOT}/data")
SPLITS_DIR = os.environ.get("RECO_SPLITS_DIR", f"{_PROJECT_ROOT}/splits")
MODELS_DIR = os.environ.get("RECO_MODELS_DIR", f"{_PROJECT_ROOT}/models")
DOCS_DIR = os.environ.get("RECO_DOCS_DIR", f"{_PROJECT_ROOT}/docs")
RANDOM_STATE = 42

DROP_COLS = {"num", "nom_pass_regroupe", "label", "flag_date_incoherente"}
CATEGORICAL_COLS = [
    "segment", "region", "device_type", "type_client_dominant",
    "type_ressource_prefere", "type_ressource", "type_client_cible",
]
BOOL_COLS = ["flag_age_moins_15ans", "a_deja_achete_pass", "ambigu"]

INT_DOWNCAST = {
    "jours_depuis_dernier_achat": "int16",
    "n_pass_distincts_verif": "int16",
    "popularite_n_clients": "int32",
    "n_lignes_interaction": "int32",
}
FLOAT_DOWNCAST_NULLABLE = ["age_estime", "anciennete_jours"]


def load_split(split_value):
    con = duckdb.connect()
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
    con.close()
    print(f"  {len(df)} lignes / {df['num'].nunique()} clients chargees en {time.time()-t0:.1f}s")
    return df


def downcast(df):
    df = df.copy()
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


def align_categories(train_df, test_df):
    for c in CATEGORICAL_COLS:
        cats = pd.api.types.union_categoricals([train_df[c], test_df[c]]).categories
        train_df[c] = train_df[c].cat.set_categories(cats)
        test_df[c] = test_df[c].cat.set_categories(cats)
    return train_df, test_df


def feature_columns(df):
    return [c for c in df.columns if c not in DROP_COLS]


def build_groups(df):
    return df.groupby("num", sort=False).size().values


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
