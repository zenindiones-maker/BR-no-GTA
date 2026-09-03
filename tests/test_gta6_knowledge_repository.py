import pytest

from app.database.gta6_knowledge_repository import (
    get_gta6_knowledge,
    get_gta6_knowledge_by_research_item,
    insert_gta6_knowledge,
    list_gta6_knowledge,
)
from app.database.research_repository import insert_research_item
from app.database.schema import initialize_schema


def test_insert_and_get_gta6_knowledge():
    initialize_schema()

    research_item_id = insert_research_item(
        source_id=None,
        title="GTA 6 TESTE",
        content="Conteúdo de teste sobre GTA 6.",
        url="https://example.com/gta6",
    )

    knowledge_id = insert_gta6_knowledge(
        research_item_id=research_item_id,
        source_name="Test Source",
        fact_type="news",
        confidence="confirmed",
    )

    assert isinstance(knowledge_id, int)
    assert knowledge_id > 0

    knowledge = get_gta6_knowledge(knowledge_id)

    assert knowledge is not None
    assert knowledge["id"] == knowledge_id
    assert knowledge["research_item_id"] == research_item_id
    assert knowledge["fact_type"] == "news"
    assert knowledge["confidence"] == "confirmed"


def test_get_gta6_knowledge_by_research_item():
    initialize_schema()

    research_item_id = insert_research_item(
        source_id=None,
        title="GTA 6 RESEARCH",
        content="Pesquisa relacionada ao GTA 6.",
        url="https://example.com/research/gta6",
    )

    knowledge_id = insert_gta6_knowledge(
        research_item_id=research_item_id,
        source_name="Test Source",
        fact_type="feature",
        confidence="probable",
    )

    knowledge = get_gta6_knowledge_by_research_item(
        research_item_id
    )

    assert knowledge is not None
    assert knowledge["id"] == knowledge_id
    assert knowledge["research_item_id"] == research_item_id
    assert knowledge["fact_type"] == "feature"
    assert knowledge["confidence"] == "probable"


def test_list_gta6_knowledge():
    initialize_schema()

    first_research_id = insert_research_item(
        source_id=None,
        title="GTA 6 RESEARCH 1",
        content="Primeira pesquisa.",
        url="https://example.com/gta6/1",
    )

    second_research_id = insert_research_item(
        source_id=None,
        title="GTA 6 RESEARCH 2",
        content="Segunda pesquisa.",
        url="https://example.com/gta6/2",
    )

    first_id = insert_gta6_knowledge(
        research_item_id=first_research_id,
        source_name="Test Source",
        fact_type="news",
        confidence="confirmed",
    )

    second_id = insert_gta6_knowledge(
        research_item_id=second_research_id,
        source_name="Test Source",
        fact_type="gameplay",
        confidence="unconfirmed",
    )

    knowledge_items = list_gta6_knowledge()

    ids = {
        item["id"]
        for item in knowledge_items
    }

    assert first_id in ids
    assert second_id in ids


def test_get_nonexistent_gta6_knowledge():
    initialize_schema()

    assert get_gta6_knowledge(999999) is None
    assert get_gta6_knowledge_by_research_item(999999) is None


def test_insert_gta6_knowledge_with_valid_research_item():
    initialize_schema()

    research_item_id = insert_research_item(
        source_id=None,
        title="GTA 6 KNOWLEDGE TEST",
        content="Pesquisa válida para teste de conhecimento GTA 6.",
        url="https://example.com/gta6/knowledge",
    )

    knowledge_id = insert_gta6_knowledge(
        research_item_id=research_item_id,
        source_name="Test Source",
        fact_type="news",
        confidence="unconfirmed",
    )

    assert isinstance(knowledge_id, int)
    assert knowledge_id > 0

    knowledge = get_gta6_knowledge(knowledge_id)

    assert knowledge is not None
    assert knowledge["research_item_id"] == research_item_id

def test_duplicate_research_item_is_rejected():
    initialize_schema()

    research_item_id = insert_research_item(
        source_id=None,
        title="GTA 6 DUPLICATE",
        content="Pesquisa duplicada.",
        url="https://example.com/gta6/duplicate",
    )

    insert_gta6_knowledge(
        research_item_id=research_item_id,
        source_name="Test Source",
        fact_type="news",
        confidence="confirmed",
    )

    with pytest.raises(Exception):
        insert_gta6_knowledge(
            research_item_id=research_item_id,
        source_name="Test Source",
            fact_type="feature",
            confidence="probable",
        )


@pytest.mark.parametrize(
    "research_item_id",
    [0, -1, "1", None],
)
def test_invalid_research_item_id(research_item_id):
    initialize_schema()

    with pytest.raises(ValueError):
        insert_gta6_knowledge(
            research_item_id=research_item_id,
        source_name="Test Source",
            fact_type="news",
            confidence="confirmed",
        )


@pytest.mark.parametrize(
    "knowledge_id",
    [0, -1, "1", None],
)
def test_invalid_knowledge_id(knowledge_id):
    initialize_schema()

    with pytest.raises(ValueError):
        get_gta6_knowledge(knowledge_id)


@pytest.mark.parametrize(
    "research_item_id",
    [0, -1, "1", None],
)
def test_invalid_research_item_lookup_id(research_item_id):
    initialize_schema()

    with pytest.raises(ValueError):
        get_gta6_knowledge_by_research_item(
            research_item_id
        )


@pytest.mark.parametrize(
    "fact_type",
    ["", "   ", None],
)
def test_invalid_fact_type(fact_type):
    initialize_schema()

    with pytest.raises(ValueError):
        insert_gta6_knowledge(
            research_item_id=1,
        source_name="Test Source",
            fact_type=fact_type,
            confidence="confirmed",
        )


@pytest.mark.parametrize(
    "confidence",
    ["", "   ", None],
)
def test_invalid_confidence(confidence):
    initialize_schema()

    with pytest.raises(ValueError):
        insert_gta6_knowledge(
            research_item_id=1,
        source_name="Test Source",
            fact_type="news",
            confidence=confidence,
        )
