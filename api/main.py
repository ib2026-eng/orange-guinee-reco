"""
Etape 6 : API FastAPI exposant les 4 modes d'usage du systeme de
recommandation. Tous les modeles/tables sont charges une seule fois au
demarrage (pas de rechargement par requete).

Endpoints (conformes au prompt d'origine) :
  POST /recommend/next-best-offer/{client_id}
  POST /recommend/top-n/{client_id}?n=5
  POST /recommend/similar-clients/{client_id}?n=5
  POST /recommend/hybrid-roi/{client_id}?n=5

Fallback cold-start transparent : l'appelant n'a pas a savoir si le client
est nouveau ou non, le routage se fait en interne selon
`a_deja_achete_pass`.
"""
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import duckdb
import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import common as c

STATE = {}

CATEGORICAL_COLS = c.CATEGORICAL_COLS
BOOL_COLS = c.BOOL_COLS


def _load_artifacts():
    print("Chargement des artefacts au demarrage de l'API...")

    features_client = pd.read_parquet(f"{c.DATA_DIR}/features_client.parquet")
    features_client = features_client.set_index("num", drop=False)
    STATE["features_client"] = features_client

    features_pass = pd.read_parquet(f"{c.DATA_DIR}/features_pass.parquet")
    STATE["features_pass"] = features_pass
    STATE["n_pass"] = len(features_pass)

    STATE["model_a"] = lgb.Booster(model_file=f"{c.MODELS_DIR}/model_a_lgbm_ranker.txt")
    STATE["model_b"] = lgb.Booster(model_file=f"{c.MODELS_DIR}/model_b_lgbm_classifier.txt")
    STATE["isotonic"] = joblib.load(f"{c.MODELS_DIR}/model_b_isotonic_calibrator.joblib")

    STATE["als_user_factors"] = np.load(f"{c.MODELS_DIR}/model_c_als_user_factors.npy")
    STATE["als_item_factors"] = np.load(f"{c.MODELS_DIR}/model_c_als_item_factors.npy")
    user_cats = pd.read_csv(f"{c.MODELS_DIR}/model_c_user_categories.csv")["num"]
    item_cats = pd.read_csv(f"{c.MODELS_DIR}/model_c_item_categories.csv")["nom_pass_regroupe"]
    STATE["als_user_index"] = {v: i for i, v in enumerate(user_cats)}
    STATE["als_item_index"] = {v: i for i, v in enumerate(item_cats)}
    STATE["als_item_names"] = item_cats.values

    con = duckdb.connect()
    purchased = con.execute(f"""
        SELECT num, list(nom_pass_regroupe) AS pass_achetes
        FROM read_parquet('{c.DATA_DIR}/interactions_client_pass.parquet')
        GROUP BY num
    """).fetchdf()
    STATE["purchased_by_client"] = dict(zip(purchased["num"], purchased["pass_achetes"]))
    con.close()

    STATE["pop_by_segment"] = pd.read_csv(f"{c.MODELS_DIR}/coldstart_popularity_by_segment.csv")
    STATE["pop_global"] = pd.read_csv(f"{c.MODELS_DIR}/coldstart_popularity_global.csv")

    print("Artefacts charges.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _load_artifacts()
    yield
    STATE.clear()


app = FastAPI(title="Orange Guinee - Recommandation de pass", lifespan=lifespan)

# Le frontend (frontend/) est servi depuis une origine differente (fichier
# local, python -m http.server, ou GitHub Pages une fois deploye) --
# CORS necessaire pour qu'il puisse appeler cette API. Origines
# surchargeables via RECO_ALLOWED_ORIGINS (liste separee par des virgules) ;
# "*" par defaut, adapte au developpement local mais a restreindre en
# production (cf. orange-platform/backend qui utilise une liste explicite).
_allowed_origins = os.environ.get("RECO_ALLOWED_ORIGINS", "*")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if _allowed_origins == "*" else _allowed_origins.split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Construction des candidats (client x tous les pass) pour les modeles A/B
# ---------------------------------------------------------------------------
def _build_candidates(client_id: str) -> pd.DataFrame:
    pass_df = STATE["features_pass"].rename(columns={
        "n_achats_international": "n_achats_international_1",
        "n_achats_pour_tiers": "n_achats_pour_tiers_1",
    })
    # .loc[[client_id]] (liste) renvoie un DataFrame et preserve le dtype
    # propre de chaque colonne -- .loc[client_id] (scalaire) renverrait une
    # Series unifiee en dtype "object" (melange str/bool/float), ce que
    # LightGBM refuse en predict().
    client_df = STATE["features_client"].loc[[client_id]].drop(columns=["num"]).reset_index(drop=True)
    client_repeated = pd.concat([client_df] * len(pass_df), ignore_index=True)
    candidates = pd.concat([client_repeated, pass_df.reset_index(drop=True)], axis=1)
    return candidates


def _prepare_for_model(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    # flag_date_incoherente : incoherence logique pure, exclue des features
    # a l'entrainement (cf. LEAKAGE_COLUMNS_a_exclure.txt / journal etape 1),
    # jamais utilisee par les modeles A/B.
    df = df.drop(columns=["flag_date_incoherente"])
    df["region"] = df["region"].replace({"NULL": "inconnu", "A_METTRE_A_JOUR": "inconnu"})
    df["device_type"] = df["device_type"].replace({"NULL": "inconnu"})
    for col in CATEGORICAL_COLS:
        df[col] = df[col].fillna("inconnu").astype("category")
    for col in BOOL_COLS:
        df[col] = df[col].fillna(False).astype("int8")
    return df


def _score_ranker(client_id: str) -> pd.DataFrame:
    candidates = _build_candidates(client_id)
    model_input = _prepare_for_model(candidates)
    model_input = model_input.drop(columns=["nom_pass_regroupe"])
    scores = STATE["model_a"].predict(model_input)
    return pd.DataFrame({
        "nom_pass_regroupe": candidates["nom_pass_regroupe"].values,
        "score_ranking": scores,
    })


def _score_classifier(client_id: str) -> pd.DataFrame:
    candidates = _build_candidates(client_id)
    model_input = _prepare_for_model(candidates)
    model_input = model_input.drop(columns=["nom_pass_regroupe"])
    raw_probs = STATE["model_b"].predict(model_input)
    calibrated = STATE["isotonic"].predict(raw_probs)
    return pd.DataFrame({
        "nom_pass_regroupe": candidates["nom_pass_regroupe"].values,
        "proba_achat": calibrated,
    })


# ---------------------------------------------------------------------------
# Fallback cold-start
# ---------------------------------------------------------------------------
def _coldstart_recommendations(client_row: pd.Series, n: int) -> list:
    segment = client_row["segment"]
    pop = STATE["pop_by_segment"]
    subset = pop[pop["segment"] == segment].sort_values("rang_segment")
    if len(subset) < n:
        subset = STATE["pop_global"].sort_values("rang_global")
    top = subset.head(n)
    return [
        {"nom_pass_regroupe": row["nom_pass_regroupe"], "score": None, "source": "popularite_segment"}
        for _, row in top.iterrows()
    ]


def _get_client_or_404(client_id: str) -> pd.Series:
    fc = STATE["features_client"]
    if client_id not in fc.index:
        raise HTTPException(status_code=404, detail=f"Client inconnu: {client_id}")
    return fc.loc[client_id]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.post("/recommend/next-best-offer/{client_id}")
def next_best_offer(client_id: str):
    client_row = _get_client_or_404(client_id)
    if not client_row["a_deja_achete_pass"]:
        reco = _coldstart_recommendations(client_row, n=1)
        return {"client_id": client_id, "cold_start": True, "recommendations": reco}
    scored = _score_ranker(client_id).sort_values("score_ranking", ascending=False)
    top = scored.iloc[0]
    return {
        "client_id": client_id,
        "cold_start": False,
        "recommendations": [{"nom_pass_regroupe": top["nom_pass_regroupe"], "score": float(top["score_ranking"])}],
    }


@app.post("/recommend/top-n/{client_id}")
def top_n(client_id: str, n: int = 5):
    client_row = _get_client_or_404(client_id)
    if not client_row["a_deja_achete_pass"]:
        reco = _coldstart_recommendations(client_row, n=n)
        return {"client_id": client_id, "cold_start": True, "recommendations": reco}
    scored = _score_ranker(client_id).sort_values("score_ranking", ascending=False).head(n)
    reco = [
        {"nom_pass_regroupe": row["nom_pass_regroupe"], "score": float(row["score_ranking"])}
        for _, row in scored.iterrows()
    ]
    return {"client_id": client_id, "cold_start": False, "recommendations": reco}


@app.post("/recommend/similar-clients/{client_id}")
def similar_clients(client_id: str, n: int = 5):
    client_row = _get_client_or_404(client_id)
    if not client_row["a_deja_achete_pass"] or client_id not in STATE["als_user_index"]:
        reco = _coldstart_recommendations(client_row, n=n)
        return {"client_id": client_id, "cold_start": True, "recommendations": reco, "note": "ALS indisponible, repli popularite"}

    user_idx = STATE["als_user_index"][client_id]
    user_vec = STATE["als_user_factors"][user_idx]
    scores = STATE["als_item_factors"] @ user_vec

    already_purchased = set(STATE["purchased_by_client"].get(client_id, []))
    item_names = STATE["als_item_names"]
    order = np.argsort(-scores)
    reco = []
    for idx in order:
        name = item_names[idx]
        if name in already_purchased:
            continue
        reco.append({"nom_pass_regroupe": name, "score": float(scores[idx])})
        if len(reco) >= n:
            break
    return {"client_id": client_id, "cold_start": False, "recommendations": reco}


@app.post("/recommend/hybrid-roi/{client_id}")
def hybrid_roi(client_id: str, n: int = 5):
    client_row = _get_client_or_404(client_id)
    if not client_row["a_deja_achete_pass"]:
        reco = _coldstart_recommendations(client_row, n=n)
        return {"client_id": client_id, "cold_start": True, "recommendations": reco}

    probs = _score_classifier(client_id)
    prices = STATE["features_pass"][["nom_pass_regroupe", "montant_moyen_par_achat"]]
    merged = probs.merge(prices, on="nom_pass_regroupe", how="left")
    merged["valeur_attendue"] = merged["proba_achat"] * merged["montant_moyen_par_achat"]
    merged = merged.sort_values("valeur_attendue", ascending=False).head(n)

    reco = [
        {
            "nom_pass_regroupe": row["nom_pass_regroupe"],
            "proba_achat": float(row["proba_achat"]),
            "prix_catalogue": float(row["montant_moyen_par_achat"]),
            "valeur_attendue": float(row["valeur_attendue"]),
        }
        for _, row in merged.iterrows()
    ]
    return {"client_id": client_id, "cold_start": False, "recommendations": reco}


@app.get("/health")
def health():
    return {"status": "ok", "n_clients": len(STATE["features_client"]), "n_pass": STATE["n_pass"]}


@app.get("/demo/sample-clients")
def sample_clients():
    """Quelques identifiants clients reels (melange actif/cold-start) pour
    permettre de tester l'API/le frontend sans devoir en connaitre a l'avance."""
    fc = STATE["features_client"]
    actifs = fc[fc["a_deja_achete_pass"]].sample(n=3, random_state=None)["num"]
    cold = fc[~fc["a_deja_achete_pass"]].sample(n=2, random_state=None)["num"]
    return {
        "clients": (
            [{"client_id": cid, "cold_start": False} for cid in actifs]
            + [{"client_id": cid, "cold_start": True} for cid in cold]
        )
    }
