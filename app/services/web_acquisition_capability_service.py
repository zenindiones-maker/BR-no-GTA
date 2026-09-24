from __future__ import annotations

import base64
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Any
from urllib import error, parse, request

from app.services.harness_authorization_service import (
    validate_harness_authorization,
)
from app.services.harness_routing_policy_service import HarnessRoutingDecision
from app.services.zero_cost_policy_service import (
    CostClass,
    ZeroCostFailureReason,
    ZeroCostPolicyError,
    enforce_zero_cost,
)

WEB_SEARCH_DISCOVER = "web.search.discover"
WEB_SOURCE_ACQUIRE = "web.source.acquire"
WEB_EVIDENCE_SNAPSHOT = "web.evidence.snapshot"

SEARCH_BINDING = (
    "app.services.web_acquisition_capability_service."
    "execute_web_search_discover"
)
ACQUIRE_BINDING = (
    "app.services.web_acquisition_capability_service."
    "execute_web_source_acquire"
)
SNAPSHOT_BINDING = (
    "app.services.web_acquisition_capability_service."
    "execute_web_evidence_snapshot"
)

APILAYER_SEARCH_URL = "https://api.apilayer.com/google_search"
APILAYER_SCRAPER_URL = "https://api.apilayer.com/scraper"
APILAYER_URL_TO_PDF_URL = "https://api.apilayer.com/url_to_pdf"

MAX_SOURCE_BYTES = 512_000
MAX_SOURCE_CHARS = 120_000
MAX_SNAPSHOT_BYTES = 2_000_000
DEFAULT_TIMEOUT_SECONDS = 25.0

_QUOTA_STATE: dict[str, dict[str, Any]] = {}


class APILayerAuthRequired(RuntimeError):
    pass


class APILayerTransportError(RuntimeError):
    pass


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _endpoint(env_name: str, default: str) -> str:
    return str(os.getenv(env_name) or default).strip()


def _cache_root() -> Path:
    return Path(
        os.getenv("BR_WEB_ACQUISITION_CACHE_DIR")
        or ".runtime/web-acquisition-cache"
    )


def _url_key(url: str) -> str:
    return sha256(url.encode("utf-8")).hexdigest()


def _headers_dict(headers: Any) -> dict[str, str]:
    if headers is None:
        return {}
    try:
        return {
            str(key).casefold(): str(value)
            for key, value in headers.items()
        }
    except Exception:
        return {}


def _quota_from_headers(transport: str, headers: Any) -> dict[str, Any]:
    normalized = _headers_dict(headers)

    def integer(*names: str) -> int | None:
        for name in names:
            raw = normalized.get(name.casefold())
            if raw is None:
                continue
            try:
                return int(str(raw).strip())
            except (TypeError, ValueError):
                continue
        return None

    remaining = integer(
        "x-ratelimit-remaining-month",
        "x-ratelimit-remaining",
        "ratelimit-remaining",
    )
    limit = integer(
        "x-ratelimit-limit-month",
        "x-ratelimit-limit",
        "ratelimit-limit",
    )
    reset = (
        normalized.get("x-ratelimit-reset")
        or normalized.get("ratelimit-reset")
    )
    state = _QUOTA_STATE.setdefault(transport, {})
    if remaining is not None:
        state["quota_remaining"] = remaining
    if limit is not None:
        state["quota_limit"] = limit
    if reset:
        state["quota_reset"] = reset
    state["updated_at"] = _utcnow()
    return dict(state)


def _quota_available(transport: str) -> bool | None:
    value = _QUOTA_STATE.get(transport, {}).get("quota_remaining")
    if value is None:
        return None
    return int(value) > 0


def _enforce_transport_zero_cost(transport: str) -> None:
    enforce_zero_cost(
        CostClass.FREE_QUOTA_LIMITED,
        quota_available=_quota_available(transport),
    )


def _api_key() -> str:
    value = str(os.getenv("APILAYER_API_KEY") or "").strip()
    if not value:
        raise APILayerAuthRequired("APILAYER_API_KEY_REQUIRED")
    return value


def _apilayer_request(
    *,
    transport: str,
    endpoint: str,
    params: dict[str, Any],
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> tuple[bytes, dict[str, Any]]:
    _enforce_transport_zero_cost(transport)
    key = _api_key()
    query = parse.urlencode({
        str(k): str(v)
        for k, v in params.items()
        if v is not None
    })
    url = endpoint + ("&" if "?" in endpoint else "?") + query
    req = request.Request(
        url,
        headers={
            "Accept": "*/*",
            "apikey": key,
            "User-Agent": "BR-no-GTA-Harness/1.0",
        },
        method="GET",
    )
    started = datetime.now(timezone.utc)
    try:
        with request.urlopen(req, timeout=float(timeout_seconds)) as response:
            raw = response.read(MAX_SNAPSHOT_BYTES + 1)
            headers = _quota_from_headers(transport, response.headers)
            if len(raw) > MAX_SNAPSHOT_BYTES:
                raise APILayerTransportError(
                    "APILAYER_RESPONSE_EXCEEDS_BOUNDED_LIMIT"
                )
            state = _QUOTA_STATE.setdefault(transport, {})
            state["last_success"] = _utcnow()
            return raw, {
                **headers,
                "http_status": int(getattr(response, "status", 200) or 200),
                "latency_seconds": max(
                    0.0,
                    (datetime.now(timezone.utc) - started).total_seconds(),
                ),
            }
    except error.HTTPError as exc:
        headers = _quota_from_headers(transport, exc.headers)
        state = _QUOTA_STATE.setdefault(transport, {})
        state["last_failure"] = _utcnow()
        state["failure_class"] = f"HTTP_{int(exc.code)}"
        if int(exc.code) in {402, 429}:
            state["quota_remaining"] = 0
            raise ZeroCostPolicyError(
                ZeroCostFailureReason.FREE_QUOTA_EXHAUSTED,
                "APILayer free quota is unavailable",
            ) from None
        if int(exc.code) in {401, 403}:
            raise APILayerAuthRequired(
                "APILAYER_PRODUCT_AUTH_REQUIRED"
            ) from None
        raise APILayerTransportError(
            f"APILAYER_HTTP_{int(exc.code)}"
        ) from None
    except (error.URLError, TimeoutError, OSError) as exc:
        state = _QUOTA_STATE.setdefault(transport, {})
        state["last_failure"] = _utcnow()
        state["failure_class"] = type(exc).__name__
        raise APILayerTransportError(
            "APILAYER_TRANSPORT_FAILED"
        ) from None


def _validate_boundary(
    *,
    capability_id: str,
    binding: str,
    authorization,
    routing_decision: HarnessRoutingDecision,
):
    auth = validate_harness_authorization(
        authorization,
        expected_action=routing_decision.authorized_action,
        expected_subject=f"capability:{capability_id}",
    )
    if routing_decision.selected_capability_id != capability_id:
        raise PermissionError("web acquisition capability routing mismatch")
    if routing_decision.selected_executor_binding != binding:
        raise PermissionError("web acquisition executor routing mismatch")
    return auth


def _provenance(
    *,
    source_url: str,
    transport_provider: str,
    auth,
    content_hash: str,
    cache_hit: bool,
    quota: dict[str, Any] | None = None,
) -> dict[str, Any]:
    safe_quota = {
        key: value
        for key, value in dict(quota or {}).items()
        if key in {
            "quota_remaining",
            "quota_limit",
            "quota_reset",
            "last_success",
            "last_failure",
            "failure_class",
        }
    }
    return {
        "source_url": source_url,
        "transport_provider": transport_provider,
        "retrieved_at": _utcnow(),
        "content_hash": content_hash,
        "execution_id": auth.execution_id,
        "authorization_id": auth.authorization_id,
        "cache_hit": bool(cache_hit),
        **safe_quota,
    }


def _source_cache_path(url: str) -> Path:
    return _cache_root() / "source" / f"{_url_key(url)}.json"


def _read_source_cache(url: str) -> dict[str, Any] | None:
    path = _source_cache_path(url)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("source_url") != url:
        return None
    return payload


def _write_source_cache(url: str, payload: dict[str, Any]) -> None:
    path = _source_cache_path(url)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )


def _direct_fetch(url: str, timeout_seconds: float) -> tuple[bytes, str]:
    req = request.Request(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml,application/json,text/plain,*/*",
            "User-Agent": "BR-no-GTA-Harness/1.0",
        },
        method="GET",
    )
    with request.urlopen(req, timeout=float(timeout_seconds)) as response:
        raw = response.read(MAX_SOURCE_BYTES + 1)
        if len(raw) > MAX_SOURCE_BYTES:
            raw = raw[:MAX_SOURCE_BYTES]
        content_type = str(
            getattr(response, "headers", {}).get(
                "Content-Type", "application/octet-stream"
            )
        )
        return raw, content_type


def _decode_source(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="replace")
    return text[:MAX_SOURCE_CHARS]


def execute_web_search_discover(
    *,
    authorization,
    routing_decision: HarnessRoutingDecision,
    payload: dict[str, Any],
) -> dict[str, Any]:
    auth = _validate_boundary(
        capability_id=WEB_SEARCH_DISCOVER,
        binding=SEARCH_BINDING,
        authorization=authorization,
        routing_decision=routing_decision,
    )
    query = str(payload.get("query") or "").strip()
    if not query:
        raise ValueError("web.search.discover requires query")
    raw, quota = _apilayer_request(
        transport="apilayer_google_search",
        endpoint=_endpoint(
            "APILAYER_GOOGLE_SEARCH_URL",
            APILAYER_SEARCH_URL,
        ),
        params={"q": query},
    )
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise APILayerTransportError(
            "APILAYER_SEARCH_INVALID_JSON"
        ) from None
    candidates = []
    if isinstance(decoded, dict):
        for key in ("organic_results", "organic", "results", "items"):
            value = decoded.get(key)
            if isinstance(value, list):
                candidates = value
                break
    results = []
    for item in candidates[:10]:
        if not isinstance(item, dict):
            continue
        url = str(item.get("link") or item.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            continue
        results.append({
            "url": url,
            "title": str(item.get("title") or "")[:500],
            "snippet": str(
                item.get("snippet")
                or item.get("description")
                or ""
            )[:1500],
        })
    digest = sha256(raw).hexdigest()
    return {
        "status": "EXECUTED",
        "query": query,
        "results": results,
        "result_count": len(results),
        "provenance": _provenance(
            source_url="search-query:" + query,
            transport_provider="apilayer_google_search",
            auth=auth,
            content_hash=digest,
            cache_hit=False,
            quota=quota,
        ),
    }


def execute_web_source_acquire(
    *,
    authorization,
    routing_decision: HarnessRoutingDecision,
    payload: dict[str, Any],
) -> dict[str, Any]:
    auth = _validate_boundary(
        capability_id=WEB_SOURCE_ACQUIRE,
        binding=ACQUIRE_BINDING,
        authorization=authorization,
        routing_decision=routing_decision,
    )
    source_url = str(payload.get("source_url") or payload.get("url") or "").strip()
    if not source_url.startswith(("http://", "https://")):
        raise ValueError("web.source.acquire requires http(s) source_url")

    cached = _read_source_cache(source_url)
    if cached is not None:
        result = dict(cached)
        provenance = dict(result.get("provenance") or {})
        provenance.update({
            "cache_hit": True,
            "execution_id": auth.execution_id,
            "authorization_id": auth.authorization_id,
        })
        result["provenance"] = provenance
        result["cache_hit"] = True
        return result

    timeout_seconds = float(
        payload.get("timeout_seconds") or DEFAULT_TIMEOUT_SECONDS
    )
    transport = "direct"
    quota: dict[str, Any] = {}
    try:
        raw, content_type = _direct_fetch(source_url, timeout_seconds)
    except (error.HTTPError, error.URLError, TimeoutError, OSError):
        transport = "apilayer_scraper"
        raw, quota = _apilayer_request(
            transport=transport,
            endpoint=_endpoint(
                "APILAYER_SCRAPER_URL",
                APILAYER_SCRAPER_URL,
            ),
            params={"url": source_url},
            timeout_seconds=timeout_seconds,
        )
        content_type = "text/html"
        try:
            candidate = json.loads(raw.decode("utf-8"))
            if isinstance(candidate, dict):
                body = candidate.get("content") or candidate.get("data")
                if isinstance(body, str):
                    raw = body.encode("utf-8")
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass

    digest = sha256(raw).hexdigest()
    result = {
        "status": "EXECUTED",
        "source_url": source_url,
        "content": _decode_source(raw),
        "content_type": content_type,
        "size_bytes": len(raw),
        "content_truncated": len(raw) > MAX_SOURCE_CHARS,
        "cache_hit": False,
        "provenance": _provenance(
            source_url=source_url,
            transport_provider=transport,
            auth=auth,
            content_hash=digest,
            cache_hit=False,
            quota=quota,
        ),
    }
    _write_source_cache(source_url, result)
    return result


def execute_web_evidence_snapshot(
    *,
    authorization,
    routing_decision: HarnessRoutingDecision,
    payload: dict[str, Any],
) -> dict[str, Any]:
    auth = _validate_boundary(
        capability_id=WEB_EVIDENCE_SNAPSHOT,
        binding=SNAPSHOT_BINDING,
        authorization=authorization,
        routing_decision=routing_decision,
    )
    if payload.get("snapshot_required") is not True:
        raise ValueError(
            "web.evidence.snapshot requires snapshot_required=true"
        )
    source_url = str(payload.get("source_url") or payload.get("url") or "").strip()
    if not source_url.startswith(("http://", "https://")):
        raise ValueError("web.evidence.snapshot requires http(s) source_url")
    raw, quota = _apilayer_request(
        transport="apilayer_url_to_pdf",
        endpoint=_endpoint(
            "APILAYER_URL_TO_PDF_URL",
            APILAYER_URL_TO_PDF_URL,
        ),
        params={"url": source_url},
    )
    if not raw.startswith(b"%PDF"):
        raise APILayerTransportError(
            "APILAYER_SNAPSHOT_NOT_PDF"
        )
    if len(raw) > MAX_SNAPSHOT_BYTES:
        raise APILayerTransportError(
            "APILAYER_SNAPSHOT_EXCEEDS_BOUNDED_LIMIT"
        )
    digest = sha256(raw).hexdigest()
    return {
        "status": "EXECUTED",
        "source_url": source_url,
        "mime_type": "application/pdf",
        "size_bytes": len(raw),
        "snapshot_base64": base64.b64encode(raw).decode("ascii"),
        "provenance": _provenance(
            source_url=source_url,
            transport_provider="apilayer_url_to_pdf",
            auth=auth,
            content_hash=digest,
            cache_hit=False,
            quota=quota,
        ),
    }


def apilayer_health_snapshot() -> dict[str, Any]:
    return {
        "configured": bool(str(os.getenv("APILAYER_API_KEY") or "").strip()),
        "products": {
            transport: dict(state)
            for transport, state in _QUOTA_STATE.items()
        },
    }
