from __future__ import annotations

import base64
import json
from typing import Any, Mapping


SCHEMA = "FreshResearchDispatchEnvelope/v1"
_ALLOWED_CONTEXT_KEYS = (
    "id",
    "classification",
    "input_kind",
    "source_url",
    "memory_event_id",
)


def _clean_context(source_context: Mapping[str, Any] | None) -> dict[str, Any]:
    raw = dict(source_context or {})
    return {
        key: raw.get(key)
        for key in _ALLOWED_CONTEXT_KEYS
        if raw.get(key) not in (None, "")
    }


def encode_fresh_research_query_b64(
    query: str,
    *,
    source_context: Mapping[str, Any] | None = None,
) -> str:
    clean_query = str(query or "").strip()
    if not clean_query:
        raise ValueError("fresh research query is required")
    envelope = {
        "schema": SCHEMA,
        "query": clean_query,
        "source_context": _clean_context(source_context),
    }
    raw = json.dumps(
        envelope,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


def decode_fresh_research_query_b64(value: str) -> tuple[str, dict[str, Any]]:
    try:
        decoded = base64.b64decode(
            str(value or "").encode("ascii"),
            validate=True,
        ).decode("utf-8").strip()
    except Exception as exc:
        raise ValueError("query_b64 is invalid") from exc
    if not decoded:
        raise ValueError("research query is required")

    try:
        payload = json.loads(decoded)
    except json.JSONDecodeError:
        return decoded, {}

    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
        # Backward compatibility: a user's literal research query may itself be
        # valid JSON. Only the explicit schema is interpreted as a transport envelope.
        return decoded, {}

    query = str(payload.get("query") or "").strip()
    if not query:
        raise ValueError("fresh research dispatch envelope query is required")
    context = payload.get("source_context")
    if not isinstance(context, dict):
        raise ValueError("fresh research dispatch envelope context is invalid")
    return query, _clean_context(context)
