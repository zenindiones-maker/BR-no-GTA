"""Offline privacy-preserving HAR 1.2 analysis for authorized web-app behavior.

Never opens a URL, replays a request, reads secret headers into a receipt,
executes JavaScript, or outputs original hostnames, paths, query strings or bodies.
"""
from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from app.services.reverse_engineering_media_service import ObservationError, _source, _sha256

SCHEMA = "BROfflineWebHARObservation/v1"
MAX_BYTES = 8_000_000
MAX_ENTRIES = 10_000
METHODS = frozenset({"GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE"})
CATEGORIES = ("html", "javascript", "json", "css", "image", "font", "audio", "video", "other")


def _mime_category(raw: Any) -> str:
    value = str(raw or "").split(";", 1)[0].lower().strip()
    if value in {"text/html", "application/xhtml+xml"}:
        return "html"
    if "javascript" in value or value in {"application/ecmascript", "text/ecmascript"}:
        return "javascript"
    if value == "application/json" or value.endswith("+json"):
        return "json"
    if value == "text/css":
        return "css"
    for group in ("image", "audio", "video", "font"):
        if value.startswith(group + "/"):
            return group
    if value.startswith("application/font") or "woff" in value:
        return "font"
    return "other"


def analyze_web_har(path: str | Path, *, rights: str) -> dict[str, Any]:
    if rights not in {"owned", "licensed", "observation_only"}:
        raise ObservationError("WEB_HAR_RIGHTS_REQUIRED")
    source = _source(path, allowed_suffixes=(".har", ".json"))
    if source.stat().st_size > MAX_BYTES:
        raise ObservationError("WEB_HAR_TOO_LARGE")
    try:
        data = json.loads(source.read_text(encoding="utf-8-sig"))
    except (UnicodeError, ValueError) as exc:
        raise ObservationError("WEB_HAR_UNREADABLE") from exc
    if not isinstance(data, dict) or not isinstance(data.get("log"), dict):
        raise ObservationError("WEB_HAR_INVALID_SCHEMA")
    har = data["log"]
    if har.get("version") != "1.2" or not isinstance(har.get("entries"), list):
        raise ObservationError("WEB_HAR_INVALID_SCHEMA")
    entries = har["entries"]
    if len(entries) > MAX_ENTRIES:
        raise ObservationError("WEB_HAR_TOO_MANY_ENTRIES")
    methods: Counter[str] = Counter()
    responses: Counter[str] = Counter()
    categories: Counter[str] = Counter()
    origins: set[tuple[str, str]] = set()
    durations: list[float] = []
    for item in entries:
        if not isinstance(item, dict):
            raise ObservationError("WEB_HAR_ENTRY_INVALID")
        request = item.get("request")
        response = item.get("response")
        if not isinstance(request, dict) or not isinstance(response, dict):
            raise ObservationError("WEB_HAR_ENTRY_INVALID")
        url = request.get("url")
        if not isinstance(url, str) or len(url) > 16_384:
            raise ObservationError("WEB_HAR_URL_INVALID")
        try:
            parsed = urlsplit(url)
            if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
                raise ValueError("non-http")
            origins.add((parsed.scheme.lower(), parsed.hostname.casefold()))
        except (ValueError, TypeError) as exc:
            raise ObservationError("WEB_HAR_URL_INVALID") from exc
        method = str(request.get("method", "OTHER")).upper()
        methods[method if method in METHODS else "OTHER"] += 1
        status = response.get("status")
        if type(status) is not int or status < 0 or status > 599:
            raise ObservationError("WEB_HAR_STATUS_INVALID")
        responses["NETWORK_OR_UNKNOWN" if status == 0 else f"{status // 100}xx"] += 1
        content = response.get("content")
        if content is not None and not isinstance(content, dict):
            raise ObservationError("WEB_HAR_CONTENT_INVALID")
        categories[_mime_category((content or {}).get("mimeType"))] += 1
        elapsed = item.get("time")
        if type(elapsed) in (int, float) and math.isfinite(elapsed) and 0 <= elapsed <= 3_600_000:
            durations.append(float(elapsed))
    ordered = sorted(durations)
    p95 = ordered[min(len(ordered) - 1, max(0, math.ceil(len(ordered) * 0.95) - 1))] if ordered else None
    result: dict[str, Any] = {
        "schema_version": SCHEMA,
        "status": "MEASURED",
        "source_sha256": _sha256(source),
        "declared_rights": rights,
        "source_format": "HAR_1.2_OFFLINE",
        "request_count": len(entries),
        "unique_origin_count": len(origins),
        "methods": dict(sorted(methods.items())),
        "response_status_families": dict(sorted(responses.items())),
        "mime_families": dict(sorted(categories.items())),
        "timing_coverage_requests": len(ordered),
        "response_time_median_ms": round(statistics.median(ordered), 2) if ordered else None,
        "response_time_p95_ms": round(p95, 2) if p95 is not None else None,
        "limitations": (
            "Offline HAR metadata is not browser performance, accessibility or security proof; "
            "timestamps are recorded by HAR producer, sensitive values are not emitted"
        ),
        "network_access": "NONE",
        "source_content_replayed": False,
        "ui_behavior_verified": False,
        "auth_headers_released": False,
    }
    canonical = json.dumps(result, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    result["evidence_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return result
