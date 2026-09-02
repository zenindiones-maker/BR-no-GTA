from app.integrations.gta6.news_adapter import (
    convert_news_item,
    convert_news_items,
)
from app.integrations.gta6.news_aggregator import (
    GTA6NewsFeedItem,
)


def test_convert_news_item():
    item = GTA6NewsFeedItem(
        title="GTA VI News",
        summary="New GTA VI information.",
        url="https://example.com/gta6",
        source_name="IGN",
        published_at="2026-09-02T00:00:00Z",
    )

    result = convert_news_item(item)

    assert result.title == item.title
    assert result.summary == item.summary
    assert result.url == item.url
    assert result.source_name == "IGN"
    assert result.fact_type == "news"
    assert result.confidence == "unconfirmed"
    assert result.published_at == item.published_at


def test_convert_news_items():
    items = [
        GTA6NewsFeedItem(
            title="News 1",
            summary="Summary 1",
            url="https://example.com/1",
            source_name="IGN",
        ),
        GTA6NewsFeedItem(
            title="News 2",
            summary="Summary 2",
            url="https://example.com/2",
            source_name="GameSpot",
        ),
    ]

    results = convert_news_items(items)

    assert len(results) == 2
    assert results[0].source_name == "IGN"
    assert results[1].source_name == "GameSpot"
    assert all(
        item.fact_type == "news"
        for item in results
    )
