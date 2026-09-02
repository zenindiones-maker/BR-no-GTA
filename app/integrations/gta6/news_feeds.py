from urllib.request import Request, urlopen

from app.integrations.gta6.news_aggregator import (
    GTA6NewsFeedItem,
    parse_rss_feed,
)

GTA6_NEWS_FEEDS = {
    "IGN": "https://feeds.feedburner.com/ignfeeds",
    "IGN GTA 6": "https://www.ign.com/rss/articles/feed?tags=grand-theft-auto-vi",
    "GameSpot": "https://www.gamespot.com/feeds/news/",
    "Reddit GTA6": "https://www.reddit.com/r/GTA6/top/.rss?t=day",
}


def fetch_news_feed(
    *,
    source_name: str,
    url: str,
    timeout: int = 20,
) -> list[GTA6NewsFeedItem]:
    """Busca um RSS e retorna itens normalizados."""
    request = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 "
                "(Linux; Android 10) "
                "AppleWebKit/537.36 "
                "Chrome/120 Safari/537.36"
            )
        },
    )

    try:
        with urlopen(request, timeout=timeout) as response:
            xml = response.read().decode(
                "utf-8",
                errors="replace",
            )
    except Exception as exc:
        raise RuntimeError(
            f"failed to fetch news feed: {source_name}"
        ) from exc

    return parse_rss_feed(
        xml,
        source_name=source_name,
    )


def fetch_gta6_news_feeds(
    *,
    timeout: int = 20,
) -> list[GTA6NewsFeedItem]:
    """Busca todas as fontes configuradas."""
    items: list[GTA6NewsFeedItem] = []

    for source_name, url in GTA6_NEWS_FEEDS.items():
        items.extend(
            fetch_news_feed(
                source_name=source_name,
                url=url,
                timeout=timeout,
            )
        )

    return items
