#!/bin/sh
set -e

echo "[attendguard-api] Alembic migrate..."
alembic upgrade head

YUNET="/app/app/ml/weights/face_detection_yunet_2023mar.onnx"
SFACE="/app/app/ml/weights/face_recognition_sface_2021dec.onnx"
if [ ! -f "$YUNET" ] || [ ! -f "$SFACE" ]; then
  echo "[attendguard-api] Face weights missing — downloading..."
  python scripts/download_face_models.py
fi

WORKERS="${UVICORN_WORKERS:-2}"
echo "[attendguard-api] Uvicorn workers=${WORKERS}"
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers "${WORKERS}"
