"""
Etape 3 (Modele C) : ALS implicite (filtrage collaboratif, mode 3
"clients similaires") sur interactions_client_pass.

Methodologie validee avec l'utilisateur : entrainement sur 100% des
2 266 771 clients actifs (necessaire pour que chaque client ait un vecteur
latent, condition pour servir le mode 3 en production), evaluation par
leave-one-out PAR CLIENT (on masque l'achat le plus recent de chaque client
ayant >= 2 pass distincts achetes, on verifie si le modele le retrouve dans
le top-K). C'est une methodologie differente du split groupe utilise pour
les modeles A/B -- normal, la nature du probleme (recuperer un vecteur
latent existant vs generaliser a un nouveau groupe) est differente, et
c'est documente comme tel dans le journal de decisions.
"""
import time
import numpy as np
import pandas as pd
import scipy.sparse as sp
import duckdb
from implicit.als import AlternatingLeastSquares

import common as c

RANDOM_STATE = 42
ALPHA = 40.0          # ponderation confiance = 1 + ALPHA * nb_achats (Hu et al.)
N_FACTORS = 64
REGULARIZATION = 0.01
ITERATIONS = 15
K_LIST = (1, 3, 5, 10)

con = duckdb.connect()
print("Chargement interactions_client_pass...")
inter = con.execute(f"""
    SELECT num, nom_pass_regroupe, nb_achats, dernier_achat
    FROM read_parquet('{c.DATA_DIR}/interactions_client_pass.parquet')
""").fetchdf()
print(f"{len(inter)} interactions / {inter['num'].nunique()} clients / {inter['nom_pass_regroupe'].nunique()} pass")

# ---------------------------------------------------------------------------
# Index utilisateurs / items
# ---------------------------------------------------------------------------
user_ids = inter["num"].astype("category")
item_ids = inter["nom_pass_regroupe"].astype("category")
inter["user_idx"] = user_ids.cat.codes
inter["item_idx"] = item_ids.cat.codes
n_users = len(user_ids.cat.categories)
n_items = len(item_ids.cat.categories)
user_categories = user_ids.cat.categories
item_categories = item_ids.cat.categories
print(f"n_users={n_users}, n_items={n_items}")

# ---------------------------------------------------------------------------
# Leave-one-out : masquer l'achat le plus recent pour les clients avec
# >= 2 pass distincts achetes
# ---------------------------------------------------------------------------
inter = inter.sort_values(["user_idx", "dernier_achat"])
inter["n_items_client"] = inter.groupby("user_idx")["item_idx"].transform("count")
inter["rank_recent"] = inter.groupby("user_idx")["dernier_achat"].rank(method="first", ascending=False)

is_holdout = (inter["n_items_client"] >= 2) & (inter["rank_recent"] == 1)
train_inter = inter[~is_holdout]
holdout_inter = inter[is_holdout]
print(f"Train: {len(train_inter)} interactions | Holdout eval: {len(holdout_inter)} clients")

# ---------------------------------------------------------------------------
# Matrice creuse de confiance (users x items)
# ---------------------------------------------------------------------------
confidence = 1.0 + ALPHA * train_inter["nb_achats"].values
train_matrix = sp.csr_matrix(
    (confidence, (train_inter["user_idx"], train_inter["item_idx"])),
    shape=(n_users, n_items),
)

# ---------------------------------------------------------------------------
# Entrainement ALS
# ---------------------------------------------------------------------------
print("\nEntrainement ALS...")
t0 = time.time()
model = AlternatingLeastSquares(
    factors=N_FACTORS,
    regularization=REGULARIZATION,
    iterations=ITERATIONS,
    random_state=RANDOM_STATE,
)
model.fit(train_matrix, show_progress=True)
train_time = time.time() - t0
print(f"Entrainement termine en {train_time:.1f}s")

np.save(f"{c.MODELS_DIR}/model_c_als_user_factors.npy", model.user_factors)
np.save(f"{c.MODELS_DIR}/model_c_als_item_factors.npy", model.item_factors)
pd.Series(user_categories).to_csv(f"{c.MODELS_DIR}/model_c_user_categories.csv", index=False, header=["num"])
pd.Series(item_categories).to_csv(f"{c.MODELS_DIR}/model_c_item_categories.csv", index=False, header=["nom_pass_regroupe"])
print("Modele et mappings sauvegardes dans models/")

# ---------------------------------------------------------------------------
# Evaluation leave-one-out
# ---------------------------------------------------------------------------
print("\nEvaluation leave-one-out...")
eval_users = holdout_inter["user_idx"].values
eval_true_items = holdout_inter["item_idx"].values

t0 = time.time()
recommended_ids, recommended_scores = model.recommend(
    eval_users, train_matrix[eval_users], N=max(K_LIST), filter_already_liked_items=True
)
infer_time = time.time() - t0
print(f"Inference (recommandations pour {len(eval_users)} clients): {infer_time:.1f}s")

hits = {k: [] for k in K_LIST}
ndcgs = {k: [] for k in K_LIST}
for i, true_item in enumerate(eval_true_items):
    row = recommended_ids[i]
    pos = np.where(row == true_item)[0]
    rank = pos[0] + 1 if len(pos) > 0 else None
    for k in K_LIST:
        hit = 1 if (rank is not None and rank <= k) else 0
        hits[k].append(hit)
        ndcgs[k].append(1.0 / np.log2(rank + 1) if hit else 0.0)

metrics = {}
for k in K_LIST:
    metrics[f"hit_rate@{k}"] = np.mean(hits[k])
    metrics[f"ndcg@{k}"] = np.mean(ndcgs[k])

# Coverage@10 : diversite du catalogue recommande sur l'ensemble des clients evalues
top10_flat = recommended_ids[:, :10].flatten()
metrics["coverage@10"] = len(np.unique(top10_flat)) / n_items
metrics["train_time_s"] = train_time
metrics["infer_time_s"] = infer_time
metrics["n_eval_users"] = len(eval_users)
metrics["n_train_interactions"] = len(train_inter)

print("\n" + "=" * 80)
print("RESULTATS MODELE C (ALS implicite, leave-one-out)")
for k, v in metrics.items():
    print(f"  {k}: {v}")

pd.DataFrame([metrics]).to_csv(f"{c.DOCS_DIR}/model_c_results.csv", index=False)
print(f"\nSauvegarde -> {c.DOCS_DIR}/model_c_results.csv")
