"""
Etape 3 (Modele B) : classifieur binaire LightGBM + calibration isotonique,
pour fournir une vraie probabilite P(achat) utilisable dans le calcul de
valeur attendue du mode hybride ROI (P(achat) x prix_catalogue).

Split train (client_split_group='train') subdivise en :
  - train_fit (90% des clients train)  -> entrainement du classifieur
  - train_calib (10% des clients train) -> calibration isotonique
      (fit sur un sous-ensemble distinct de l'entrainement, sinon la
      calibration serait optimiste / surestimerait sa propre qualite)
Evaluation finale sur le split test complet (jamais vu).
"""
import time
import joblib
import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.model_selection import train_test_split
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import roc_auc_score, brier_score_loss

import common as c

train_df = c.load_split("train")
test_df = c.load_split("test")

train_df = c.downcast(train_df)
test_df = c.downcast(test_df)
train_df, test_df = c.align_categories(train_df, test_df)

feature_cols = c.feature_columns(train_df)
print(f"\n{len(feature_cols)} features utilisees")

# ---------------------------------------------------------------------------
# Sous-split fit/calib par client (stratifie sur type_client_dominant)
# ---------------------------------------------------------------------------
clients = train_df[["num", "type_client_dominant"]].drop_duplicates()
fit_clients, calib_clients = train_test_split(
    clients, test_size=0.10, random_state=c.RANDOM_STATE,
    stratify=clients["type_client_dominant"],
)
fit_ids = set(fit_clients["num"])
is_fit = train_df["num"].isin(fit_ids)

fit_df = train_df[is_fit]
calib_df = train_df[~is_fit]
print(f"train_fit: {len(fit_df)} lignes / {fit_df['num'].nunique()} clients")
print(f"train_calib: {len(calib_df)} lignes / {calib_df['num'].nunique()} clients")

X_fit, y_fit = fit_df[feature_cols], fit_df["label"].values
X_calib, y_calib = calib_df[feature_cols], calib_df["label"].values
X_test, y_test = test_df[feature_cols], test_df["label"].values

# ---------------------------------------------------------------------------
# Entrainement du classifieur binaire (memes hyperparametres de base que
# le Modele A pour rester comparable, objective binaire cette fois)
# ---------------------------------------------------------------------------
print("\nEntrainement LightGBM binaire...")
t0 = time.time()
model = lgb.LGBMClassifier(
    objective="binary",
    n_estimators=200,
    learning_rate=0.05,
    num_leaves=63,
    random_state=c.RANDOM_STATE,
    verbosity=-1,
)
model.fit(X_fit, y_fit, categorical_feature=c.CATEGORICAL_COLS)
train_time = time.time() - t0
print(f"Entrainement termine en {train_time:.1f}s")

model_path = f"{c.MODELS_DIR}/model_b_lgbm_classifier.txt"
model.booster_.save_model(model_path)
print(f"Modele sauvegarde -> {model_path}")

# ---------------------------------------------------------------------------
# Calibration isotonique sur train_calib (jamais vu par le classifieur)
# ---------------------------------------------------------------------------
print("\nCalibration isotonique...")
raw_probs_calib = model.predict_proba(X_calib)[:, 1]
isotonic = IsotonicRegression(out_of_bounds="clip")
isotonic.fit(raw_probs_calib, y_calib)
joblib.dump(isotonic, f"{c.MODELS_DIR}/model_b_isotonic_calibrator.joblib")
print(f"Calibrateur sauvegarde -> {c.MODELS_DIR}/model_b_isotonic_calibrator.joblib")

# ---------------------------------------------------------------------------
# Evaluation sur le test set complet, jamais vu (ni par le classifieur, ni
# par le calibrateur)
# ---------------------------------------------------------------------------
print("\nEvaluation sur le test set complet...")
t0 = time.time()
raw_probs_test = model.predict_proba(X_test)[:, 1]
calibrated_probs_test = isotonic.predict(raw_probs_test)
infer_time = time.time() - t0

auc_raw = roc_auc_score(y_test, raw_probs_test)
auc_calibrated = roc_auc_score(y_test, calibrated_probs_test)  # doit etre ~identique (transfo monotone)
brier_raw = brier_score_loss(y_test, raw_probs_test)
brier_calibrated = brier_score_loss(y_test, calibrated_probs_test)

# Courbe de calibration (deciles de probabilite predite)
def reliability_table(probs, labels, n_bins=10):
    bins = pd.qcut(probs, n_bins, duplicates="drop")
    df = pd.DataFrame({"bin": bins, "prob": probs, "label": labels})
    table = df.groupby("bin", observed=True).agg(
        n=("label", "size"),
        mean_predicted=("prob", "mean"),
        mean_observed=("label", "mean"),
    )
    return table

rel_raw = reliability_table(raw_probs_test, y_test)
rel_calibrated = reliability_table(calibrated_probs_test, y_test)

print("\n" + "=" * 80)
print("RESULTATS MODELE B (classifieur + calibration isotonique)")
print(f"AUC brut: {auc_raw:.4f} | AUC calibre: {auc_calibrated:.4f} (doit etre ~identique, transfo monotone)")
print(f"Brier score brut: {brier_raw:.5f} | Brier score calibre: {brier_calibrated:.5f} (plus bas = mieux calibre)")
print(f"Temps inference (test complet): {infer_time:.1f}s")

print("\nCourbe de calibration AVANT (10 deciles de proba brute) :")
print(rel_raw.round(4).to_string())
print("\nCourbe de calibration APRES (10 deciles de proba calibree) :")
print(rel_calibrated.round(4).to_string())

results = {
    "auc_raw": auc_raw,
    "auc_calibrated": auc_calibrated,
    "brier_raw": brier_raw,
    "brier_calibrated": brier_calibrated,
    "train_time_s": train_time,
    "infer_time_s": infer_time,
    "n_fit_rows": len(fit_df),
    "n_calib_rows": len(calib_df),
    "n_test_rows": len(test_df),
}
pd.DataFrame([results]).to_csv(f"{c.DOCS_DIR}/model_b_results.csv", index=False)
rel_raw.to_csv(f"{c.DOCS_DIR}/model_b_calibration_curve_raw.csv")
rel_calibrated.to_csv(f"{c.DOCS_DIR}/model_b_calibration_curve_calibrated.csv")
print(f"\nSauvegarde -> {c.DOCS_DIR}/model_b_results.csv (+ courbes de calibration)")
