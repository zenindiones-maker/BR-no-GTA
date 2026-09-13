from __future__ import annotations

import pytest

from app.services.harness_capability_service import (
    CAPABILITY_CATALOG,
    CapabilityAuthorization,
    discover_capabilities,
    execute_capability,
)


def _authorization(action: str = "DEVELOPMENT") -> CapabilityAuthorization:
    return CapabilityAuthorization(
        authority="deepseek_harness",
        authorized_action=action,
        harness_decision_id="decision-1",
        execution_id="execution-1",
    )


def test_catalog_contains_expected_available_capabilities():
    addy = [item for item in CAPABILITY_CATALOG if item.provider == "addy-agent-skills"]
    higgsfield = [item for item in CAPABILITY_CATALOG if item.provider == "higgsfield"]

    assert len(addy) == 24
    assert len(higgsfield) == 4
    assert all(item.available for item in CAPABILITY_CATALOG)
    assert not any("browser-testing-with-devtools" in item.capability_id for item in addy)


def test_discovery_is_progressive_and_does_not_return_entire_catalog():
    assert discover_capabilities(intent="", authorized_action="DEVELOPMENT") == []

    results = discover_capabilities(
        intent="code review quality",
        authorized_action="DEVELOPMENT",
    )

    ids = {item["capability_id"] for item in results}
    assert "addy:code-review-and-quality" in ids
    assert len(results) <= 5


def test_execution_rejects_non_harness_authority():
    authorization = CapabilityAuthorization(
        authority="gta6_brain",
        authorized_action="DEVELOPMENT",
        harness_decision_id="decision-1",
        execution_id="execution-1",
    )

    with pytest.raises(PermissionError, match="sole capability authority"):
        execute_capability(
            capability_id="addy:code-review-and-quality",
            authorization=authorization,
            payload={},
        )


def test_execution_rejects_action_outside_capability_policy():
    with pytest.raises(PermissionError, match="not authorized"):
        execute_capability(
            capability_id="higgsfield-youtube-thumbnail",
            authorization=_authorization("EXECUTION"),
            payload={},
        )


def test_higgsfield_is_available_but_blocked_before_adapter_execution():
    called = False

    def executor(capability, payload):
        nonlocal called
        called = True
        return {"unexpected": True}

    evidence = execute_capability(
        capability_id="higgsfield-generate",
        authorization=_authorization("EXECUTION"),
        payload={"prompt": "do not generate"},
        executor=executor,
    )

    assert called is False
    assert evidence.status == "BLOCKED"
    assert evidence.active is False
    assert evidence.provider == "higgsfield"
    assert evidence.authority == "deepseek_harness"
    assert evidence.harness_decision_id == "decision-1"
    assert evidence.execution_id == "execution-1"
    assert "ephemeral-runner auth" in evidence.boundary


def test_authorized_addy_executor_returns_evidence_to_harness():
    calls = []

    def executor(capability, payload):
        calls.append((capability.capability_id, payload))
        return {"review": "pass"}

    evidence = execute_capability(
        capability_id="addy:code-review-and-quality",
        authorization=_authorization(),
        payload={"target": "changed-files"},
        executor=executor,
    )

    assert calls == [
        ("addy:code-review-and-quality", {"target": "changed-files"}),
    ]
    assert evidence.status == "EXECUTED"
    assert evidence.active is True
    assert evidence.result == {"review": "pass"}
    assert evidence.authorized_action == "DEVELOPMENT"
