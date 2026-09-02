import pytest

from app.services.gta6_knowledge import (
    GTA6KnowledgeItem,
    create_gta6_knowledge_item,
    create_gta6_research_item,
)


def test_create_gta6_knowledge_item():
    item = create_gta6_knowledge_item(
        title="GTA 6 recebe nova informação",
        summary="Informação de teste.",
        source_name="Test Source",
        source_url="https://example.com/gta6",
        fact_type="news",
        confidence="confirmed",
        published_at="2026-09-01T12:00:00+00:00",
    )

    assert isinstance(item, GTA6KnowledgeItem)
    assert item.title == "GTA 6 recebe nova informação"
    assert item.fact_type == "news"
    assert item.confidence == "confirmed"


def test_knowledge_item_serialization():
    item = create_gta6_knowledge_item(
        title="Gameplay",
        summary="Novo detalhe.",
        source_name="Test Source",
        source_url="https://example.com/gameplay",
        fact_type="gameplay",
        confidence="probable",
    )

    data = item.to_dict()

    assert data["title"] == "Gameplay"
    assert data["fact_type"] == "gameplay"
    assert data["confidence"] == "probable"


def test_invalid_fact_type_is_rejected():
    with pytest.raises(ValueError, match="invalid GTA6 fact type"):
        create_gta6_knowledge_item(
            title="Teste",
            summary="Teste",
            source_name="Test",
            source_url="https://example.com",
            fact_type="invalid",
            confidence="confirmed",
        )


def test_invalid_confidence_is_rejected():
    with pytest.raises(ValueError, match="invalid GTA6 confidence"):
        create_gta6_knowledge_item(
            title="Teste",
            summary="Teste",
            source_name="Test",
            source_url="https://example.com",
            fact_type="news",
            confidence="invalid",
        )


def test_research_item_gets_timestamp():
    item = create_gta6_research_item(
        title="Pesquisa GTA 6",
        summary="Resultado de pesquisa.",
        source_name="Test",
        source_url="https://example.com",
    )

    assert item.published_at is not None
