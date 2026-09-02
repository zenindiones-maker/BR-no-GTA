from app.integrations.gta6.source import GTA6SourceItem
import app.services.gta6_rockstar_monitor_ingestion as module


def test_collect_rockstar_newswire_items_parses_monitored_content(
    monkeypatch,
):
    html = """
    <script type="application/ld+json">
    {
      "@type": "NewsArticle",
      "headline": "GTA VI Update",
      "description": "Official update.",
      "url": "https://www.rockstargames.com/newswire/gta-vi-update"
    }
    </script>
    """

    monkeypatch.setattr(
        module,
        "monitor_gta6_page_persisted",
        lambda monitor, url: type(
            "Result",
            (),
            {"content": html},
        )(),
    )

    result = module.collect_rockstar_newswire_items()

    assert len(result) == 1
    assert isinstance(result[0], GTA6SourceItem)
    assert result[0].title == "GTA VI Update"
    assert result[0].source_name == "Rockstar Newswire"


def test_collect_rockstar_newswire_items_returns_empty_when_no_articles(
    monkeypatch,
):
    html = """
    <html>
      <body>No structured articles.</body>
    </html>
    """

    monkeypatch.setattr(
        module,
        "monitor_gta6_page_persisted",
        lambda monitor, url: type(
            "Result",
            (),
            {"content": html},
        )(),
    )

    assert module.collect_rockstar_newswire_items() == []


def test_ingest_rockstar_newswire_from_monitor_persists_items(
    monkeypatch,
):
    items = [
        GTA6SourceItem(
            title="GTA VI Update",
            summary="Official update.",
            url="https://www.rockstargames.com/newswire/gta-vi-update",
            source_name="Rockstar Newswire",
            fact_type="news",
            confidence="confirmed",
            published_at=None,
        )
    ]

    monkeypatch.setattr(
        module,
        "collect_rockstar_newswire_items",
        lambda timeout=15.0: items,
    )

    persisted = [
        {
            "research_item_id": 1,
            "knowledge_id": 1,
            "knowledge": None,
            "duplicate": False,
        }
    ]

    monkeypatch.setattr(
        module,
        "ingest_gta6_source_items",
        lambda received: persisted
        if received == items
        else [],
    )

    result = module.ingest_rockstar_newswire_from_monitor()

    assert result == persisted


def test_ingest_rockstar_newswire_from_monitor_returns_empty_without_items(
    monkeypatch,
):
    monkeypatch.setattr(
        module,
        "collect_rockstar_newswire_items",
        lambda timeout=15.0: [],
    )

    def fail_if_called(items):
        raise AssertionError(
            "ingest_gta6_source_items should not be called"
        )

    monkeypatch.setattr(
        module,
        "ingest_gta6_source_items",
        fail_if_called,
    )

    assert module.ingest_rockstar_newswire_from_monitor() == []
