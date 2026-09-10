from app.database.memory_claim_evidence_repository import (
    insert_memory_claim_evidence,
)
from app.database.memory_claim_repository import (
    insert_memory_claim,
)
from app.database.memory_event_repository import (
    insert_memory_event,
)
from app.database.memory_repository import (
    find_memory_by_source,
)
from app.services.memory_claim_evidence_service import (
    create_memory_claim_evidence,
)
from app.services.memory_claim_service import (
    create_memory_claim,
)
from app.services.memory_consolidation_persistence_service import (
    consolidate_and_persist_claim,
)
from app.services.memory_event_service import (
    create_memory_event,
)


def test_consolidate_and_persist_claim():
    event = create_memory_event(
        event_type="gta6_knowledge_ingested",
        source_type="rockstar_newswire",
        source_id="test-1",
        content="Rockstar publicou uma nova informação sobre GTA VI.",
        scope="gta6",
        provenance="Rockstar Newswire",
    )
    event_id = insert_memory_event(event)

    claim = create_memory_claim(
        claim="Rockstar publicou uma nova informação sobre GTA VI.",
        claim_type="observation",
        confidence=9.0,
        status="active",
        scope="gta6",
        extraction_method="test",
    )
    claim_id = insert_memory_claim(claim)

    evidence = create_memory_claim_evidence(
        claim_id=claim_id,
        event_id=event_id,
        evidence_role="supporting",
        weight=1.0,
    )
    insert_memory_claim_evidence(evidence)

    result = consolidate_and_persist_claim(claim_id)

    assert result["status"] == "consolidated"
    assert result["claim_id"] == claim_id
    assert isinstance(result["memory_id"], int)
    assert result["memory"]["memory_type"] == "semantic"
    assert result["memory"]["source_type"] == "memory_claim"
    assert result["memory"]["source_id"] == str(claim_id)

    persisted = find_memory_by_source(
        source_type="memory_claim",
        source_id=str(claim_id),
    )

    assert len(persisted) == 1
    assert persisted[0]["id"] == result["memory_id"]


def test_consolidate_and_persist_claim_is_idempotent():
    event = create_memory_event(
        event_type="gta6_knowledge_ingested",
        source_type="rockstar_newswire",
        source_id="test-idempotent",
        content="Evidência para teste de idempotência.",
        scope="gta6",
        provenance="Rockstar Newswire",
    )
    event_id = insert_memory_event(event)

    claim = create_memory_claim(
        claim="Evidência para teste de idempotência.",
        claim_type="observation",
        confidence=8.0,
        status="active",
        scope="gta6",
        extraction_method="test",
    )
    claim_id = insert_memory_claim(claim)

    evidence = create_memory_claim_evidence(
        claim_id=claim_id,
        event_id=event_id,
        evidence_role="supporting",
        weight=1.0,
    )
    insert_memory_claim_evidence(evidence)

    first = consolidate_and_persist_claim(claim_id)
    second = consolidate_and_persist_claim(claim_id)

    assert first["status"] == "consolidated"
    assert second["status"] == "already_consolidated"
    assert second["memory_id"] == first["memory_id"]
