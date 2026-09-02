import pytest

from app.database.gta6_knowledge_repository import (
    get_gta6_knowledge,
)
from app.database.research_repository import (
    get_research_item,
)
from app.database.schema import initialize_schema
from app.services.gta6_knowledge_service import (
    create_gta6_knowledge,
)


def test_create_gta6_knowledge_persists_research_and_knowledge():
    initialize_schema()

    result = create_gta6_knowledge(
        title="GTA 6 TESTE",
        summary="Informação de teste sobre GTA 6.",
        source_name="Example",
        source_url="https://example.com/gta6",
        fact_type="news",
        confidence="confirmed",
        published_at="2026-09-01T12:00:00+00:00",
    )

    assert result["research_item_id"] > 0
    assert result["knowledge_id"] > 0

    research = get_research_item(
        result["research_item_id"]
    )

    assert research is not None
    assert research["title"] == "GTA 6 TESTE"
    assert research["content"] == (
        "Informação de teste sobre GTA 6."
    )
    assert research["url"] == (
        "https://example.com/gta6"
    )

    knowledge = get_gta6_knowledge(
        result["knowledge_id"]
    )

    assert knowledge is not None
    assert knowledge["research_item_id"] == (
        result["research_item_id"]
    )
    assert knowledge["fact_type"] == "news"
    assert knowledge["confidence"] == "confirmed"


@pytest.mark.parametrize(
    "fact_type",
    [
        "invalid",
        "",
        None,
    ],
)
def test_invalid_fact_type(fact_type):
    initialize_schema()

    with pytest.raises(ValueError):
        create_gta6_knowledge(
            title="GTA 6 TESTE",
            summary="Teste.",
            source_name="Example",
            source_url="https://example.com",
            fact_type=fact_type,
            confidence="confirmed",
        )


@pytest.mark.parametrize(
    "confidence",
    [
        "invalid",
        "",
        None,
    ],
)
def test_invalid_confidence(confidence):
    initialize_schema()

    with pytest.raises(ValueError):
        create_gta6_knowledge(
            title="GTA 6 TESTE",
            summary="Teste.",
            source_name="Example",
            source_url="https://example.com",
            fact_type="news",
            confidence=confidence,
        )


def test_service_preserves_published_at():
    initialize_schema()

    published_at = "2026-09-01T15:30:00+00:00"

    result = create_gta6_knowledge(
        title="GTA 6 RELEASE",
        summary="Informação de lançamento.",
        source_name="Example",
        source_url="https://example.com/release",
        fact_type="release",
        confidence="confirmed",
        published_at=published_at,
    )

    assert result["knowledge"]["published_at"] == published_at

    research = get_research_item(
        result["research_item_id"]
    )

    assert research is not None
    assert research["published_at"] == published_at
