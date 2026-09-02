from app.integrations.gta6.news_aggregator import (
    GTA6NewsFeedItem,
)
from app.integrations.gta6.source import (
    GTA6SourceItem,
)
from app.services.gta6_confidence_classifier import (
    classify_gta6_confidence,
)


def convert_news_item(
    item: GTA6NewsFeedItem,
) -> GTA6SourceItem:
    """Converte item agregado para o contrato GTA6SourceItem."""

    confidence = classify_gta6_confidence(
        item.title,
        item.summary,
    )

    return GTA6SourceItem(
        title=item.title,
        summary=item.summary,
        url=item.url,
        source_name=item.source_name,
        fact_type="news",
        confidence=confidence,
        published_at=item.published_at,
    )


def convert_news_items(
    items: list[GTA6NewsFeedItem],
) -> list[GTA6SourceItem]:
    """Converte vários itens agregados."""

    return [
        convert_news_item(item)
        for item in items
    ]
