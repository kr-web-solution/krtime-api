"""Verify ECDSA P-256 signatures from registered devices."""

from __future__ import annotations

import base64
import hashlib

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils

from app.core.errors import AppError


def canonical_attendance_message(
    *,
    challenge_id: str,
    employee_id: str,
    lat: float,
    lng: float,
    accuracy: float,
    qr_token: str,
    image_sha256_hex: str,
) -> bytes:
    # Fixed formatting so phone and server sign the same bytes.
    text = (
        f"{challenge_id}|{employee_id}|{lat:.6f}|{lng:.6f}|"
        f"{accuracy:.2f}|{qr_token}|{image_sha256_hex}"
    )
    return text.encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify_ecdsa_p256_signature(*, public_key_pem: str, message: bytes, signature_b64: str) -> None:
    try:
        key = serialization.load_pem_public_key(public_key_pem.encode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise AppError("invalid_public_key", "Stored device public key is invalid") from exc

    if not isinstance(key, ec.EllipticCurvePublicKey) or key.curve.name != "secp256r1":
        raise AppError("invalid_public_key", "Device key must be ECDSA P-256")

    try:
        signature = base64.b64decode(signature_b64, validate=True)
    except Exception as exc:  # noqa: BLE001
        raise AppError("invalid_signature", "Signature is not valid base64") from exc

    try:
        # Android Keystore ECDSA typically produces DER (ASN.1) signatures.
        key.verify(signature, message, ec.ECDSA(hashes.SHA256()))
    except InvalidSignature as exc:
        # Some stacks emit raw r||s (64 bytes). Try converting.
        if len(signature) == 64:
            r = int.from_bytes(signature[:32], "big")
            s = int.from_bytes(signature[32:], "big")
            der = utils.encode_dss_signature(r, s)
            try:
                key.verify(der, message, ec.ECDSA(hashes.SHA256()))
                return
            except InvalidSignature:
                pass
        raise AppError("invalid_signature", "Device signature verification failed") from exc
