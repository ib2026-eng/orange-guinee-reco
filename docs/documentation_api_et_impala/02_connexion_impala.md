# Connecter le pipeline à une source de données Impala

Ce document décrit comment remplacer les fichiers Parquet statiques
(`data/features_client.parquet`, etc.) par une connexion directe à un
entrepôt de données Impala/Hive — l'architecture typique d'un cluster
Hadoop en environnement télécom. **Non branché à ce jour** : ceci est une
documentation d'architecture, pas un composant actif du pipeline. Aucune
instance Impala réelle n'a été accessible pour l'implémenter et la
tester.

## 1. Pourquoi Impala

Actuellement, `scripts/common.py` lit des fichiers Parquet livrés
manuellement. Si les données sources vivent en réalité dans un entrepôt
Impala (mis à jour en continu par les systèmes Orange), il est possible
d'y requêter directement plutôt que de dépendre d'un export manuel
ponctuel.

## 2. Librairie et pattern de connexion

La librairie standard pour interroger Impala depuis Python est
[`impyla`](https://github.com/cloudera/impyla) :

```bash
pip install impyla thrift_sasl
```

```python
from impala.dbapi import connect
from impala.util import as_pandas

conn = connect(
    host="impala.orange-guinee.internal",
    port=21050,
    auth_mechanism="GSSAPI",  # ou "LDAP", "PLAIN", "NOSASL" selon la config du cluster
)
cursor = conn.cursor()
cursor.execute("""
    SELECT num, segment, region, device_type, mnt_recharge_6m, ...
    FROM warehouse.features_client
    WHERE num = ?
""", (client_id,))
df = as_pandas(cursor)
conn.close()
```

Alternatives possibles : ODBC via `pyodbc` avec le driver Impala Cloudera,
ou SQLAlchemy avec le dialecte `impala`. `impyla` reste le choix le plus
direct pour un usage pandas.

## 3. Point critique : la latence

L'API sert actuellement les recommandations en **10 à 20 ms**, parce que
tous les profils clients sont chargés en mémoire au démarrage. Une requête
Impala prend typiquement de quelques dizaines de millisecondes (requête
ciblée sur une clé, bien partitionnée) à plusieurs secondes (agrégation ou
scan large) — Impala est un moteur analytique, pas une base
transactionnelle optimisée pour le lookup ponctuel à faible latence.

**Deux scénarios distincts :**

- **Lookup ciblé** (`WHERE num = 'X'`, un seul client) : potentiellement
  compatible avec un appel direct à Impala au moment de la requête API, à
  condition que la table soit partitionnée/indexée pour ce type d'accès.
  À valider empiriquement sur le cluster réel avant toute décision.
- **Agrégations lourdes** (recalcul de features sur tout l'historique,
  jointures entre grosses tables) : à éviter en direct dans le chemin de
  requête de l'API — cela romprait la latence de production.

## 4. Approche recommandée : export périodique (snapshot)

Plutôt que d'interroger Impala à chaque requête API, conserver
l'architecture actuelle (données en mémoire) mais automatiser
l'alimentation :

```
Impala (source de vérité, mise à jour continue)
        │
        │  job périodique (ex. nocturne), export vers Parquet
        ▼
data/features_client.parquet, features_pass.parquet, interactions_client_pass.parquet
        │
        ▼
API (charge le snapshot au démarrage, sert en 10-20 ms)
```

**Compromis assumé** : les données servies par l'API ont jusqu'à un cycle
d'export de retard (24h si le job est nocturne) — un achat réalisé dans la
journée n'apparaît dans les recommandations qu'après le prochain export.
Ce délai est réglable (fréquence du job) mais jamais nul avec cette
architecture ; un vrai temps réel demanderait une architecture différente
(requête Impala en direct pour le client concerné, en acceptant une
latence plus élevée pour ce cas précis).

## 5. Prérequis pour un branchement réel

Avant de pouvoir implémenter cette connexion :

- Accès réseau au cluster (VPN / règles pare-feu internes Orange)
- Mécanisme d'authentification du cluster (Kerberos, LDAP, ou aucun en
  interne)
- Noms réels des tables/schémas Impala correspondant aux fichiers actuels
  (`features_client`, `features_pass`, `interactions_client_pass`)
- Décision sur la fréquence de rafraîchissement acceptable (nocturne,
  horaire, autre) selon le besoin métier

## 6. Ce qui changerait dans le code

Seule `scripts/common.py::load_split()` et les chargements équivalents
dans `_load_artifacts()` (`api/main.py`) seraient concernés — remplacer
les appels `pd.read_parquet(...)` / `duckdb.read_parquet(...)` par des
requêtes Impala vers les tables sources, exécutées par le job d'export
périodique plutôt que par l'API elle-même. Le reste du pipeline
(entraînement, API, format des features) reste inchangé, puisqu'il
consomme déjà des DataFrames pandas indépendamment de leur origine.
