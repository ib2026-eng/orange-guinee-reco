# Systeme de recommandation de pass — Orange Guinee

Systeme de recommandation a 4 modes (next-best-offer, top-N, filtrage
collaboratif, hybride ROI) pour les pass Orange Guinee. Pipeline complet :
evaluation des donnees, split train/test, bake-off d'algorithmes,
entrainement, comparaison a des baselines non-ML, API FastAPI dockerisee.

**Documentation complete des choix methodologiques et resultats chiffres :
[`docs/00_journal_decisions.md`](docs/00_journal_decisions.md)**

## Ce depot NE contient PAS

`data/`, `models/` et `splits/` sont volontairement exclus (`.gitignore`) :
donnees clients et modeles entraines, trop volumineux pour Git (jusqu'a
1,4 Go par fichier) et sensibles (comportement de 2,47M clients, meme
pseudonymise). Distribues separement, hors GitHub.

Pour deployer l'API, il faut recuperer `data/` (3 fichiers parquet
requis : `features_client.parquet`, `features_pass.parquet`,
`interactions_client_pass.parquet`) et `models/` (artefacts entraines)
aupres de la personne qui a lance l'entrainement, puis :

```bash
docker compose up --build -d
curl http://localhost:8000/health
```

Documentation interactive une fois lance : `http://localhost:8000/docs`.

## Frontend

`frontend/` est une petite plateforme statique (vanilla JS, sans etape de
build), identite propre a ce projet : navigation laterale, cartes blanches
sur fond neutre, accent orange. Recherche d'un client (avec des exemples
cliquables, y compris cold-start) et affichage des 4 modes de
recommandation.

Pour la lancer en local a cote de l'API (`docker compose up --build -d`) :
```bash
cd frontend
python3 -m http.server 8081
# puis ouvrir http://localhost:8081
```
Par defaut le frontend appelle l'API sur `http://localhost:8000`
(`frontend/js/config.js` — a adapter une fois l'API deployee ailleurs).

## Structure

```
scripts/    pipeline d'entrainement, etapes 01 a 07 (executes dans l'ordre)
api/        API FastAPI (4 endpoints de recommandation + /health + /demo)
frontend/   plateforme statique (recherche client + 4 vues de recommandation)
docs/       journal de decisions + resultats chiffres (csv)
Dockerfile, docker-compose.yml
```
