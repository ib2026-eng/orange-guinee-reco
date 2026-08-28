# Contrat API — Système de recommandation de pass Orange Guinée

Documentation de référence pour tout consommateur de l'API (frontend,
autre service, intégration tierce). Cette API est **sans état** (pas de
base de données, pas d'authentification pour l'instant) et **synchrone,
lecture seule** : aucun réentraînement, aucune écriture déclenchée par une
requête.

- Documentation interactive (Swagger) : `GET /docs`
- Schéma OpenAPI brut : `GET /openapi.json`
- Base URL locale : `http://localhost:8000`

## Authentification

Aucune actuellement. À ajouter avant toute exposition sur un réseau non
maîtrisé (voir section "Sécurité" en bas de page).

## Conventions communes

- Tous les endpoints de recommandation sont en **POST** (conforme au
  contrat d'origine, même si ce sont des lectures — pas d'effet de bord).
- `client_id` est l'identifiant pseudonymisé du client (colonne `num` des
  données sources), passé dans le chemin de l'URL.
- `n` (paramètre de requête, optionnel) : nombre de recommandations
  souhaitées. Défaut = 5.
- Le **fallback cold-start est transparent** : l'appelant n'a jamais besoin
  de savoir si un client a un historique d'achat ou non. La réponse
  contient toujours `"cold_start": true|false` pour information.
- Toutes les réponses sont en JSON, encodage UTF-8.

## Codes d'erreur

| Code | Cas |
|---|---|
| 200 | Succès |
| 404 | `client_id` inconnu de la base |
| 422 | Paramètre invalide (ex. `n` non numérique) — géré nativement par FastAPI |
| 500 | Erreur serveur (à signaler) |

---

## `POST /recommend/next-best-offer/{client_id}`

La meilleure recommandation unique pour ce client (Modèle A, score de
ranking).

**Requête**
```
POST /recommend/next-best-offer/NjI1MTIyMDU2
```

**Réponse 200 (client actif)**
```json
{
  "client_id": "NjI1MTIyMDU2",
  "cold_start": false,
  "recommendations": [
    {"nom_pass_regroupe": "Pass_230Mo", "score": 4.8836525071706065}
  ]
}
```

**Réponse 200 (client cold-start)** — `score` est `null`, la
recommandation vient du repli popularité par segment :
```json
{
  "client_id": "NjIzOTU2MTU1",
  "cold_start": true,
  "recommendations": [
    {"nom_pass_regroupe": "Pass_230Mo", "score": null, "source": "popularite_segment"}
  ]
}
```

---

## `POST /recommend/top-n/{client_id}?n=5`

Les N meilleures recommandations classées par pertinence (Modèle A).

**Paramètres** : `n` (query, int, défaut 5)

**Réponse 200**
```json
{
  "client_id": "NjI1MTIyMDU2",
  "cold_start": false,
  "recommendations": [
    {"nom_pass_regroupe": "Pass_230Mo", "score": 4.8836525071706065},
    {"nom_pass_regroupe": "Pass_50Mo", "score": 3.0455253172062653}
  ]
}
```

---

## `POST /recommend/similar-clients/{client_id}?n=5`

Filtrage collaboratif (Modèle C, ALS) — "les clients similaires ont aussi
acheté". Exclut les pass déjà achetés par ce client.

**Paramètres** : `n` (query, int, défaut 5)

**Réponse 200**
```json
{
  "client_id": "NjI1MTIyMDU2",
  "cold_start": false,
  "recommendations": [
    {"nom_pass_regroupe": "Pass_1_5Go", "score": 0.5824152231216431}
  ]
}
```

**Si le client actif n'a pas de vecteur ALS** (cas rare) — repli
popularité avec un champ `note` explicatif :
```json
{
  "client_id": "...",
  "cold_start": true,
  "recommendations": [...],
  "note": "ALS indisponible, repli popularite"
}
```

---

## `POST /recommend/hybrid-roi/{client_id}?n=5`

Classement par valeur attendue = `P(achat) × prix catalogue` (Modèle B
calibré). Optimise le revenu attendu, pas juste la probabilité brute.

**Paramètres** : `n` (query, int, défaut 5)

**Réponse 200 (client actif)**
```json
{
  "client_id": "NjI1MTIyMDU2",
  "cold_start": false,
  "recommendations": [
    {
      "nom_pass_regroupe": "Pass_600Mo",
      "proba_achat": 0.8513816280806572,
      "prix_catalogue": 6944.832829756551,
      "valeur_attendue": 5912.703081346131
    }
  ]
}
```

**Réponse 200 (cold-start)** — pas de probabilité/prix, uniquement le
repli popularité :
```json
{
  "client_id": "...",
  "cold_start": true,
  "recommendations": [
    {"nom_pass_regroupe": "Pass_230Mo", "score": null, "source": "popularite_segment"}
  ]
}
```

---

## `GET /health`

Vérification de l'état de l'API (utile pour un check de disponibilité /
monitoring).

```json
{"status": "ok", "n_clients": 2471994, "n_pass": 65}
```

## `GET /demo/sample-clients`

Renvoie 3 clients actifs + 2 clients cold-start au hasard, pour tester
sans connaître d'identifiant à l'avance (utilisé par le frontend).

```json
{
  "clients": [
    {"client_id": "NjI5NDY4NzMy", "cold_start": false},
    {"client_id": "NjI0OTk3MjU5", "cold_start": true}
  ]
}
```

---

## Exemples d'appel

**curl**
```bash
curl -X POST "http://localhost:8000/recommend/top-n/NjI1MTIyMDU2?n=5"
```

**Python (requests)**
```python
import requests
r = requests.post("http://localhost:8000/recommend/hybrid-roi/NjI1MTIyMDU2", params={"n": 5})
r.raise_for_status()
data = r.json()
```

**JavaScript (fetch)**
```javascript
const res = await fetch(`http://localhost:8000/recommend/top-n/${clientId}?n=5`, { method: "POST" });
const data = await res.json();
```

---

## Sécurité (avant une exposition en dehors d'un réseau interne maîtrisé)

- **Authentification** : aucune actuellement — à ajouter (clé API en
  header, ou JWT) avant toute exposition publique.
- **CORS** : `RECO_ALLOWED_ORIGINS` est à `*` par défaut (pratique en
  développement) — à restreindre aux domaines autorisés en production
  (voir `DEPLOIEMENT.md`).
- **Rate limiting** : aucun actuellement — à considérer si l'API est
  exposée au-delà d'un usage interne.
- **PII** : `client_id` est un identifiant pseudonymisé, mais reste une
  donnée client — à traiter avec les mêmes précautions que toute donnée
  client (logs, transport HTTPS en production).
