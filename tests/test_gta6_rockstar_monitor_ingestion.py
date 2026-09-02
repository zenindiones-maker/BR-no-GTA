from app.integrations.gta6.source import GTA6SourceItem
import app.services.gta6_rockstar_monitor_ingestion as module


def test_collect_rockstar_newswire_items_parses_monitored_content(monkeypatch):
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
