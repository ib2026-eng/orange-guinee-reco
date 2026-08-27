"""
Comparaison du Modele A (LightGBM ranker) a deux baselines non-ML, sur
EXACTEMENT le meme test set (9 366 765 lignes, meme split principal),
avec les memes fonctions de metriques (common.ranking_metrics /
coverage_at_k) -- comparaison strictement equitable.

Baselines :
  1. Popularite globale : score = popularite_n_clients (deja une colonne
     de training_ranking, aucune info client utilisee).
  2. Popularite ponderee par segment : score = n_clients_segment (table
     construite en etape 3 pour le fallback cold-start), utilise le
     segment du client mais aucun modele entraine.

Objectif : quantifier le gain reel du Modele A par rapport a ce qu'une
heuristique simple donnerait, pour le rapport de stage.
"""
import numpy as np
import pandas as pd

import common as c

test_df = c.load_split("test")
test_df = c.downcast(test_df)

test_groups = c.build_groups(test_df)
y_test = test_df["label"].values
test_pass_names = test_df["nom_pass_regroupe"].reset_index(drop=True)
n_total_pass = test_df["nom_pass_regroupe"].nunique()

print(f"Test set: {len(test_df)} lignes / {test_df['num'].nunique()} clients / {n_total_pass} pass")

results = []

# ---------------------------------------------------------------------------
# Baseline 1 : popularite globale (colonne deja presente dans training_ranking)
# ---------------------------------------------------------------------------
print("\nBaseline 1 : popularite globale...")
scores_global = test_df["popularite_n_clients"].values
m = c.ranking_metrics(scores_global, y_test, test_groups)
m["coverage@5"] = c.coverage_at_k(scores_global, test_pass_names, test_groups, 5, n_total_pass)
m["model"] = "Baseline popularite globale"
results.append(m)
print({k: round(v, 4) if isinstance(v, float) else v for k, v in m.items()})

# ---------------------------------------------------------------------------
# Baseline 2 : popularite ponderee par segment (table du fallback cold-start)
# ---------------------------------------------------------------------------
print("\nBaseline 2 : popularite ponderee par segment...")
pop_by_segment = pd.read_csv(f"{c.MODELS_DIR}/coldstart_popularity_by_segment.csv")
pop_lookup = pop_by_segment.set_index(["segment", "nom_pass_regroupe"])["n_clients_segment"]

merge_key = pd.MultiIndex.from_arrays([test_df["segment"].astype(str), test_df["nom_pass_regroupe"].astype(str)])
scores_segment = merge_key.map(pop_lookup).fillna(0).values.astype(float)

m = c.ranking_metrics(scores_segment, y_test, test_groups)
m["coverage@5"] = c.coverage_at_k(scores_segment, test_pass_names, test_groups, 5, n_total_pass)
m["model"] = "Baseline popularite par segment"
results.append(m)
print({k: round(v, 4) if isinstance(v, float) else v for k, v in m.items()})

# ---------------------------------------------------------------------------
# Modele A (deja evalue) -- on rappelle ses resultats pour la comparaison
# ---------------------------------------------------------------------------
model_a = pd.read_csv(f"{c.DOCS_DIR}/model_a_fullscale_results.csv").iloc[0].to_dict()
model_a["model"] = "Modele A (LightGBM ranker)"
results.append(model_a)

# ---------------------------------------------------------------------------
# Tableau comparatif
# ---------------------------------------------------------------------------
summary = pd.DataFrame(results).set_index("model")
cols = ["ndcg@1", "ndcg@3", "ndcg@5", "precision@1", "precision@3", "precision@5",
        "recall@1", "recall@3", "recall@5", "coverage@5"]
summary = summary[cols].round(4)

print("\n" + "=" * 100)
print("COMPARAISON MODELE A vs BASELINES (meme test set, memes metriques)")
print(summary.to_string())

gain_vs_global = summary.loc["Modele A (LightGBM ranker)"] - summary.loc["Baseline popularite globale"]
gain_vs_segment = summary.loc["Modele A (LightGBM ranker)"] - summary.loc["Baseline popularite par segment"]
print("\nGain Modele A vs baseline popularite globale (points) :")
print(gain_vs_global.round(4).to_string())
print("\nGain Modele A vs baseline popularite par segment (points) :")
print(gain_vs_segment.round(4).to_string())

summary.to_csv(f"{c.DOCS_DIR}/model_a_vs_baselines.csv")
print(f"\nSauvegarde -> {c.DOCS_DIR}/model_a_vs_baselines.csv")
