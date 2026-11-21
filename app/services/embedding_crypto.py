"""AES-256-GCM encryption for face embeddings."""

from __future__ import annotations

import base64
import os
import struct

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import Settings
from app.core.errors import AppError


def _load_key(settings: Settings) -> bytes:
    raw = (settings.embedding_encryption_key or "").strip()
    if not raw:
        if settings.is_production:
            raise AppError(
                "embedding_key_missing",
                "EMBEDDING_ENCRYPTION_KEY is required in production",
                status_code=500,
            )
        # Deterministic 32-byte dev-only key so local enroll/verify works without secrets.
        raw = base64.b64encode(b"attendguard-dev-embedding-key!32").decode("ascii")
    try:
        key = base64.b64decode(raw, validate=True)
    except Exception as exc:  # noqa: BLE001
        raise AppError("embedding_key_invalid", "EMBEDDING_ENCRYPTION_KEY must be base64") from exc
    if len(key) != 32:
        raise AppError(
            "embedding_key_invalid",
            "EMBEDDING_ENCRYPTION_KEY must decode to 32 bytes",
            status_code=500,
        )
    return key


def encrypt_embedding(settings: Settings, embedding: bytes) -> tuple[bytes, bytes]:
    """Returns (nonce, ciphertext_with_tag)."""
    key = _load_key(settings)
    nonce = os.urandom(12)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, embedding, associated_data=b"attendguard-face-v1")
    return nonce, ciphertext


def decrypt_embedding(settings: Settings, *, nonce: bytes, ciphertext: bytes) -> bytes:
    key = _load_key(settings)
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ciphertext, associated_data=b"attendguard-face-v1")


def packing_float32(values: list[float]) -> bytes:
    return struct.pack(f"{len(values)}f", *values)


def unpacking_float32(data: bytes) -> list[float]:
    n = len(data) // 4
    return list(struct.unpack(f"{n}f", data))
