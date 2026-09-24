from __future__ import annotations

from html.parser import HTMLParser
import json
import re
from urllib.parse import urljoin

from app.integrations.gta6.rockstar_newswire_graph import (
    RockstarNewswireArticle,
)
from app.integrations.gta6.source import GTA6SourceItem


def convert_rockstar_article(
    article: RockstarNewswireArticle,
) -> GTA6SourceItem:
    if not isinstance(article, RockstarNewswireArticle):
        raise ValueError("article must be a RockstarNewswireArticle")

    return GTA6SourceItem(
        title=article.title,
        summary=article.title,
        url=article.url,
        source_name="Rockstar Newswire",
        fact_type="news",
        confidence="confirmed",
        published_at=article.created_at,
    )


def convert_rockstar_articles(
    articles: list[RockstarNewswireArticle],
) -> list[GTA6SourceItem]:
    if not isinstance(articles, list):
        raise ValueError("articles must be a list")

    return [
        convert_rockstar_article(article)
        for article in articles
    ]


class _NewswireAnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._href: str | None = None
        self._text: list[str] = []
        self.links: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.casefold() != "a":
            return
        href = dict(attrs).get("href")
        if isinstance(href, str) and href.strip():
            self._href = href.strip()
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() != "a" or self._href is None:
            return
        title = " ".join(" ".join(self._text).split())
        if title:
            self.links.append((title, self._href))
        self._href = None
        self._text = []


_GTA6_TITLE_MARKERS = (
    "grand theft auto vi",
    "grand theft auto 6",
    "gta vi",
    "gta 6",
    "vice city",
    "leonida",
    "goodtime state",
    "jason and lucia",
)


def _fallback_article_links(content: str) -> list[GTA6SourceItem]:
    parser = _NewswireAnchorParser()
    parser.feed(content)
    items: list[GTA6SourceItem] = []
    for title, href in parser.links:
        url = urljoin("https://www.rockstargames.com", href)
        if "/newswire/article/" not in url.casefold():
            continue
        normalized_title = title.casefold()
        if not any(marker in normalized_title for marker in _GTA6_TITLE_MARKERS):
            continue
        items.append(
            GTA6SourceItem(
                title=title,
                summary=title,
                url=url,
                source_name="Rockstar Newswire",
                fact_type="news",
                confidence="confirmed",
            )
        )
    return items


def parse_rockstar_newswire_html(
    content: str,
) -> list[GTA6SourceItem]:
    """Extrai artigos estruturados do HTML do Rockstar Newswire."""

    if not isinstance(content, str):
        raise ValueError("content must be a string")

    if not content.strip():
        return []

    items: list[GTA6SourceItem] = []

    for match in re.finditer(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        content,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        raw_json = match.group(1).strip()

        try:
            payload = json.loads(raw_json)
        except json.JSONDecodeError:
            continue

        candidates = payload if isinstance(payload, list) else [payload]

        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue

            item = _convert_json_ld_article(candidate)

            if item is not None:
                items.append(item)

    if not items:
        items.extend(_fallback_article_links(content))

    return _deduplicate_source_items(items)


def _convert_json_ld_article(
    payload: dict,
) -> GTA6SourceItem | None:
    item_type = payload.get("@type")

    if isinstance(item_type, list):
        is_article = any(
            value in {"Article", "NewsArticle"}
            for value in item_type
        )
    else:
        is_article = item_type in {"Article", "NewsArticle"}

    if not is_article:
        return None

    title = payload.get("headline") or payload.get("name")
    url = payload.get("url")

    if not isinstance(title, str) or not title.strip():
        return None

    if not isinstance(url, str) or not url.strip():
        return None

    summary = payload.get("description") or title
    published_at = payload.get("datePublished")

    if not isinstance(summary, str):
        summary = title

    if published_at is not None and not isinstance(published_at, str):
        published_at = None

    return GTA6SourceItem(
        title=title.strip(),
        summary=summary.strip(),
        url=url.strip(),
        source_name="Rockstar Newswire",
        fact_type="news",
        confidence="confirmed",
        published_at=published_at,
    )


def _deduplicate_source_items(
    items: list[GTA6SourceItem],
) -> list[GTA6SourceItem]:
    seen_urls: set[str] = set()
    result: list[GTA6SourceItem] = []

    for item in items:
        if item.url in seen_urls:
            continue

        seen_urls.add(item.url)
        result.append(item)

    return result
