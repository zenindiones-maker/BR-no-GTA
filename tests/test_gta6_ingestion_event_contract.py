"""GTA6 ingestion must return observed event IDs, never fabricate them."""
from types import SimpleNamespace

import pytest

from app.services import gta6_ingestion


def source_item():
    return SimpleNamespace(
        title="GTA VI", summary="Official test summary",
        source_name="Rockstar", url="https://example.invalid/fixture",
        fact_type="news", confidence="confirmed", published_at=None,
    )


@pytest.mark.parametrize("existing", [None, {"id": 8, "research_item_id": 7}])
def test_new_and_duplicate_ingestion_pass_exact_event_id(monkeypatch, existing):
    monkeypatch.setattr(gta6_ingestion, "get_gta6_knowledge_by_source_url", lambda url: existing)
    monkeypatch.setattr(gta6_ingestion, "create_gta6_knowledge", lambda **kw: {
        "research_item_id": 7, "knowledge_id": 8, "knowledge": {"title": kw["title"]},
    })
    seen = []
    monkeypatch.setattr(gta6_ingestion, "ingest_gta6_knowledge_memory_event",
                        lambda row: seen.append(dict(row)) or 31)
    result = gta6_ingestion.ingest_gta6_source_item(source_item())
    assert result["memory_event_id"] == 31
    assert result["duplicate"] is (existing is not None)
    assert len(seen) == 1
    assert "memory_event_id" not in seen[0]


@pytest.mark.parametrize("invalid_id", [None, 0, -1, False, "31"])
def test_no_synthetic_event_id_on_bad_persistence_result(monkeypatch, invalid_id):
    monkeypatch.setattr(gta6_ingestion, "get_gta6_knowledge_by_source_url", lambda url: None)
    monkeypatch.setattr(gta6_ingestion, "create_gta6_knowledge", lambda **kw: {
        "research_item_id": 7, "knowledge_id": 8, "knowledge": {},
    })
    monkeypatch.setattr(gta6_ingestion, "ingest_gta6_knowledge_memory_event",
                        lambda row: invalid_id)
    with pytest.raises(RuntimeError, match="MEMORY_EVENT_ID_INVALID"):
        gta6_ingestion.ingest_gta6_source_item(source_item())
