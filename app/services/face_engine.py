"""YuNet detect + SFace embed + anti-spoof signals (CPU).

Weights are downloaded separately (see scripts/download_face_models.py).
YuNet: MIT (OpenCV Zoo). SFace: Apache-2.0 (OpenCV Zoo).
MiniFASNet weights are NOT bundled — optional file + basic quality fallback.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app.core.config import Settings

logger = logging.getLogger("attendguard.face")

MODEL_VERSION = "yunet2023mar+sface2021dec"
WEIGHTS_DIR = Path(__file__).resolve().parents[1] / "ml" / "weights"
YUNET_NAME = "face_detection_yunet_2023mar.onnx"
SFACE_NAME = "face_recognition_sface_2021dec.onnx"


@dataclass
class DetectedFace:
    embedding: list[float]
    box: tuple[int, int, int, int]
    spoof_score: float  # higher = more likely live / real
    quality: float


class FaceEngineUnavailable(RuntimeError):
    pass


class FaceEngine:
    def __init__(self, weights_dir: Path | None = None) -> None:
        self.weights_dir = weights_dir or WEIGHTS_DIR
        self._detector = None
        self._recognizer = None
        self._lock = threading.Lock()
        self._loaded = False

    @property
    def available(self) -> bool:
        yunet = self.weights_dir / YUNET_NAME
        sface = self.weights_dir / SFACE_NAME
        return yunet.is_file() and sface.is_file()

    def ensure_loaded(self) -> None:
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
            if not self.available:
                raise FaceEngineUnavailable(
                    f"Face model weights missing in {self.weights_dir}. "
                    "Run: python scripts/download_face_models.py"
                )
            import cv2  # local import keeps API boot light when unused

            yunet = str(self.weights_dir / YUNET_NAME)
            sface = str(self.weights_dir / SFACE_NAME)
            self._detector = cv2.FaceDetectorYN.create(yunet, "", (320, 320), 0.7, 0.3, 5000)
            self._recognizer = cv2.FaceRecognizerSF.create(sface, "")
            self._loaded = True
            logger.info("Face engine loaded (%s)", MODEL_VERSION)

    def _decode(self, image_bytes: bytes):
        import cv2

        arr = np.frombuffer(image_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("invalid_image")
        return img

    def _basic_spoof_score(self, face_bgr) -> float:
        """Licence-safe quality proxy (not a claim of MiniFASNet-level anti-spoof).

        Combines Laplacian sharpness and colour variance. Range roughly 0..1.
        """
        import cv2

        gray = cv2.cvtColor(face_bgr, cv2.COLOR_BGR2GRAY)
        lap = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        sharp = min(lap / 200.0, 1.0)
        hsv = cv2.cvtColor(face_bgr, cv2.COLOR_BGR2HSV)
        sat_std = float(hsv[:, :, 1].std()) / 64.0
        sat = min(max(sat_std, 0.0), 1.0)
        return float(0.65 * sharp + 0.35 * sat)

    def detect_and_embed(self, image_bytes: bytes) -> DetectedFace:
        import cv2

        self.ensure_loaded()
        assert self._detector is not None and self._recognizer is not None
        img = self._decode(image_bytes)
        h, w = img.shape[:2]
        self._detector.setInputSize((w, h))
        _, faces = self._detector.detect(img)
        if faces is None or len(faces) == 0:
            raise ValueError("no_face")
        if len(faces) > 1:
            # Take largest face by area
            areas = []
            for row in faces:
                areas.append(float(row[2] * row[3]))
            idx = int(np.argmax(areas))
            face = faces[idx]
        else:
            face = faces[0]

        x, y, bw, bh = [int(v) for v in face[:4]]
        x, y = max(x, 0), max(y, 0)
        aligned = self._recognizer.alignCrop(img, face)
        feature = self._recognizer.feature(aligned)
        embedding = feature.flatten().astype(np.float32).tolist()
        crop = img[y : y + bh, x : x + bw]
        if crop.size == 0:
            crop = aligned
        spoof = self._basic_spoof_score(crop)
        quality = min(float(bw * bh) / float(max(w * h, 1)), 1.0)
        return DetectedFace(
            embedding=embedding,
            box=(x, y, bw, bh),
            spoof_score=spoof,
            quality=quality,
        )

    def cosine_similarity(self, a: list[float], b: list[float]) -> float:
        import cv2

        self.ensure_loaded()
        assert self._recognizer is not None
        fa = np.asarray(a, dtype=np.float32).reshape(1, -1)
        fb = np.asarray(b, dtype=np.float32).reshape(1, -1)
        # FaceRecognizerSF match uses cosine by default with FR_COSINE
        score = self._recognizer.match(fa, fb, cv2.FaceRecognizerSF_FR_COSINE)
        return float(score)

    def average_embeddings(self, embeddings: list[list[float]]) -> list[float]:
        arr = np.asarray(embeddings, dtype=np.float32)
        mean = arr.mean(axis=0)
        norm = np.linalg.norm(mean) + 1e-8
        return (mean / norm).astype(np.float32).tolist()


_engine: FaceEngine | None = None
_engine_lock = threading.Lock()


def get_face_engine() -> FaceEngine:
    global _engine
    with _engine_lock:
        if _engine is None:
            _engine = FaceEngine()
        return _engine


# Limit concurrent face jobs to 2 (shared VPS budget).
face_job_semaphore = threading.Semaphore(2)


def with_face_slot(fn):
    acquired = face_job_semaphore.acquire(timeout=30)
    if not acquired:
        raise TimeoutError("face_queue_busy")
    try:
        return fn()
    finally:
        face_job_semaphore.release()


def load_thresholds(settings: Settings, db_settings: dict[str, dict] | None = None) -> dict:
    match = settings.face_match_threshold
    band = 0.02
    spoof_min = 0.35
    if db_settings:
        if "face.match_threshold" in db_settings:
            match = float(db_settings["face.match_threshold"].get("value", match))
        if "face.borderline_band" in db_settings:
            band = float(db_settings["face.borderline_band"].get("below_accept", band))
        if "face.spoof_min_score" in db_settings:
            spoof_min = float(db_settings["face.spoof_min_score"].get("value", spoof_min))
    return {"match": match, "band": band, "spoof_min": spoof_min}
