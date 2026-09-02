from app.integrations.gta6.news_aggregator import GTA6NewsFeedItem
from app.services.gta6_news_ingestion import ingest_gta6_news_items


def test_ingest_gta6_news_items(monkeypatch):
    captured = {}

    def fake_ingest(items):
        captured["items"] = items
        return [{"knowledge_id": 1}]

    monkeypatch.setattr(
        "app.services.gta6_news_ingestion.ingest_gta6_source_items",
        fake_ingest,
    )

    items = [
        GTA6NewsFeedItem(
            title="GTA VI News",
            summary="New information.",
            url="https://example.com/gta6",
            source_name="IGN",
        )
    ]

    result = ingest_gta6_news_items(items)

    assert result == [{"knowledge_id": 1}]
    assert len(captured["items"]) == 1
    assert captured["items"][0].title == "GTA VI News"
    assert captured["items"][0].fact_type == "news"
    assert captured["items"][0].confidence == "unconfirmed"


def test_ingest_gta6_news_items_empty(monkeypatch):
    def fake_ingest(items):
        raise AssertionError("não deveria chamar ingestão")

    monkeypatch.setattr(
        "app.services.gta6_news_ingestion.ingest_gta6_source_items",
        fake_ingest,
    )

    assert ingest_gta6_news_items([]) == []
