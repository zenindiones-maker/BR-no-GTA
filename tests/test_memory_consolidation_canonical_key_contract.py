"""SQLite claim reconstruction preserves the persisted canonical identity."""
import pytest

from app.services.memory_consolidation_persistence_service import (
    MemoryConsolidationPersistenceError,
    _build_memory_claim,
)


def _row():
    return {
        "canonical_key": "gta6:official fact",
        "claim": "Official Fact",
        "claim_type": "observation",
        "confidence": 9.0,
        "status": "active",
        "scope": "gta6",
        "valid_at": None,
        "invalid_at": None,
        "extraction_method": "gta6_knowledge",
    }


def test_reconstruct_preserves_exact_persisted_key():
    row = _row()
    reconstructed = _build_memory_claim(row)
    assert reconstructed.canonical_key == row["canonical_key"]
    assert reconstructed.claim == row["claim"]


@pytest.mark.parametrize("key", [None, "", "  ", 45])
def test_reconstruction_denies_missing_canonical_identity(key):
    row = _row()
    row["canonical_key"] = key
    with pytest.raises(MemoryConsolidationPersistenceError, match="CLAIM_CANONICAL_KEY"):
        _build_memory_claim(row)
