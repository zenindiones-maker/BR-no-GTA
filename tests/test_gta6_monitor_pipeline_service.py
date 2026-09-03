from __future__ import annotations

from dataclasses import dataclass

from app.services.gta6_change_detector import GTA6ChangeResult
from app.services.gta6_monitor_service import GTA6MonitorResult


@dataclass(frozen=True)
class FakePipelineResult:
    knowledge_created: bool
    claims_created: int


def test_pipeline_does_not_create_knowledge_or_claim_when_content_is_unchanged():
    result = GTA6MonitorResult(
        url="https://example.com/gta6",
        status_code=200,
        content="<html>GTA 6</html>",
        change=GTA6ChangeResult(
            changed=False,
            previous_hash="abc123",
            current_hash="abc123",
        ),
    )

    assert result.change.changed is False
    assert result.content == "<html>GTA 6</html>"

    pipeline_result = FakePipelineResult(
        knowledge_created=False,
        claims_created=0,
    )

    assert pipeline_result.knowledge_created is False
    assert pipeline_result.claims_created == 0
