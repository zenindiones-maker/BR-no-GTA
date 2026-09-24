from __future__ import annotations

import re
from typing import Any

from app.integrations.gta6.rockstar_news import ROCKSTAR_NEWSWIRE_URL
from app.integrations.gta6.rockstar_newswire_adapter import (
    parse_rockstar_newswire_html,
)
from app.integrations.gta6.source import GTA6SourceItem
from app.integrations.gta6.vice_monitor import GTA6ViceMonitor
from app.services.gta6_ingestion import ingest_gta6_source_items
from app.services.gta6_monitor_persistence_service import (
    monitor_gta6_page_persisted,
)


def _meta_description(content: str) -> str:
    for pattern in (
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']',
        r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\'](.*?)["\']',
    ):
        match = re.search(pattern, content, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return " ".join(match.group(1).split())[:4000]
    return ""


def collect_rockstar_newswire_items(
    *,
    timeout: float = 15.0,
) -> list[GTA6SourceItem]:
    """Collect current official GTA VI Newswire stories with bounded enrichment."""

    monitor = GTA6ViceMonitor(
        timeout=timeout,
        user_agent=(
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "Chrome/126 Safari/537.36"
        ),
        max_retries=2,
    )

    result = monitor_gta6_page_persisted(
        monitor,
        ROCKSTAR_NEWSWIRE_URL,
    )
    items = parse_rockstar_newswire_html(result.content)

    enriched: list[GTA6SourceItem] = []
    for item in items[:8]:
        replacement = item
        try:
            page = monitor.fetch(item.url)
            direct_items = parse_rockstar_newswire_html(page.content)
            exact = next(
                (
                    candidate
                    for candidate in direct_items
                    if candidate.url.rstrip("/") == item.url.rstrip("/")
                ),
                None,
            )
            summary = (
                exact.summary
                if exact is not None and exact.summary.strip() != exact.title.strip()
                else _meta_description(page.content)
            )
            if summary and summary.strip() != item.title.strip():
                replacement = GTA6SourceItem(
                    title=(exact.title if exact is not None else item.title),
                    summary=summary,
                    url=item.url,
                    source_name="Rockstar Newswire",
                    fact_type="news",
                    confidence="confirmed",
                    published_at=(
                        exact.published_at
                        if exact is not None
                        else item.published_at
                    ),
                )
        except Exception:
            # The listing remains valid official evidence if a bounded detail
            # fetch transiently fails; do not convert that network failure into
            # invented article content.
            replacement = item
        enriched.append(replacement)

    return enriched


def ingest_rockstar_newswire_from_monitor(
    *,
    timeout: float = 15.0,
) -> list[dict[str, Any]]:
    """Captura o Newswire e persiste os artigos no Knowledge Core."""

    items = collect_rockstar_newswire_items(
        timeout=timeout,
    )

    if not items:
        return []

    return ingest_gta6_source_items(items)
