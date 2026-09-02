from app.database.gta6_knowledge_repository import (
    get_gta6_knowledge,
)
from app.database.research_repository import (
    get_research_item,
)
from app.services.gta6_ingestion import (
    ingest_gta6_source_item,
    ingest_gta6_source_items,
)
from app.integrations.gta6.source import GTA6SourceItem


def test_ingest_gta6_source_item_persists_knowledge():
    item = GTA6SourceItem(
        title="Grand Theft Auto VI Trailer",
        summary="Official GTA VI trailer information.",
        url=(
            "https://www.rockstargames.com/"
            "newswire/article/grand-theft-auto-vi-trailer"
        ),
        source_name="Rockstar Newswire",
        fact_type="news",
        confidence="confirmed",
        published_at="2026-09-02T00:00:00+00:00",
    )

    result = ingest_gta6_source_item(item)

    assert result["research_item_id"] > 0
    assert result["knowledge_id"] > 0

    research = get_research_item(
        result["research_item_id"]
    )

    knowledge = get_gta6_knowledge(
        result["knowledge_id"]
    )

    assert research is not None
    assert research["title"] == item.title
    assert research["content"] == item.summary
    assert research["url"] == item.url

    assert knowledge is not None
    assert knowledge["research_item_id"] == (
        result["research_item_id"]
    )
    assert knowledge["fact_type"] == "news"
    assert knowledge["confidence"] == "confirmed"


def test_ingest_gta6_source_items_persists_all_items():
    items = [
        GTA6SourceItem(
            title="GTA VI News 1",
            summary="News item one.",
            url="https://example.com/gta6/1",
            source_name="Test Source",
            fact_type="news",
            confidence="confirmed",
        ),
        GTA6SourceItem(
            title="GTA VI Feature",
            summary="Feature information.",
            url="https://example.com/gta6/2",
            source_name="Test Source",
            fact_type="feature",
            confidence="probable",
        ),
    ]

    results = ingest_gta6_source_items(items)

    assert len(results) == 2

    assert all(
        result["research_item_id"] > 0
        for result in results
    )

    assert all(
        result["knowledge_id"] > 0
        for result in results
    )

    assert results[0]["knowledge"]["title"] == (
        "GTA VI News 1"
    )

    assert results[1]["knowledge"]["title"] == (
        "GTA VI Feature"
    )


def test_ingest_gta6_source_item_skips_duplicate(monkeypatch):
    from app.integrations.gta6.source import GTA6SourceItem
    from app.services import gta6_ingestion

    monkeypatch.setattr(
        gta6_ingestion,
        "get_gta6_knowledge_by_source_url",
        lambda url: {
            "id": 99,
            "research_item_id": 55,
        },
    )

    def fail_create(**kwargs):
        raise AssertionError("duplicate should not be created")

    monkeypatch.setattr(
        gta6_ingestion,
        "create_gta6_knowledge",
        fail_create,
    )

    item = GTA6SourceItem(
        title="GTA 6",
        summary="Resumo",
        url="https://example.com/gta6",
        source_name="Example",
        fact_type="news",
        confidence="unconfirmed",
    )

    result = gta6_ingestion.ingest_gta6_source_item(item)

    assert result["knowledge_id"] == 99
    assert result["research_item_id"] == 55
    assert result["duplicate"] is True
