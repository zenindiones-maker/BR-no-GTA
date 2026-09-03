from __future__ import annotations

import pytest

from app.services.gta6_claim_extraction_service import (
    extract_gta6_claims,
)
from app.services.gta6_knowledge_service import (
    create_gta6_knowledge_item,
)
from app.services.memory_claim_service import (
    MemoryClaim,
)


def make_knowledge(
    *,
    confidence: str = "unconfirmed",
    published_at: str | None = "2026-09-03T00:00:00",
):
    return create_gta6_knowledge_item(
        title="GTA 6 — teste de extração",
        summary="GTA 6 apresenta um comportamento descrito nesta evidência.",
        source_name="test_source",
        source_url="https://example.com/gta6-test",
        fact_type="gameplay",
        confidence=confidence,
        published_at=published_at,
    )


def test_extract_gta6_claims_returns_memory_claim():
    knowledge = make_knowledge()

    claims = extract_gta6_claims(knowledge)

    assert isinstance(claims, list)
    assert len(claims) == 1
    assert isinstance(claims[0], MemoryClaim)


def test_extract_gta6_claims_maps_knowledge_to_claim():
    knowledge = make_knowledge()

    claim = extract_gta6_claims(knowledge)[0]

    assert claim.claim == knowledge.summary
    assert claim.claim_type == "observation"
    assert claim.status == "active"
    assert claim.scope == "gta6"
    assert claim.extraction_method == "gta6_knowledge"
    assert claim.valid_at == knowledge.published_at
    assert claim.invalid_at is None


@pytest.mark.parametrize(
    ("knowledge_confidence", "expected_claim_confidence"),
    [
        ("confirmed", 9.0),
        ("probable", 7.5),
        ("unconfirmed", 5.0),
        ("rumor", 3.0),
    ],
)
def test_extract_gta6_claims_maps_confidence(
    knowledge_confidence: str,
    expected_claim_confidence: float,
):
    knowledge = make_knowledge(
        confidence=knowledge_confidence,
    )

    claim = extract_gta6_claims(knowledge)[0]

    assert claim.confidence == expected_claim_confidence


def test_extract_gta6_claims_preserves_published_at():
    knowledge = make_knowledge(
        published_at="2026-09-03T12:34:56",
    )

    claim = extract_gta6_claims(knowledge)[0]

    assert claim.valid_at == "2026-09-03T12:34:56"


def test_extract_gta6_claims_allows_missing_published_at():
    knowledge = make_knowledge(
        published_at=None,
    )

    claim = extract_gta6_claims(knowledge)[0]

    assert claim.valid_at is None


def test_extract_gta6_claims_rejects_invalid_input():
    with pytest.raises(TypeError):
        extract_gta6_claims("not a knowledge item")  # type: ignore[arg-type]
