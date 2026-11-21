"""Key helpers: QR secrets and ECDSA P-256 public key validation."""

from __future__ import annotations

import secrets

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from app.core.errors import AppError


def generate_qr_secret() -> str:
    return secrets.token_urlsafe(32)


def _normalize_pem(pem: str) -> str:
    """Collapse whitespace inside base64 body; keep standard SPKI headers."""
    text = pem.replace("\r\n", "\n").replace("\r", "\n").strip()
    begin = "-----BEGIN PUBLIC KEY-----"
    end = "-----END PUBLIC KEY-----"
    if begin in text and end in text:
        body = text.split(begin, 1)[1].split(end, 1)[0]
        b64 = "".join(body.split())
        wrapped = "\n".join(b64[i : i + 64] for i in range(0, len(b64), 64))
        return f"{begin}\n{wrapped}\n{end}\n"
    return text + ("\n" if not text.endswith("\n") else "")


def validate_ecdsa_p256_public_key_pem(pem: str) -> str:
    """Parse and re-serialize a PEM public key; must be ECDSA P-256."""
    normalized_input = _normalize_pem(pem)
    try:
        key = serialization.load_pem_public_key(normalized_input.encode("utf-8"))
    except Exception as exc:  # noqa: BLE001 — surface as validation error
        raise AppError("invalid_public_key", "Public key PEM could not be parsed") from exc

    if not isinstance(key, ec.EllipticCurvePublicKey):
        raise AppError("invalid_public_key", "Public key must be ECDSA")
    if key.curve.name != "secp256r1":
        raise AppError("invalid_public_key", "Public key must use P-256 (secp256r1)")

    normalized = key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    return normalized
