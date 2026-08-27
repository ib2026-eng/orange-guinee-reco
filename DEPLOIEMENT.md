# Deploiement de l'API + plateforme de recommandation Orange Guinee

## Prerequis sur le serveur
- Docker + Docker Compose installes (`docker --version` et `docker compose version`)
- Au moins ~2 Go d'espace disque libre et ~2 Go de RAM disponibles
- Python 3 pour servir le frontend statique (ou n'importe quel serveur
  static, nginx compris)

## 1. API

```bash
cd orange-guinee-reco
docker compose up --build -d
curl http://localhost:8000/health
# {"status":"ok","n_clients":2471994,"n_pass":65}
```

Documentation interactive : `http://<ip-serveur>:8000/docs`

## 2. Frontend (plateforme)

Statique, sans etape de build. Par defaut il appelle l'API sur
`http://localhost:8000` -- si l'API tourne sur un autre host/port, editer
`frontend/js/config.js` avant de servir :

```bash
cd frontend
python3 -m http.server 8081
# puis ouvrir http://<ip-serveur>:8081
```

Ou avec n'importe quel serveur statique/nginx pointant sur le dossier
`frontend/`.

## Endpoints disponibles

Tous en POST, `client_id` est l'identifiant pseudonymise du client (colonne
`num` des donnees) :

```
POST /recommend/next-best-offer/{client_id}
POST /recommend/top-n/{client_id}?n=5
POST /recommend/similar-clients/{client_id}?n=5
POST /recommend/hybrid-roi/{client_id}?n=5
GET  /demo/sample-clients          (identifiants d'exemple pour tester)
```

Exemple :
```bash
curl -X POST "http://localhost:8000/recommend/top-n/<client_id>?n=5"
```

Le fallback cold-start (client sans historique d'achat) est automatique --
pas besoin de le gerer cote appelant.

## CORS

Si le frontend est servi depuis une origine differente de l'API (autre
domaine/port), l'API doit l'autoriser. Par defaut `RECO_ALLOWED_ORIGINS=*`
(tout autorise, pratique en local/demo). Pour restreindre en production,
definir la variable d'environnement avant `docker compose up`, par exemple
dans `docker-compose.yml` :
```yaml
environment:
  - RECO_ALLOWED_ORIGINS=https://mon-frontend.exemple.com
```

## Arreter / relancer

```bash
docker compose down        # arreter l'API
docker compose up -d       # relancer (image deja construite)
docker compose logs -f     # voir les logs en direct
```

## Mettre a jour les modeles

Si de nouveaux modeles sont entraines, remplacer les fichiers dans
`models/` (et `data/` si les features changent), puis :
```bash
docker compose restart
```
Pas besoin de rebuilder l'image -- `data/` et `models/` sont montes en
volume, pas copies dedans.

## En cas de probleme au build (apt-get echoue)

Si `docker compose up --build` echoue sur `apt-get update` avec une erreur
de connexion, c'est probablement un blocage du port 80 sortant sur le
reseau du serveur (rencontre lors du developpement). Le `Dockerfile`
force deja les sources apt en HTTPS pour contourner ce cas -- si le
probleme persiste malgre tout, verifier la configuration reseau/firewall
du serveur.
