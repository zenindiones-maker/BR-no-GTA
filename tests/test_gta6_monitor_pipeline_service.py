from __future__ import annotations
import pytest

from unittest.mock import Mock

from app.services.gta6_change_detector import GTA6ChangeResult
from app.services.gta6_knowledge import GTA6KnowledgeItem
from app.services.gta6_monitor_service import GTA6MonitorResult


def _monitor_result(*, changed: bool) -> GTA6MonitorResult:
    return GTA6MonitorResult(
        url="https://example.com/gta6",
        status_code=200,
        content="<html>GTA 6 atualizado</html>",
        change=GTA6ChangeResult(
            changed=changed,
            previous_hash=None if changed else "abc123",
            current_hash="def456" if changed else "abc123",
        ),
    )


def _knowledge() -> GTA6KnowledgeItem:
    return GTA6KnowledgeItem(
        title="GTA 6 update",
        summary="GTA 6 recebeu uma nova atualização observada.",
        source_name="Example",
        source_url="https://example.com/gta6",
        fact_type="update",
        confidence="confirmed",
        published_at="2026-09-03T12:00:00+00:00",
    )


def test_pipeline_does_not_create_knowledge_or_claim_when_content_is_unchanged(
    monkeypatch,
):
    from app.services import gta6_monitor_pipeline_service

    monitor_result = _monitor_result(changed=False)

    monitor = Mock()
    monitor.return_value = monitor_result

    knowledge_service = Mock()
    claim_extraction_service = Mock()
    memory_repository = Mock()

    monkeypatch.setattr(
        gta6_monitor_pipeline_service,
        "monitor_gta6_page",
        monitor,
    )
    monkeypatch.setattr(
        gta6_monitor_pipeline_service,
        "create_gta6_knowledge",
        knowledge_service,
    )
    monkeypatch.setattr(
        gta6_monitor_pipeline_service,
        "extract_gta6_claims",
        claim_extraction_service,
    )
    monkeypatch.setattr(
        gta6_monitor_pipeline_service,
        "insert_memory_claim",
        memory_repository,
    )

    result = gta6_monitor_pipeline_service.run_gta6_monitor_pipeline(
        url="https://example.com/gta6",
        monitor=Mock(),
        previous_hash="abc123",
        knowledge_factory=Mock(return_value=_knowledge()),
    )

    assert result.monitor.change.changed is False
    assert result.knowledge_created is False
    assert result.claims_created == 0

    knowledge_service.assert_not_called()
    claim_extraction_service.assert_not_called()
    memory_repository.assert_not_called()


def test_pipeline_changed_path_creates_knowledge_claim_and_memory_claim(
    monkeypatch,
):
    from app.services import gta6_monitor_pipeline_service

    monitor_result = _monitor_result(changed=True)
    knowledge = _knowledge()

    monitor = Mock()
    monitor.return_value = monitor_result

    knowledge_service = Mock(
        return_value={
            "research_item_id": 10,
            "knowledge_id": 20,
            "knowledge": knowledge.to_dict(),
        }
    )

    claim = Mock()
    claims = [claim]

    claim_extraction_service = Mock(
        return_value=claims
    )

    memory_repository = Mock(return_value=30)

    monkeypatch.setattr(
        gta6_monitor_pipeline_service,
        "monitor_gta6_page",
        monitor,
    )
    monkeypatch.setattr(
        gta6_monitor_pipeline_service,
        "create_gta6_knowledge",
        knowledge_service,
    )
    monkeypatch.setattr(
        gta6_monitor_pipeline_service,
        "extract_gta6_claims",
        claim_extraction_service,
    )
    monkeypatch.setattr(
        gta6_monitor_pipeline_service,
        "insert_memory_claim",
        memory_repository,
    )

    result = gta6_monitor_pipeline_service.run_gta6_monitor_pipeline(
        url="https://example.com/gta6",
        monitor=Mock(),
        previous_hash="abc123",
        knowledge_factory=Mock(return_value=knowledge),
    )

    assert result.monitor.change.changed is True
    assert result.knowledge_created is True
    assert result.knowledge_id == 20
    assert result.claims_created == 1
    assert result.memory_claim_ids == [30]

    knowledge_service.assert_called_once_with(
        title=knowledge.title,
        summary=knowledge.summary,
        source_name=knowledge.source_name,
        source_url=knowledge.source_url,
        fact_type=knowledge.fact_type,
        confidence=knowledge.confidence,
        published_at=knowledge.published_at,
    )

    claim_extraction_service.assert_called_once_with(knowledge)
    memory_repository.assert_called_once_with(claim)


def test_pipeline_first_observation_is_treated_as_change(monkeypatch):
    from app.services import gta6_monitor_pipeline_service

    monitor_result = _monitor_result(changed=True)

    monitor = Mock(return_value=monitor_result)
    knowledge = _knowledge()

    monkeypatch.setattr(
        gta6_monitor_pipeline_service,
        "monitor_gta6_page",
        monitor,
    )
    monkeypatch.setattr(
        gta6_monitor_pipeline_service,
        "create_gta6_knowledge",
        Mock(
            return_value={
                "research_item_id": 10,
                "knowledge_id": 20,
                "knowledge": knowledge.to_dict(),
            }
        ),
    )
    monkeypatch.setattr(
        gta6_monitor_pipeline_service,
        "extract_gta6_claims",
        Mock(return_value=[]),
    )
    monkeypatch.setattr(
        gta6_monitor_pipeline_service,
        "insert_memory_claim",
        Mock(),
    )

    result = gta6_monitor_pipeline_service.run_gta6_monitor_pipeline(
        url="https://example.com/gta6",
        monitor=Mock(),
        previous_hash=None,
        knowledge_factory=Mock(return_value=knowledge),
    )

    assert result.monitor.change.changed is True

def test_pipeline_persists_current_hash_after_monitoring(monkeypatch):
    from app.services import gta6_monitor_pipeline_service

    monitor_result = _monitor_result(changed=True)
    monitor = Mock(return_value=monitor_result)
    knowledge = _knowledge()

    persist_monitor_state = Mock()

    monkeypatch.setattr(
        gta6_monitor_pipeline_service,
        "monitor_gta6_page",
        monitor,
    )
    monkeypatch.setattr(
        gta6_monitor_pipeline_service,
        "save_gta6_monitor_state",
        persist_monitor_state,
    )
    monkeypatch.setattr(
        gta6_monitor_pipeline_service,
        "create_gta6_knowledge",
        Mock(
            return_value={
                "research_item_id": 10,
                "knowledge_id": 20,
                "knowledge": knowledge.to_dict(),
            }
        ),
    )
    monkeypatch.setattr(
        gta6_monitor_pipeline_service,
        "extract_gta6_claims",
        Mock(return_value=[]),
    )
    monkeypatch.setattr(
        gta6_monitor_pipeline_service,
        "insert_memory_claim",
        Mock(),
    )

    gta6_monitor_pipeline_service.run_gta6_monitor_pipeline(
        url="https://example.com/gta6",
        monitor=Mock(),
        previous_hash=None,
        knowledge_factory=Mock(return_value=knowledge),
    )

    persist_monitor_state.assert_called_once_with(
        "https://example.com/gta6",
        "def456",
    )

def test_pipeline_is_idempotent_for_same_content(monkeypatch):
    from app.services import gta6_monitor_pipeline_service

    monitor_result = _monitor_result(changed=False)
    monitor = Mock(return_value=monitor_result)

    knowledge_service = Mock()
    claim_extraction_service = Mock()
    memory_repository = Mock()
    persist_monitor_state = Mock()

    monkeypatch.setattr(
        gta6_monitor_pipeline_service,
        "monitor_gta6_page",
        monitor,
    )
    monkeypatch.setattr(
        gta6_monitor_pipeline_service,
        "save_gta6_monitor_state",
        persist_monitor_state,
    )
    monkeypatch.setattr(
        gta6_monitor_pipeline_service,
        "create_gta6_knowledge",
        knowledge_service,
    )
    monkeypatch.setattr(
        gta6_monitor_pipeline_service,
        "extract_gta6_claims",
        claim_extraction_service,
    )
    monkeypatch.setattr(
        gta6_monitor_pipeline_service,
        "insert_memory_claim",
        memory_repository,
    )

    result = gta6_monitor_pipeline_service.run_gta6_monitor_pipeline(
        url="https://example.com/gta6",
        monitor=Mock(),
        previous_hash="abc123",
        knowledge_factory=Mock(),
    )

    assert result.monitor.change.changed is False
    assert result.knowledge_created is False
    assert result.claims_created == 0
    assert result.memory_claim_ids == []

    persist_monitor_state.assert_called_once_with(
        "https://example.com/gta6",
        "abc123",
    )
    knowledge_service.assert_not_called()
    claim_extraction_service.assert_not_called()
    memory_repository.assert_not_called()

def test_pipeline_persists_monitor_result_hash_exactly(monkeypatch):
    from app.services import gta6_monitor_pipeline_service

    monitor_result = GTA6MonitorResult(
        url="https://example.com/gta6",
        status_code=200,
        content="<html>GTA 6 conteúdo novo</html>",
        change=GTA6ChangeResult(
            changed=True,
            previous_hash="old-hash",
            current_hash="unique-current-hash-789",
        ),
    )

    persist_monitor_state = Mock()

    monkeypatch.setattr(
        gta6_monitor_pipeline_service,
        "monitor_gta6_page",
        Mock(return_value=monitor_result),
    )
    monkeypatch.setattr(
        gta6_monitor_pipeline_service,
        "save_gta6_monitor_state",
        persist_monitor_state,
    )
    monkeypatch.setattr(
        gta6_monitor_pipeline_service,
        "create_gta6_knowledge",
        Mock(
            return_value={
                "research_item_id": 10,
                "knowledge_id": 20,
                "knowledge": _knowledge().to_dict(),
            }
        ),
    )
    monkeypatch.setattr(
        gta6_monitor_pipeline_service,
        "extract_gta6_claims",
        Mock(return_value=[]),
    )
    monkeypatch.setattr(
        gta6_monitor_pipeline_service,
        "insert_memory_claim",
        Mock(),
    )

    gta6_monitor_pipeline_service.run_gta6_monitor_pipeline(
        url="https://example.com/gta6",
        monitor=Mock(),
        previous_hash="old-hash",
        knowledge_factory=Mock(),
    )

    persist_monitor_state.assert_called_once_with(
        "https://example.com/gta6",
        "unique-current-hash-789",
    )

def test_pipeline_stops_when_knowledge_acquisition_fails(monkeypatch):
    from app.services import gta6_monitor_pipeline_service

    monitor_result = _monitor_result(changed=True)

    persist_monitor_state = Mock()
    knowledge_factory = Mock(
        side_effect=RuntimeError(
            "knowledge acquisition failed"
        )
    )
    knowledge_service = Mock()
    claim_extraction_service = Mock()
    memory_repository = Mock()

    monkeypatch.setattr(
        gta6_monitor_pipeline_service,
        "monitor_gta6_page",
        Mock(return_value=monitor_result),
    )
    monkeypatch.setattr(
        gta6_monitor_pipeline_service,
        "save_gta6_monitor_state",
        persist_monitor_state,
    )
    monkeypatch.setattr(
        gta6_monitor_pipeline_service,
        "create_gta6_knowledge",
        knowledge_service,
    )
    monkeypatch.setattr(
        gta6_monitor_pipeline_service,
        "extract_gta6_claims",
        claim_extraction_service,
    )
    monkeypatch.setattr(
        gta6_monitor_pipeline_service,
        "insert_memory_claim",
        memory_repository,
    )

    try:
        gta6_monitor_pipeline_service.run_gta6_monitor_pipeline(
            url="https://example.com/gta6",
            monitor=Mock(),
            previous_hash="old-hash",
            knowledge_factory=knowledge_factory,
        )
    except RuntimeError as exc:
        assert str(exc) == "knowledge acquisition failed"
    else:
        raise AssertionError(
            "pipeline should propagate knowledge acquisition failure"
        )

    persist_monitor_state.assert_not_called()
    knowledge_factory.assert_called_once_with(monitor_result)
    knowledge_service.assert_not_called()
    claim_extraction_service.assert_not_called()
    memory_repository.assert_not_called()

def test_pipeline_does_not_persist_hash_when_knowledge_acquisition_fails(
    monkeypatch,
):
    from app.services import gta6_monitor_pipeline_service

    monitor_result = _monitor_result(changed=True)

    persist_monitor_state = Mock()
    knowledge_factory = Mock(
        side_effect=RuntimeError(
            "knowledge acquisition failed"
        )
    )

    monkeypatch.setattr(
        gta6_monitor_pipeline_service,
        "monitor_gta6_page",
        Mock(return_value=monitor_result),
    )
    monkeypatch.setattr(
        gta6_monitor_pipeline_service,
        "save_gta6_monitor_state",
        persist_monitor_state,
    )

    with pytest.raises(
        RuntimeError,
        match="knowledge acquisition failed",
    ):
        gta6_monitor_pipeline_service.run_gta6_monitor_pipeline(
            url="https://example.com/gta6",
            monitor=Mock(),
            previous_hash="old-hash",
            knowledge_factory=knowledge_factory,
        )

    persist_monitor_state.assert_not_called()


def test_pipeline_persists_monitor_state_after_successful_processing(
    monkeypatch,
):
    from app.services import gta6_monitor_pipeline_service

    monitor_result = _monitor_result(changed=True)

    persist_monitor_state = Mock()
    create_knowledge = Mock(
        return_value={
            "research_item_id": 10,
            "knowledge_id": 20,
            "knowledge": _knowledge().to_dict(),
        }
    )
    extract_claims = Mock(return_value=[])
    insert_claim = Mock()

    monkeypatch.setattr(
        gta6_monitor_pipeline_service,
        "monitor_gta6_page",
        Mock(return_value=monitor_result),
    )
    monkeypatch.setattr(
        gta6_monitor_pipeline_service,
        "save_gta6_monitor_state",
        persist_monitor_state,
    )
    monkeypatch.setattr(
        gta6_monitor_pipeline_service,
        "create_gta6_knowledge",
        create_knowledge,
    )
    monkeypatch.setattr(
        gta6_monitor_pipeline_service,
        "extract_gta6_claims",
        extract_claims,
    )
    monkeypatch.setattr(
        gta6_monitor_pipeline_service,
        "insert_memory_claim",
        insert_claim,
    )

    result = gta6_monitor_pipeline_service.run_gta6_monitor_pipeline(
        url="https://example.com/gta6",
        monitor=Mock(),
        previous_hash="old-hash",
        knowledge_factory=Mock(return_value=_knowledge()),
    )

    assert result.knowledge_created is True
    assert result.knowledge_id == 20
    assert result.claims_created == 0
    assert result.memory_claim_ids == []

    create_knowledge.assert_called_once()
    extract_claims.assert_called_once()
    insert_claim.assert_not_called()

    persist_monitor_state.assert_called_once_with(
        "https://example.com/gta6",
        "def456",
    )


def test_pipeline_does_not_persist_hash_when_claim_extraction_fails(
    monkeypatch,
):
    from app.services import gta6_monitor_pipeline_service

    monitor_result = _monitor_result(changed=True)

    persist_monitor_state = Mock()
    create_knowledge = Mock(
        return_value={
            "research_item_id": 10,
            "knowledge_id": 20,
            "knowledge": _knowledge().to_dict(),
        }
    )
    extract_claims = Mock(
        side_effect=RuntimeError(
            "claim extraction failed"
        )
    )
    insert_claim = Mock()

    monkeypatch.setattr(
        gta6_monitor_pipeline_service,
        "monitor_gta6_page",
        Mock(return_value=monitor_result),
    )
    monkeypatch.setattr(
        gta6_monitor_pipeline_service,
        "save_gta6_monitor_state",
        persist_monitor_state,
    )
    monkeypatch.setattr(
        gta6_monitor_pipeline_service,
        "create_gta6_knowledge",
        create_knowledge,
    )
    monkeypatch.setattr(
        gta6_monitor_pipeline_service,
        "extract_gta6_claims",
        extract_claims,
    )
    monkeypatch.setattr(
        gta6_monitor_pipeline_service,
        "insert_memory_claim",
        insert_claim,
    )

    with pytest.raises(
        RuntimeError,
        match="claim extraction failed",
    ):
        gta6_monitor_pipeline_service.run_gta6_monitor_pipeline(
            url="https://example.com/gta6",
            monitor=Mock(),
            previous_hash="old-hash",
            knowledge_factory=Mock(return_value=_knowledge()),
        )

    create_knowledge.assert_called_once()
    extract_claims.assert_called_once()
    insert_claim.assert_not_called()
    persist_monitor_state.assert_not_called()

def test_pipeline_propagates_monitor_state_persistence_failure(
    monkeypatch,
):
    from app.services import gta6_monitor_pipeline_service

    monitor_result = _monitor_result(changed=True)

    create_knowledge = Mock(
        return_value={
            "research_item_id": 10,
            "knowledge_id": 20,
            "knowledge": _knowledge().to_dict(),
        }
    )
    extract_claims = Mock(return_value=[])
    insert_claim = Mock()
    persist_monitor_state = Mock(
        side_effect=RuntimeError(
            "monitor state persistence failed"
        )
    )

    monkeypatch.setattr(
        gta6_monitor_pipeline_service,
        "monitor_gta6_page",
        Mock(return_value=monitor_result),
    )
    monkeypatch.setattr(
        gta6_monitor_pipeline_service,
        "create_gta6_knowledge",
        create_knowledge,
    )
    monkeypatch.setattr(
        gta6_monitor_pipeline_service,
        "extract_gta6_claims",
        extract_claims,
    )
    monkeypatch.setattr(
        gta6_monitor_pipeline_service,
        "insert_memory_claim",
        insert_claim,
    )
    monkeypatch.setattr(
        gta6_monitor_pipeline_service,
        "save_gta6_monitor_state",
        persist_monitor_state,
    )

    with pytest.raises(
        RuntimeError,
        match="monitor state persistence failed",
    ):
        gta6_monitor_pipeline_service.run_gta6_monitor_pipeline(
            url="https://example.com/gta6",
            monitor=Mock(),
            previous_hash="old-hash",
            knowledge_factory=Mock(return_value=_knowledge()),
        )

    create_knowledge.assert_called_once()
    extract_claims.assert_called_once()
    insert_claim.assert_not_called()
    persist_monitor_state.assert_called_once_with(
        "https://example.com/gta6",
        "def456",
    )
