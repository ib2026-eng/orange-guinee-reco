"""
Etape 2 : construction des splits train/test.

Deux schemas de split independants, tous les deux groupes par client (num)
pour eviter la fuite de groupe dans l'entrainement group-wise du ranking :

1. Split principal (aleatoire, stratifie) :
   GroupShuffleSplit equivalent au niveau client, stratifie sur
   type_client_dominant pour preserver la representation des segments
   minoritaires B2B/M2M/FTTH/box_fixe. C'est le split utilise pour
   entrainer et evaluer tous les modeles des 4 modes d'usage.

2. Split temporel (controle de robustesse) :
   Pour chaque client, on calcule la date de sa derniere interaction
   positive (jointure avec interactions_client_pass.dernier_achat).
   Un cutoff est choisi pour isoler ~20% des clients les plus recents
   en test temporel, le reste en train temporel. Toutes les lignes
   (positives ET negatives) d'un client vont dans le meme cote, donc
   pas de fuite non plus. Sert a verifier que les modeles tiennent
   dans le temps (pas seulement sur un split aleatoire).

Les fichiers produits sont de simples tables de correspondance
(num -> split), pas des copies dupliquees de training_ranking.parquet :
le filtrage se fait a la volee via DuckDB au moment de l'entrainement.
"""
import duckdb
import pandas as pd
from sklearn.model_selection import train_test_split

DATA_DIR = "/Users/ibrahimabarry/Projects/orange-guinee-reco/data"
SPLITS_DIR = "/Users/ibrahimabarry/Projects/orange-guinee-reco/splits"

TEST_SIZE = 0.20
RANDOM_STATE = 42

con = duckdb.connect()

# ---------------------------------------------------------------------------
# 1. Split principal : groupe par client, stratifie sur type_client_dominant
# ---------------------------------------------------------------------------
print("=" * 80)
print("SPLIT PRINCIPAL (aleatoire groupe par client, stratifie)")

clients = con.execute(f"""
    SELECT num, type_client_dominant, segment
    FROM read_parquet('{DATA_DIR}/features_client.parquet')
    WHERE a_deja_achete_pass = true
""").fetchdf()

print(f"Clients actifs (a_deja_achete_pass=True) : {len(clients)}")
print(clients["type_client_dominant"].value_counts())

train_clients, test_clients = train_test_split(
    clients,
    test_size=TEST_SIZE,
    random_state=RANDOM_STATE,
    stratify=clients["type_client_dominant"],
)

train_clients = train_clients.assign(split_group="train")
test_clients = test_clients.assign(split_group="test")
group_split = pd.concat([train_clients, test_clients], ignore_index=True)[
    ["num", "type_client_dominant", "segment", "split_group"]
]

group_split_path = f"{SPLITS_DIR}/client_split_group.parquet"
group_split.to_parquet(group_split_path, index=False)

print(f"\nTrain: {len(train_clients)} clients ({len(train_clients)/len(clients):.1%})")
print(f"Test:  {len(test_clients)} clients ({len(test_clients)/len(clients):.1%})")
print("\nVerification stratification (proportions par type_client_dominant) :")
check = pd.crosstab(group_split["type_client_dominant"], group_split["split_group"], normalize="index")
print(check)
print(f"\nSauvegarde -> {group_split_path}")

# ---------------------------------------------------------------------------
# 2. Split temporel : dernier achat par client, cutoff ~20% les plus recents
# ---------------------------------------------------------------------------
print("\n" + "=" * 80)
print("SPLIT TEMPOREL (controle de robustesse)")

last_purchase = con.execute(f"""
    SELECT num, MAX(dernier_achat) AS derniere_interaction
    FROM read_parquet('{DATA_DIR}/interactions_client_pass.parquet')
    GROUP BY num
""").fetchdf()

print(f"Clients avec au moins une interaction : {len(last_purchase)}")
print("Distribution de derniere_interaction (quantiles) :")
print(last_purchase["derniere_interaction"].quantile([0, 0.5, 0.8, 0.9, 1.0]))

cutoff = last_purchase["derniere_interaction"].quantile(1 - TEST_SIZE)
print(f"\nCutoff choisi (quantile {1-TEST_SIZE:.0%}) : {cutoff}")

last_purchase["split_temporal"] = last_purchase["derniere_interaction"].apply(
    lambda d: "test" if d >= cutoff else "train"
)

temporal_split_path = f"{SPLITS_DIR}/client_split_temporal.parquet"
last_purchase.rename(columns={"derniere_interaction": "derniere_interaction_positive"}).to_parquet(
    temporal_split_path, index=False
)

print(last_purchase["split_temporal"].value_counts())
print(f"\nSauvegarde -> {temporal_split_path}")

# ---------------------------------------------------------------------------
# 3. Verification : tailles resultantes une fois applique a training_ranking
# ---------------------------------------------------------------------------
print("\n" + "=" * 80)
print("VERIFICATION sur training_ranking.parquet (sans materialiser de copie)")

res = con.execute(f"""
    SELECT
        g.split_group,
        COUNT(*) AS n_lignes,
        SUM(CASE WHEN t.label = 1 THEN 1 ELSE 0 END) AS n_positifs,
        SUM(CASE WHEN t.label = 0 THEN 1 ELSE 0 END) AS n_negatifs
    FROM read_parquet('{DATA_DIR}/training_ranking.parquet') t
    JOIN read_parquet('{SPLITS_DIR}/client_split_group.parquet') g USING (num)
    GROUP BY g.split_group
""").fetchdf()
print("\nSplit principal applique a training_ranking :")
print(res)

res_temp = con.execute(f"""
    SELECT
        s.split_temporal,
        COUNT(*) AS n_lignes,
        SUM(CASE WHEN t.label = 1 THEN 1 ELSE 0 END) AS n_positifs,
        SUM(CASE WHEN t.label = 0 THEN 1 ELSE 0 END) AS n_negatifs
    FROM read_parquet('{DATA_DIR}/training_ranking.parquet') t
    JOIN read_parquet('{SPLITS_DIR}/client_split_temporal.parquet') s USING (num)
    GROUP BY s.split_temporal
""").fetchdf()
print("\nSplit temporel applique a training_ranking :")
print(res_temp)

con.close()
print("\nTermine.")
