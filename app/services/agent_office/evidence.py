from __future__ import annotations

from hashlib import sha256
import json
import re
from typing import Any


_SENSITIVE_KEY = re.compile(r"(?:api[_-]?key|secret|token|password|credential|authorization)", re.I)


def sanitize_evidence(value: Any, *, key: str = "") -> Any:
    """Remove secret-shaped fields before mission output reaches Harness evidence."""
    if _SENSITIVE_KEY.search(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {
            str(item_key): sanitize_evidence(item_value, key=str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [sanitize_evidence(item) for item in value]
    if isinstance(value, str):
        return value[:20_000]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:2_000]


def evidence_digest(value: Any) -> str:
    canonical = json.dumps(
        sanitize_evidence(value),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return sha256(canonical.encode("utf-8")).hexdigest()
