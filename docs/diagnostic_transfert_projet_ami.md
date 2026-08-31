# Diagnostic avant transfert — projet de l'ami (Windows)

Commande à faire coller par l'ami dans PowerShell, **depuis le dossier de
son projet**, avant tout transfert de fichiers. Objectif : savoir
exactement quoi récupérer (nom de l'image Docker, si `data/`/`models/`
sont inclus dans l'image ou montés en volume à côté, contenu de
`frontend/`) avant d'organiser le transfert vers le Mac.

```powershell
Write-Host "=== Images Docker disponibles ===" ; docker images
Write-Host "`n=== Conteneurs (actifs + arretes) ===" ; docker ps -a
Write-Host "`n=== Contenu du dossier projet ===" ; Get-ChildItem
Write-Host "`n=== docker-compose.yml (si present) ===" ; Get-Content .\docker-compose.yml -ErrorAction SilentlyContinue
Write-Host "`n=== Taille de data/ et models/ (si presents) ===" ; if (Test-Path .\data) { "data/ : {0:N0} Mo" -f ((Get-ChildItem .\data -Recurse | Measure-Object Length -Sum).Sum/1MB) } else { "data/ absent" } ; if (Test-Path .\models) { "models/ : {0:N0} Mo" -f ((Get-ChildItem .\models -Recurse | Measure-Object Length -Sum).Sum/1MB) } else { "models/ absent" }
Write-Host "`n=== Contenu de frontend/ (si present) ===" ; Get-ChildItem .\frontend -Recurse -ErrorAction SilentlyContinue
```

## Ce que le résultat permet de déterminer

- **Nom exact de l'image** (colonne `REPOSITORY:TAG` de `docker images`)
  → nécessaire pour la commande d'export :
  ```powershell
  docker save -o backend.tar <nom_image>:<tag>
  ```
- **`data/`/`models/` présents à côté du code** → à envoyer séparément en
  plus du `.tar` (l'image ne les contient probablement pas, montés en
  volume comme dans notre `docker-compose.yml` d'origine).
- **`data/`/`models/` absents** → probablement inclus dans l'image
  elle-même, le `.tar` suffit.
- **Contenu de `docker-compose.yml`** → confirme directement si des
  volumes `./data:/app/data` / `./models:/app/models` sont déclarés.

## Une fois le résultat obtenu

Faire coller le résultat complet dans la conversation pour déterminer
précisément quoi transférer (image seule, ou image + data + models +
frontend), avant de lancer le transfert (cloud, USB — pas l'email pour le
`.tar`, généralement trop volumineux).
