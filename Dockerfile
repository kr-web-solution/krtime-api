# KRTime API — build context: api/
# Dokploy: set Dockerfile path to api/Dockerfile, context = api (or repo root + this path)

FROM python:3.12-slim-bookworm AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UVICORN_WORKERS=2

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        libglib2.0-0 \
        libgomp1 \
        libgl1 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin appuser

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Bake YuNet + SFace into the image (required for face enroll / match).
RUN mkdir -p /app/data/review_photos /app/app/ml/weights \
    && python scripts/download_face_models.py \
    && chmod +x /app/scripts/entrypoint.sh \
    && chown -R appuser:appuser /app

USER appuser

# Keep 8000 fixed. Dokploy Domains → Port must be 8000 (not 3000).
EXPOSE 8000

HEALTHCHECK --interval=20s --timeout=5s --start-period=45s --retries=5 \
  CMD curl -fsS http://127.0.0.1:8000/health || exit 1

CMD ["/app/scripts/entrypoint.sh"]
