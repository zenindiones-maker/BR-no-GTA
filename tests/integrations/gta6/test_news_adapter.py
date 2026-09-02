from app.integrations.gta6.news_adapter import (
    convert_news_item,
    convert_news_items,
)
from app.integrations.gta6.news_aggregator import (
    GTA6NewsFeedItem,
)


def test_convert_news_item():
    item = GTA6NewsFeedItem(
        title="Rockstar officially confirmed a new GTA VI feature",
        summary="Rockstar Games confirmed the feature.",
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
    assert result.confidence == "confirmed"
    assert result.published_at == item.published_at


def test_convert_news_item_classifies_rumor():
    item = GTA6NewsFeedItem(
        title="GTA 6 leak reveals new feature",
        summary="The information was shared by an insider.",
        url="https://example.com/gta6/leak",
        source_name="GameSpot",
    )

    result = convert_news_item(item)

    assert result.confidence == "rumor"


def test_convert_news_items():
    items = [
        GTA6NewsFeedItem(
            title="GTA VI News",
            summary="New information.",
            url="https://example.com/gta6/1",
            source_name="IGN",
        ),
        GTA6NewsFeedItem(
            title="GTA VI rumor",
            summary="Insider claims something new.",
            url="https://example.com/gta6/2",
            source_name="GameSpot",
        ),
    ]

    results = convert_news_items(items)

    assert len(results) == 2
    assert results[0].confidence == "unconfirmed"
    assert results[1].confidence == "rumor"
