"""
Etape 3 (fallback cold-start) : popularite des pass ponderee par segment,
pour les 205 223 clients sans historique d'achat (a_deja_achete_pass=False).

Ni l'ALS (aucune interaction) ni les modeles A/B (features de comportement
pass a "aucun_achat"/NaN) ne s'appliquent a ces clients. segment/region/
device_type sont les SEULS signaux disponibles (segment est base sur
mnt_recharge_6m, calculable independamment de tout achat de pass).

La popularite est calculee a partir des clients ACTIFS (qui ont un
historique) au sein de chaque segment, puis appliquee comme recommandation
par defaut aux clients cold-start du meme segment.

Limite assumee et documentee : contrairement aux modeles A/B/C, ce fallback
ne peut pas etre evalue avec les donnees livrees (les clients cold-start
n'ont par definition aucun achat observe, dans training_ranking ni dans
interactions_client_pass, pour verifier si la recommandation aurait ete
pertinente).
"""
import duckdb
import pandas as pd

import common as c

con = duckdb.connect()

print("Calcul de la popularite des pass par segment (clients actifs)...")
pop_by_segment = con.execute(f"""
    SELECT
        fc.segment,
        i.nom_pass_regroupe,
        COUNT(DISTINCT i.num) AS n_clients_segment,
        SUM(i.nb_achats) AS total_achats_segment
    FROM read_parquet('{c.DATA_DIR}/interactions_client_pass.parquet') i
    JOIN read_parquet('{c.DATA_DIR}/features_client.parquet') fc USING (num)
    WHERE fc.a_deja_achete_pass = true
    GROUP BY fc.segment, i.nom_pass_regroupe
""").fetchdf()

pop_by_segment["rang_segment"] = pop_by_segment.groupby("segment")["n_clients_segment"] \
    .rank(method="first", ascending=False).astype(int)
pop_by_segment = pop_by_segment.sort_values(["segment", "rang_segment"])

# Popularite globale (fallback ultime si un segment est absent/inconnu)
pop_global = con.execute(f"""
    SELECT
        i.nom_pass_regroupe,
        COUNT(DISTINCT i.num) AS n_clients_global,
        SUM(i.nb_achats) AS total_achats_global
    FROM read_parquet('{c.DATA_DIR}/interactions_client_pass.parquet') i
    GROUP BY i.nom_pass_regroupe
""").fetchdf()
pop_global["rang_global"] = pop_global["n_clients_global"].rank(method="first", ascending=False).astype(int)
pop_global = pop_global.sort_values("rang_global")

pop_by_segment.to_csv(f"{c.MODELS_DIR}/coldstart_popularity_by_segment.csv", index=False)
pop_global.to_csv(f"{c.MODELS_DIR}/coldstart_popularity_global.csv", index=False)

print(f"Sauvegarde -> {c.MODELS_DIR}/coldstart_popularity_by_segment.csv")
print(f"Sauvegarde -> {c.MODELS_DIR}/coldstart_popularity_global.csv")

print("\nTop 5 pass par segment :")
for seg in sorted(pop_by_segment["segment"].unique()):
    top5 = pop_by_segment[pop_by_segment["segment"] == seg].head(5)
    print(f"\n{seg}:")
    print(top5[["nom_pass_regroupe", "n_clients_segment", "rang_segment"]].to_string(index=False))

print("\nTop 5 global :")
print(pop_global.head(5)[["nom_pass_regroupe", "n_clients_global"]].to_string(index=False))

# Verification : coverage -- combien de segments ont au moins 5 pass differents recommandables
n_pass_by_segment = pop_by_segment.groupby("segment")["nom_pass_regroupe"].nunique()
print("\nNombre de pass distincts disponibles par segment (verification suffisance) :")
print(n_pass_by_segment.to_string())
