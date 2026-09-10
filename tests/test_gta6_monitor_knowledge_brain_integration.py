from __future__ import annotations

from types import SimpleNamespace

from app.database.memory_claim_evidence_repository import (
    list_memory_claim_evidence_for_claim,
)
from app.database.memory_claim_repository import (
    get_memory_claim,
)
from app.database.memory_event_repository import (
    get_memory_event,
)
from app.database.memory_repository import (
    find_memory_by_source,
)
from app.services import gta6_monitor_run_service


class FakeMonitor:
    def __init__(self, page):
        self.page = page

    def fetch(self, url):
        return self.page


def test_monitor_run_persists_gta6_knowledge_brain(monkeypatch):
    page = SimpleNamespace(
        url="https://www.rockstargames.com/newswire",
        status_code=200,
        content="<html>GTA VI official update</html>",
    )

    item = SimpleNamespace(
        title="GTA VI Official Update",
        summary="Rockstar publicou uma atualização oficial sobre GTA VI.",
        source_name="Rockstar Newswire",
        url="https://www.rockstargames.com/newswire/test-brain",
        fact_type="news",
        confidence="confirmed",
        published_at=None,
    )

    monkeypatch.setattr(
        gta6_monitor_run_service,
        "GTA6ViceMonitor",
        lambda timeout: FakeMonitor(page),
    )
    monkeypatch.setattr(
        gta6_monitor_run_service,
        "get_gta6_monitor_state",
        lambda url: None,
    )
    monkeypatch.setattr(
        gta6_monitor_run_service,
        "parse_rockstar_newswire_html",
        lambda content: [item],
    )

    result = gta6_monitor_run_service.run_gta6_monitor_once(execution_id="test-execution")

    assert result.baseline is True
    assert result.items_found == 1
    assert result.items_ingested == 1
    assert result.items_duplicated == 0
    assert result.knowledge_ids

    knowledge = result.knowledge_ids[0]
    assert isinstance(knowledge, int)

    from app.database.gta6_knowledge_repository import (
        get_gta6_knowledge_by_source_url,
    )

    persisted_knowledge = get_gta6_knowledge_by_source_url(item.url)

    assert persisted_knowledge is not None
    assert persisted_knowledge["id"] == knowledge

    from app.database.research_repository import (
        get_research_item,
    )

    research_item = get_research_item(
        persisted_knowledge["research_item_id"],
    )

    assert research_item is not None

    from app.database.memory_event_repository import (
        list_memory_events_by_source,
    )

    events = list_memory_events_by_source(
        source_type="gta6_knowledge",
        source_id=str(knowledge),
    )

    assert len(events) == 1

    event = events[0]
    assert event["scope"] == "gta6"
    assert event["content"]
    assert event["provenance"] == "gta6_knowledge_ingestion"

    from app.database.memory_claim_repository import (
        list_memory_claims,
    )

    claims = list_memory_claims(scope="gta6")

    assert len(claims) == 1

    claim = claims[0]
    assert claim["claim"] == item.summary
    assert claim["claim_type"] == "observation"
    assert claim["status"] == "active"

    evidences = list_memory_claim_evidence_for_claim(
        claim["id"],
    )

    assert len(evidences) == 1
    assert evidences[0]["event_id"] == event["id"]
    assert evidences[0]["evidence_role"] == "supporting"

    memory = find_memory_by_source(
        source_type="memory_claim",
        source_id=str(claim["id"]),
    )

    assert len(memory) == 1
    assert memory[0]["memory_type"] == "semantic"
    assert memory[0]["scope"] == "gta6"
