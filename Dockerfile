# Image legere pour servir l'API de recommandation (etape 6).
# Ne contient QUE le code -- data/ et models/ sont montes en volume au
# lancement (docker-compose.yml), pas copies dans l'image : ca evite de
# reconstruire l'image a chaque reentrainement, et de gonfler l'image avec
# des fichiers dont l'API n'a meme pas besoin (training_ranking.parquet,
# 1.4 Go, n'est utilise que pour l'entrainement, jamais par l'API).
FROM python:3.13-slim

# libgomp1 : runtime OpenMP requis par LightGBM et implicit (ALS) a
# l'execution, pas seulement a la compilation.
# Les sources apt de l'image de base pointent en http:// ; sur ce reseau le
# port 80 sortant est bloque (seul https:// passe), d'ou la substitution
# avant apt-get update.
RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY api/requirements.txt ./api/requirements.txt
RUN pip install --no-cache-dir -r api/requirements.txt

COPY api/main.py ./api/main.py
COPY scripts/common.py ./scripts/common.py

ENV RECO_DATA_DIR=/app/data
ENV RECO_MODELS_DIR=/app/models
ENV RECO_SPLITS_DIR=/app/splits
ENV RECO_DOCS_DIR=/app/docs
# OpenBLAS threadpool interne desactive -- recommande par 'implicit' pour
# eviter des problemes de performance severes (avertissement observe en
# local lors de l'entrainement du Modele C).
ENV OPENBLAS_NUM_THREADS=1

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
