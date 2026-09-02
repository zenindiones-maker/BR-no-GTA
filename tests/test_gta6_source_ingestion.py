from app.integrations.gta6.source import GTA6SourceItem
from app.services.gta6_source_ingestion import (
    ingest_rockstar_newswire,
)


def test_ingest_rockstar_newswire_persists_items(monkeypatch):
    items = [
        GTA6SourceItem(
            title="GTA VI News",
            summary="Official GTA VI news.",
            url="https://example.com/gta6/news",
            source_name="Rockstar Newswire",
            fact_type="news",
            confidence="confirmed",
            published_at="2026-09-02T00:00:00+00:00",
        ),
        GTA6SourceItem(
            title="GTA VI Feature",
            summary="A GTA VI feature.",
            url="https://example.com/gta6/feature",
            source_name="Rockstar Newswire",
            fact_type="feature",
            confidence="confirmed",
            published_at="2026-09-02T00:01:00+00:00",
        ),
    ]

    def fake_fetch():
        return items

    monkeypatch.setattr(
        "app.services.gta6_source_ingestion."
        "fetch_rockstar_newswire",
        fake_fetch,
    )

    results = ingest_rockstar_newswire()

    assert len(results) == 2

    assert results[0]["knowledge"]["title"] == (
        "GTA VI News"
    )

    assert results[1]["knowledge"]["title"] == (
        "GTA VI Feature"
    )


def test_ingest_rockstar_newswire_returns_empty_when_source_empty(
    monkeypatch,
):
    def fake_fetch():
        return []

    monkeypatch.setattr(
        "app.services.gta6_source_ingestion."
        "fetch_rockstar_newswire",
        fake_fetch,
    )

    assert ingest_rockstar_newswire() == []
