from __future__ import annotations

from types import SimpleNamespace

from app.services import agent_office_harness_service as harness
from app.services.agent_office.development_checkpoint_hook_service import (
    HarnessDevelopmentCheckpointHook,
)
from app.services.agent_office.munder_adapter import MunderAdapter


def test_harness_injects_checkpoint_hook_into_official_agent_office_path(monkeypatch, tmp_path):
    seen = {}

    class FakeService:
        def __init__(self, repository_root, *, adapter=None):
            seen["root"] = repository_root
            seen["adapter"] = adapter

        def execute(self, spec, tasks):
            seen["spec"] = spec
            seen["tasks"] = tasks
            return SimpleNamespace(to_dict=lambda: {"status": "SUCCEEDED"})

    monkeypatch.setattr(harness, "AgentOfficeService", FakeService)
    monkeypatch.setattr(
        harness.AgentOfficeExecutionSpec,
        "from_mapping",
        classmethod(lambda cls, payload: SimpleNamespace(goal_id="goal-1")),
    )
    monkeypatch.setattr(
        harness.AgentOfficeTask,
        "from_mapping",
        classmethod(lambda cls, payload: SimpleNamespace()),
    )

    auth = SimpleNamespace(
        authorization_id="agent-office-auth",
        execution_id="exec-1",
        harness_decision_id="decision-1",
        authorized_action="DEVELOPMENT",
        lineage={"goal_id": "goal-1"},
        subject="capability:agent-office.execute",
    )

    result = harness.execute_agent_office_capability(
        auth,
        SimpleNamespace(),
        {"tasks": [{}]},
        repository_root=tmp_path,
    )

    assert result["status"] == "SUCCEEDED"
    adapter = seen["adapter"]
    assert isinstance(adapter, MunderAdapter)
    hook = adapter._development_durability_hook
    assert isinstance(hook, HarnessDevelopmentCheckpointHook)
    assert hook.parent_authorization is auth
    assert hook.goal_id == "goal-1"
