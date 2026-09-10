import pytest

from app.services.memory_claim_service import (
    MemoryClaimError,
    create_memory_claim,
)


def test_create_memory_claim_normalizes_core_fields():
    claim = create_memory_claim(
        claim="  GTA 6 terá um sistema policial mais dinâmico.  ",
        claim_type="observation",
        confidence=7.5,
        status="active",
        scope="  gta6  ",
        valid_at="2026-09-07T05:00:00",
        invalid_at=None,
        extraction_method="  gta6_knowledge  ",
    )

    assert claim.claim == "GTA 6 terá um sistema policial mais dinâmico."
    assert claim.scope == "gta6"
    assert claim.extraction_method == "gta6_knowledge"
    assert claim.confidence == 7.5
    assert claim.status == "active"


def test_create_memory_claim_rejects_invalid_claim_type():
    with pytest.raises(MemoryClaimError):
        create_memory_claim(
            claim="GTA 6 terá determinado recurso.",
            claim_type="invalid",
            confidence=7.5,
            status="active",
            scope="gta6",
            valid_at=None,
            invalid_at=None,
            extraction_method="test",
        )


def test_create_memory_claim_rejects_invalid_temporal_range():
    with pytest.raises(MemoryClaimError):
        create_memory_claim(
            claim="GTA 6 terá determinado recurso.",
            claim_type="observation",
            confidence=7.5,
            status="active",
            scope="gta6",
            valid_at="2026-09-08T00:00:00",
            invalid_at="2026-09-07T00:00:00",
            extraction_method="test",
        )


def test_create_memory_claim_rejects_empty_claim():
    with pytest.raises(MemoryClaimError):
        create_memory_claim(
            claim="   ",
            claim_type="observation",
            confidence=7.5,
            status="active",
            scope="gta6",
            valid_at=None,
            invalid_at=None,
            extraction_method="test",
        )


def test_memory_claim_has_canonical_identity():
    claim = create_memory_claim(
        claim="  GTA 6 terá um sistema policial mais dinâmico.  ",
        claim_type="observation",
        confidence=7.5,
        status="active",
        scope="gta6",
        valid_at=None,
        invalid_at=None,
        extraction_method="test",
    )

    assert claim.canonical_key
    assert claim.canonical_key == "gta6:gta 6 terá um sistema policial mais dinâmico."

def test_memory_claim_canonical_identity_is_stable_for_case_and_whitespace():
    claim_a = create_memory_claim(
        claim="GTA 6 terá um sistema policial mais dinâmico.",
        claim_type="observation",
        confidence=7.5,
        status="active",
        scope="gta6",
        valid_at=None,
        invalid_at=None,
        extraction_method="test",
    )

    claim_b = create_memory_claim(
        claim="  gta 6 terá um sistema policial mais dinâmico.  ",
        claim_type="observation",
        confidence=7.5,
        status="active",
        scope="GTA6",
        valid_at=None,
        invalid_at=None,
        extraction_method="test",
    )

    assert claim_a.canonical_key == claim_b.canonical_key

def test_memory_claim_serialization_preserves_canonical_key():
    from app.services.memory_claim_service import claim_to_dict

    claim = create_memory_claim(
        claim="GTA 6 terá um sistema policial mais dinâmico.",
        claim_type="observation",
        confidence=7.5,
        status="active",
        scope="gta6",
        valid_at=None,
        invalid_at=None,
        extraction_method="test",
    )

    data = claim_to_dict(claim)

    assert data["canonical_key"] == claim.canonical_key
