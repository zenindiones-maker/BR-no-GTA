from __future__ import annotations

from hashlib import sha256
import json


SCHEMA = "TelegramSemanticReasoningRequest/v1"


def build_telegram_semantic_request_id(
    *,
    telegram_chat_id: int,
    telegram_message_id: int,
    human_turn_id: int,
    artifact_content_sha256: str,
    human_text_sha256: str,
) -> str:
    payload = {
        "schema": SCHEMA,
        "telegram_chat_id": int(telegram_chat_id),
        "telegram_message_id": int(telegram_message_id),
        "human_turn_id": int(human_turn_id),
        "artifact_content_sha256": str(artifact_content_sha256 or "").lower(),
        "human_text_sha256": str(human_text_sha256 or "").lower(),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "telegram-semantic-" + sha256(raw).hexdigest()


def deterministic_retry_delay_seconds(
    request_id: str,
    attempt_number: int,
    *,
    base_seconds: float = 1.0,
    max_seconds: float = 300.0,
) -> float:
    attempt = max(1, int(attempt_number))
    ceiling = min(float(max_seconds), float(base_seconds) * (2 ** attempt))
    floor = max(float(base_seconds), ceiling / 2.0)
    digest = sha256(f"{request_id}:{attempt}".encode("utf-8")).digest()
    fraction = int.from_bytes(digest[:8], "big") / float(2**64 - 1)
    return floor + (ceiling - floor) * fraction


def classify_semantic_failure_domain(*, code: str | None, status_code: int | None) -> str:
    normalized = str(code or "").strip().casefold()
    if normalized in {"invalid_credentials", "unauthorized", "auth_required"} or status_code == 401:
        return "AUTH"
    if normalized in {"malformed_structured_output", "invalid_json", "invalid_completion"}:
        return "CONTRACT"
    if normalized in {"provider_profile_integrity_mismatch", "integrity_mismatch"}:
        return "INTEGRITY"
    if normalized in {"model_unavailable", "provider_model_unavailable", "timeout"}:
        return "MODEL_LOCAL"
    if normalized == "quota_exhausted":
        return "FREE_QUOTA_EXHAUSTED"
    if normalized == "rate_limited" or status_code == 429:
        return "RATE_LIMIT"
    if status_code in {500, 502, 503, 504} or normalized in {
        "service_unavailable", "transport_error", "upstream_error"
    }:
        return "PROVIDER_WIDE"
    return "UNKNOWN"
