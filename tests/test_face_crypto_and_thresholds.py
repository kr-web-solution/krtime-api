"""Phase 4 unit tests: embedding AES-GCM + threshold loading."""

from __future__ import annotations

import base64

import numpy as np
import pytest

from app.core.config import Settings
from app.services.embedding_crypto import (
    decrypt_embedding,
    encrypt_embedding,
    packing_float32,
    unpacking_float32,
)
from app.services.face_engine import load_thresholds


def test_pack_unpack_roundtrip() -> None:
    values = [0.1, -0.25, 1.5, 0.0]
    packed = packing_float32(values)
    assert len(packed) == 16
    out = unpacking_float32(packed)
    assert len(out) == 4
    assert out[0] == pytest.approx(0.1, abs=1e-6)


def test_encrypt_decrypt_roundtrip() -> None:
    key = base64.b64encode(b"0123456789abcdef0123456789abcdef").decode("ascii")
    settings = Settings(embedding_encryption_key=key, app_env="test")
    payload = packing_float32([0.5, 0.25, -0.125])
    nonce, ciphertext = encrypt_embedding(settings, payload)
    assert len(nonce) == 12
    assert ciphertext != payload
    plain = decrypt_embedding(settings, nonce=nonce, ciphertext=ciphertext)
    assert plain == payload


def test_encrypt_uses_dev_key_when_unset() -> None:
    settings = Settings(embedding_encryption_key="", app_env="development")
    payload = b"face-bytes-demo"
    nonce, ct = encrypt_embedding(settings, payload)
    assert len(nonce) == 12
    assert decrypt_embedding(settings, nonce=nonce, ciphertext=ct) == payload


def test_dev_fallback_key_is_exactly_32_bytes() -> None:
    from app.services.embedding_crypto import _load_key

    settings = Settings(embedding_encryption_key="", app_env="development")
    assert len(_load_key(settings)) == 32


def test_load_thresholds_defaults_and_overrides() -> None:
    settings = Settings(face_match_threshold=0.363, app_env="test")
    defaults = load_thresholds(settings)
    assert defaults["match"] == pytest.approx(0.363)
    assert defaults["band"] == pytest.approx(0.02)
    assert defaults["spoof_min"] == pytest.approx(0.35)

    overridden = load_thresholds(
        settings,
        {
            "face.match_threshold": {"value": 0.4},
            "face.borderline_band": {"below_accept": 0.03},
            "face.spoof_min_score": {"value": 0.5},
        },
    )
    assert overridden["match"] == pytest.approx(0.4)
    assert overridden["band"] == pytest.approx(0.03)
    assert overridden["spoof_min"] == pytest.approx(0.5)


def test_numpy_cosine_reference_for_borderline_band() -> None:
    """Sanity: borderline band math used by verifier (sim >= match - band)."""
    match = 0.363
    band = 0.02
    sim = 0.350
    assert match - band <= sim < match


def test_average_embeddings_l2() -> None:
    from app.services.face_engine import FaceEngine

    eng = FaceEngine(weights_dir=__import__("pathlib").Path("/nonexistent"))
    avg = eng.average_embeddings([[1.0, 0.0], [0.0, 1.0]])
    norm = float(np.linalg.norm(np.asarray(avg)))
    assert norm == pytest.approx(1.0, abs=1e-5)
