"""Verify external, narrowly scoped Ed25519 REA execution consent.

Only verification lives here. No signing key, key generation, model tools,
private credentials, HTTP endpoint, or authority issuance is installed.
Production MUST provide a public key from a trusted external configuration
boundary; absent/invalid key denies all REA inspections.
"""
from __future__ import annotations

import base64
import binascii
from datetime import datetime, timezone
import json
import os
import time
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

SCHEMA = "BRReaTrustedIssuerAttestation/v1"
PUBLIC_KEY_ENV = "BR_REA_TRUSTED_ISSUER_PUBLIC_KEY_B64"
MAX_VALIDITY_SECONDS = 120
MAX_CLOCK_SKEW_SECONDS = 10


class IssuerAttestationBlocked(PermissionError):
    """Trusted issuer proof unavailable, invalid, stale or out of scope."""


def canonical_message(authorization: Any, paths: tuple[str, ...], *, issued_at: int, expires_at: int) -> bytes:
    if type(issued_at) is not int or type(expires_at) is not int:
        raise IssuerAttestationBlocked("Issuer proof time fields must be integer seconds")
    if expires_at <= issued_at or expires_at - issued_at > MAX_VALIDITY_SECONDS:
        raise IssuerAttestationBlocked("Issuer proof lifetime outside allowed window")
    return json.dumps(
        {
            "schema": SCHEMA,
            "purpose": "one_shot_first_party_python_source_inspection",
            "authorization_id": authorization.authorization_id,
            "harness_decision_id": authorization.harness_decision_id,
            "execution_id": authorization.execution_id,
            "action": authorization.authorized_action,
            "subject": authorization.subject,
            "paths": list(paths),
            "issued_at": issued_at,
            "expires_at": expires_at,
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _decode(value: str, *, expected_length: int) -> bytes:
    if not isinstance(value, str) or len(value) > 128:
        raise IssuerAttestationBlocked("Issuer proof encoding invalid")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise IssuerAttestationBlocked("Issuer proof encoding invalid") from exc
    if len(decoded) != expected_length:
        raise IssuerAttestationBlocked("Issuer proof length invalid")
    return decoded


def verify_trusted_issuer_attestation(authorization: Any, paths: tuple[str, ...], proof: Any) -> None:
    if not isinstance(proof, dict) or set(proof) != {"schema", "issued_at", "expires_at", "signature_b64"}:
        raise IssuerAttestationBlocked("Exact signed issuer proof required")
    if proof["schema"] != SCHEMA:
        raise IssuerAttestationBlocked("Unrecognized issuer proof schema")
    now = int(time.time())
    issued_at, expires_at = proof["issued_at"], proof["expires_at"]
    message = canonical_message(authorization, paths, issued_at=issued_at, expires_at=expires_at)
    if issued_at > now + MAX_CLOCK_SKEW_SECONDS or expires_at <= now:
        raise IssuerAttestationBlocked("Issuer proof expired or from the future")
    public_key = os.environ.get(PUBLIC_KEY_ENV)
    if not public_key:
        raise IssuerAttestationBlocked("Trusted REA public key not provisioned")
    encoded_key = _decode(public_key, expected_length=32)
    signature = _decode(proof["signature_b64"], expected_length=64)
    try:
        Ed25519PublicKey.from_public_bytes(encoded_key).verify(signature, message)
    except (ValueError, InvalidSignature) as exc:
        raise IssuerAttestationBlocked("Issuer proof signature invalid") from exc
