from __future__ import annotations

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
