from app.integrations.gta6.news_aggregator import GTA6NewsFeedItem
from app.services.gta6_news_pipeline import run_gta6_news_pipeline


def test_run_gta6_news_pipeline(monkeypatch):
    items = [
        GTA6NewsFeedItem(
            title="GTA VI News",
            summary="New information.",
            url="https://example.com/gta6",
            source_name="IGN",
        )
    ]

    captured = {}

    def fake_fetch(*, timeout):
        captured["timeout"] = timeout
        return items

    def fake_ingest(received_items):
        captured["items"] = received_items
        return [{"knowledge_id": 1}]

    monkeypatch.setattr(
        "app.services.gta6_news_pipeline.fetch_gta6_news_feeds",
        fake_fetch,
    )
    monkeypatch.setattr(
        "app.services.gta6_news_pipeline.ingest_gta6_news_items",
        fake_ingest,
    )

    result = run_gta6_news_pipeline(timeout=9)

    assert result == [{"knowledge_id": 1}]
    assert captured["timeout"] == 9
    assert captured["items"] == items


def test_run_gta6_news_pipeline_empty(monkeypatch):
    monkeypatch.setattr(
        "app.services.gta6_news_pipeline.fetch_gta6_news_feeds",
        lambda *, timeout: [],
    )

    def fail_ingest(items):
        raise AssertionError("não deveria ingerir")

    monkeypatch.setattr(
        "app.services.gta6_news_pipeline.ingest_gta6_news_items",
        fail_ingest,
    )

    assert run_gta6_news_pipeline() == []
