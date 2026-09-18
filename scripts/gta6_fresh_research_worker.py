from __future__ import annotations

import argparse
import base64
import hashlib
import html
import ipaddress
import json
import re
import socket
import sys
import urllib.parse
import urllib.request
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.integrations.gta6.news_feeds import fetch_gta6_news_feeds


OFFICIAL_SOURCES = (
    ("Rockstar GTA VI", "https://www.rockstargames.com/VI"),
    ("Rockstar Store GTA VI", "https://store.rockstargames.com/game/buy-gta-vi"),
    ("Rockstar Newswire", "https://www.rockstargames.com/newswire"),
)
USER_AGENT = "BR-no-GTA-FreshResearch/1.0"
MAX_OFFICIAL_TEXT = 12000
MAX_SECONDARY_ITEMS = 24


def _decode_query(value: str) -> str:
    try:
        return base64.b64decode(value.encode("ascii"), validate=True).decode("utf-8").strip()
    except Exception as exc:
        raise ValueError("query_b64 is invalid") from exc


def _decode_optional(value: str) -> str:
    clean = str(value or "").strip()
    if not clean:
        return ""
    try:
        return base64.b64decode(clean.encode("ascii"), validate=True).decode("utf-8").strip()
    except Exception as exc:
        raise ValueError("source_url_b64 is invalid") from exc


def _public_https_url(value: str) -> str:
    parsed = urllib.parse.urlparse(str(value or "").strip())
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("submitted source URL must use public HTTPS")
    host = parsed.hostname.rstrip(".").casefold()
    if host in {"localhost"} or host.endswith((".local", ".internal")):
        raise ValueError("submitted source URL host is not public")
    try:
        addresses = {
            item[4][0]
            for item in socket.getaddrinfo(host, parsed.port or 443, type=socket.SOCK_STREAM)
        }
    except socket.gaierror as exc:
        raise ValueError("submitted source URL host cannot be resolved") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise ValueError("submitted source URL resolved to non-public address")
    return urllib.parse.urlunparse(parsed)


def _root_domain(url: str) -> str:
    host = (urllib.parse.urlparse(url).hostname or "").casefold()
    parts = [part for part in host.split(".") if part]
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def _content_fingerprint(value: str) -> str:
    normalized = " ".join(re.sub(r"\W+", " ", str(value or "").casefold()).split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _source_hierarchy(url: str) -> str:
    host = (urllib.parse.urlparse(url).hostname or "").casefold()
    if host == "rockstargames.com" or host.endswith(".rockstargames.com"):
        return "OFFICIAL_PRIMARY"
    if host == "take2games.com" or host.endswith(".take2games.com"):
        return "OFFICIAL_PRIMARY"
    return "SECONDARY_REPORT"


def _secondary_hierarchy(payload: dict[str, Any]) -> tuple[str, str]:
    source_name = str(payload.get("source_name") or "")
    text = " ".join(
        str(payload.get(key) or "")
        for key in ("title", "summary", "source_name")
    ).casefold()
    if "reddit" in source_name.casefold():
        return "COMMUNITY_SIGNAL", _root_domain(str(payload.get("url") or ""))
    rockstar_markers = (
        "according to rockstar", "rockstar said", "rockstar says",
        "rockstar confirmed", "rockstar announced", "rockstar revealed",
    )
    take_two_markers = (
        "according to take-two", "according to take two", "take-two said",
        "take two said", "take-two confirmed", "take two confirmed",
    )
    if any(marker in text for marker in rockstar_markers):
        return "PRIMARY_STATEMENT_REPORTED_BY_SECONDARY", "primary-statement:rockstar"
    if any(marker in text for marker in take_two_markers):
        return "PRIMARY_STATEMENT_REPORTED_BY_SECONDARY", "primary-statement:take-two"
    return "SECONDARY_REPORT", _root_domain(str(payload.get("url") or ""))


def _platform(url: str) -> str:
    host = (urllib.parse.urlparse(url).hostname or "").casefold()
    if host.endswith("instagram.com"):
        return "instagram"
    if host in {"x.com", "www.x.com"} or host.endswith("twitter.com"):
        return "x"
    return "web"


def _fetch_text(url: str, *, timeout: int = 25) -> tuple[str, str]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9,pt-BR;q=0.8",
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.5",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        final_url = response.geturl()
        content_type = str(response.headers.get("Content-Type") or "").casefold()
        raw_bytes = response.read(2_000_000)
    if "text/" not in content_type and "json" not in content_type and content_type:
        raise ValueError("submitted source is not textual")
    raw = raw_bytes.decode("utf-8", errors="replace")
    raw = re.sub(r"<script\b[^>]*>.*?</script>", " ", raw, flags=re.I | re.S)
    raw = re.sub(r"<style\b[^>]*>.*?</style>", " ", raw, flags=re.I | re.S)
    raw = re.sub(r"<[^>]+>", " ", raw)
    text = " ".join(html.unescape(raw).split())
    return text, final_url


def _resolve_submitted_source(source_url: str, *, checked_at: str) -> dict[str, Any]:
    try:
        safe_url = _public_https_url(source_url)
        text, final_url = _fetch_text(safe_url)
        final_url = _public_https_url(final_url)
        platform = _platform(safe_url)
        lowered = text.casefold()
        unusable_markers = (
            "log in to instagram", "login • instagram", "something went wrong",
            "javascript is not available", "enable javascript",
        )
        minimum = 80 if platform == "web" else 40
        if len(text.strip()) < minimum or any(marker in lowered for marker in unusable_markers):
            raise ValueError("original source content was not recoverable as usable text")
        excerpt = text[:16000]
        return {
            "resolution_status": "PASS",
            "source_name": urllib.parse.urlparse(safe_url).hostname,
            "url": safe_url,
            "resolved_url": final_url,
            "platform": platform,
            "retrieved_at": checked_at,
            "source_hierarchy": _source_hierarchy(safe_url),
            "original_source_retrieved": True,
            "content_excerpt": excerpt,
            "content_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "independent_group": _root_domain(safe_url),
            "content_fingerprint": _content_fingerprint(excerpt),
        }
    except Exception as exc:
        return {
            "resolution_status": "FAIL",
            "source_name": urllib.parse.urlparse(source_url).hostname or "submitted-source",
            "url": source_url,
            "resolved_url": None,
            "platform": _platform(source_url),
            "retrieved_at": checked_at,
            "source_hierarchy": None,
            "original_source_retrieved": False,
            "content_excerpt": "",
            "content_sha256": None,
            "independent_group": None,
            "content_fingerprint": None,
            "error": type(exc).__name__,
        }


def _query_terms(query: str) -> tuple[str, ...]:
    words = re.findall(r"[A-Za-zÀ-ÿ0-9]+", query.casefold())
    stop = {
        "a", "as", "o", "os", "de", "da", "do", "das", "dos", "e", "em", "um", "uma",
        "que", "qual", "quais", "como", "sobre", "para", "por", "me", "diga", "hoje",
        "gta", "6", "vi",
    }
    return tuple(dict.fromkeys(word for word in words if len(word) >= 4 and word not in stop))


def _relevant_excerpt(text: str, query: str, *, limit: int = MAX_OFFICIAL_TEXT) -> str:
    if len(text) <= limit:
        return text
    terms = _query_terms(query)
    anchors = (
        "november 19, 2026",
        "release date",
        "coming",
        "jason",
        "lucia",
        "leonida",
        "vice city",
        "trailer",
        "pre-order",
        *terms,
    )
    lowered = text.casefold()
    windows: list[tuple[int, int]] = []
    for anchor in anchors:
        start = 0
        needle = anchor.casefold()
        while needle and len(windows) < 24:
            pos = lowered.find(needle, start)
            if pos < 0:
                break
            windows.append((max(0, pos - 500), min(len(text), pos + 1500)))
            start = pos + len(needle)
    if not windows:
        return text[:limit]
    windows.sort()
    merged: list[tuple[int, int]] = []
    for start, end in windows:
        if merged and start <= merged[-1][1] + 120:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    rendered = " ... ".join(text[start:end] for start, end in merged)
    return rendered[:limit]


def collect(
    query: str,
    *,
    execution_id: str,
    source_url: str = "",
    telegram_input_id: str = "",
    classification: str = "",
    input_kind: str = "",
    memory_event_id: str = "",
) -> dict[str, Any]:
    checked_at = datetime.now(timezone.utc).isoformat()
    submitted_source = (
        _resolve_submitted_source(source_url, checked_at=checked_at)
        if source_url else None
    )
    official: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    for source_name, url in OFFICIAL_SOURCES:
        try:
            text, resolved_url = _fetch_text(url)
        except Exception as exc:
            errors.append({"source": source_name, "url": url, "error": type(exc).__name__})
            continue
        official.append(
            {
                "source_name": source_name,
                "url": url,
                "authority": "official",
                "source_hierarchy": "OFFICIAL_PRIMARY",
                "original_source": True,
                "resolved_url": resolved_url,
                "checked_at": checked_at,
                "independent_group": _root_domain(url),
                "content_fingerprint": _content_fingerprint(_relevant_excerpt(text, query)),
                "content_excerpt": _relevant_excerpt(text, query),
            }
        )

    secondary: list[dict[str, Any]] = []
    try:
        items = fetch_gta6_news_feeds(timeout=20)
    except Exception as exc:
        errors.append({"source": "configured-news-feeds", "url": "", "error": type(exc).__name__})
        items = []
    for item in items[:MAX_SECONDARY_ITEMS]:
        payload = asdict(item)
        hierarchy, independent_group = _secondary_hierarchy(payload)
        payload["authority"] = "community" if hierarchy == "COMMUNITY_SIGNAL" else "secondary"
        payload["source_hierarchy"] = hierarchy
        payload["original_source"] = False
        payload["independent_group"] = independent_group
        payload["content_fingerprint"] = _content_fingerprint(
            f"{payload.get('title') or ''} {payload.get('summary') or ''}"
        )
        secondary.append(payload)

    status = "PASS" if official else "FAIL"
    return {
        "status": status,
        "execution_id": execution_id,
        "query": query,
        "checked_at": checked_at,
        "telegram_context": {
            "telegram_input_id": telegram_input_id or None,
            "classification": classification or None,
            "input_kind": input_kind or None,
            "memory_event_id": memory_event_id or None,
            "source_url": source_url or None,
        },
        "submitted_source": submitted_source,
        "source_content_resolution": (
            submitted_source.get("resolution_status")
            if isinstance(submitted_source, dict) else "NOT_APPLICABLE"
        ),
        "official_source_count": len(official),
        "secondary_source_count": len(secondary),
        "official_sources": official,
        "secondary_sources": secondary,
        "source_errors": errors,
        "policy": {
            "official_primary_requires_direct_artifact": True,
            "primary_statement_reported_by_secondary_is_not_official_primary": True,
            "secondary_sources_require_corroboration": True,
            "multiple_independent_reports_require_distinct_origin_groups": True,
            "duplicate_content_fingerprints_are_not_independent": True,
            "community_sources_are_signals_only": True,
            "social_links_require_original_content_resolution": True,
            "model_prior_is_not_evidence": True,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--query-b64", required=True)
    parser.add_argument("--execution-id", required=True)
    parser.add_argument("--source-url-b64", default="")
    parser.add_argument("--telegram-input-id", default="")
    parser.add_argument("--classification", default="")
    parser.add_argument("--input-kind", default="")
    parser.add_argument("--memory-event-id", default="")
    parser.add_argument("--output", default="runtime/gta6-fresh-research/result.json")
    args = parser.parse_args()

    query = _decode_query(args.query_b64)
    if not query:
        raise ValueError("research query is required")
    result = collect(
        query,
        execution_id=args.execution_id,
        source_url=_decode_optional(args.source_url_b64),
        telegram_input_id=args.telegram_input_id,
        classification=args.classification,
        input_kind=args.input_kind,
        memory_event_id=args.memory_event_id,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"FRESH_RESEARCH_STATUS={result['status']}")
    print(f"OFFICIAL_SOURCE_COUNT={result['official_source_count']}")
    print(f"SECONDARY_SOURCE_COUNT={result['secondary_source_count']}")
    print(f"CHECKED_AT={result['checked_at']}")
    print(f"SOURCE_CONTENT_RESOLUTION={result['source_content_resolution']}")
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    sys.exit(main())
