from __future__ import annotations

import argparse
import base64
import html
import json
import re
import sys
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


def _fetch_text(url: str, *, timeout: int = 25) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9,pt-BR;q=0.8",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8", errors="replace")
    raw = re.sub(r"<script\b[^>]*>.*?</script>", " ", raw, flags=re.I | re.S)
    raw = re.sub(r"<style\b[^>]*>.*?</style>", " ", raw, flags=re.I | re.S)
    raw = re.sub(r"<[^>]+>", " ", raw)
    return " ".join(html.unescape(raw).split())


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


def collect(query: str, *, execution_id: str) -> dict[str, Any]:
    checked_at = datetime.now(timezone.utc).isoformat()
    official: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    for source_name, url in OFFICIAL_SOURCES:
        try:
            text = _fetch_text(url)
        except Exception as exc:
            errors.append({"source": source_name, "url": url, "error": type(exc).__name__})
            continue
        official.append(
            {
                "source_name": source_name,
                "url": url,
                "authority": "official",
                "checked_at": checked_at,
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
        payload["authority"] = "community" if "reddit" in item.source_name.casefold() else "secondary"
        secondary.append(payload)

    status = "PASS" if official else "FAIL"
    return {
        "status": status,
        "execution_id": execution_id,
        "query": query,
        "checked_at": checked_at,
        "official_source_count": len(official),
        "secondary_source_count": len(secondary),
        "official_sources": official,
        "secondary_sources": secondary,
        "source_errors": errors,
        "policy": {
            "official_sources_are_authoritative": True,
            "secondary_sources_require_corroboration": True,
            "community_sources_are_signals_only": True,
            "model_prior_is_not_evidence": True,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--query-b64", required=True)
    parser.add_argument("--execution-id", required=True)
    parser.add_argument("--output", default="runtime/gta6-fresh-research/result.json")
    args = parser.parse_args()

    query = _decode_query(args.query_b64)
    if not query:
        raise ValueError("research query is required")
    result = collect(query, execution_id=args.execution_id)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"FRESH_RESEARCH_STATUS={result['status']}")
    print(f"OFFICIAL_SOURCE_COUNT={result['official_source_count']}")
    print(f"SECONDARY_SOURCE_COUNT={result['secondary_source_count']}")
    print(f"CHECKED_AT={result['checked_at']}")
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    sys.exit(main())
