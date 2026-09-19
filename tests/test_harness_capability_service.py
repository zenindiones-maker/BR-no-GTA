from __future__ import annotations

import pytest

from app.services.harness_capability_service import (
    CAPABILITY_CATALOG,
    discover_capabilities,
    execute_capability,
)
from app.services.harness_authorization_service import issue_harness_authorization


def _authorization(
    action: str = "DEVELOPMENT",
    capability_id: str = "addy:code-review-and-quality",
):
    return issue_harness_authorization(
        authorized_action=action,
        subject=f"capability:{capability_id}",
        harness_decision_id="decision-1",
        execution_id="execution-1",
    )


def test_catalog_contains_global_registry_inventory():
    addy = [
        item for item in CAPABILITY_CATALOG
        if item.capability_id.startswith("addy:")
    ]
    higgsfield = [
        item for item in CAPABILITY_CATALOG
        if item.provider == "higgsfield"
    ]

    assert len(addy) == 24
    assert len(higgsfield) == 4
    assert all(item.available for item in addy)
    assert all(not item.available for item in higgsfield)
    assert not any(
        "browser-testing-with-devtools" in item.capability_id
        for item in addy
    )


def test_discovery_is_progressive_and_does_not_return_entire_catalog():
    assert discover_capabilities(
        intent="",
        authorized_action="DEVELOPMENT",
    ) == []

    results = discover_capabilities(
        intent="code review quality",
        authorized_action="DEVELOPMENT",
    )

    ids = {item["capability_id"] for item in results}
    assert "addy:code-review-and-quality" in ids
    assert len(results) <= 5
    assert all(item["availability"] == "AVAILABLE" for item in results)


def test_discovery_filters_action_and_blocked_availability():
    development = discover_capabilities(
        intent="code review youtube higgsfield",
        authorized_action="DEVELOPMENT",
        limit=20,
    )
    ids = {item["capability_id"] for item in development}

    assert "addy:code-review-and-quality" in ids
    assert "youtube.publish-public" not in ids
    assert not any(item.startswith("higgsfield-") for item in ids)


def test_execution_rejects_fabricated_authorization():
    with pytest.raises(PermissionError, match="not found"):
        execute_capability(
            capability_id="addy:code-review-and-quality",
            authorization="fabricated",
            payload={},
        )


def test_execution_rejects_action_outside_capability_policy():
    with pytest.raises(PermissionError, match="not authorized"):
        execute_capability(
            capability_id="higgsfield-youtube-thumbnail",
            authorization=_authorization(
                "EXECUTION",
                "higgsfield-youtube-thumbnail",
            ),
            payload={},
        )


def test_higgsfield_is_blocked_before_adapter_execution():
    evidence = execute_capability(
        capability_id="higgsfield-generate",
        authorization=_authorization("EXECUTION", "higgsfield-generate"),
        payload={"prompt": "do not generate"},
    )

    assert evidence.status == "BLOCKED"
    assert evidence.active is False
    assert evidence.provider == "higgsfield"
    assert evidence.authority == "deepseek_harness"
    assert evidence.harness_decision_id == "decision-1"
    assert evidence.execution_id == "execution-1"
    assert "ephemeral-runner auth" in evidence.boundary


def test_unknown_capability_state_fails_before_executor():
    called = False

    def executor(capability, payload):
        nonlocal called
        called = True
        return {"unexpected": True}

    with pytest.raises(ValueError, match="not AVAILABLE"):
        execute_capability(
            capability_id="tubegent",
            authorization=_authorization("DEVELOPMENT", "tubegent"),
            payload={},
            executor=executor,
        )

    assert called is False


def test_addy_rejects_caller_supplied_executor_override():
    def attacker_executor(capability, payload):
        return {"unexpected": True}

    with pytest.raises(PermissionError, match="caller executor is not the Registry binding"):
        execute_capability(
            capability_id="addy:code-review-and-quality",
            authorization=_authorization(),
            payload={"target": "changed-files"},
            executor=attacker_executor,
        )


def test_addy_override_failure_cannot_trigger_silent_fallback():
    def failing_override(capability, payload):
        raise RuntimeError("should never run")

    with pytest.raises(PermissionError, match="caller executor is not the Registry binding"):
        execute_capability(
            capability_id="addy:code-review-and-quality",
            authorization=_authorization(),
            payload={},
            executor=failing_override,
        )


def test_harness_discovery_authorization_preserves_registry_executor_identity():
    discovered = discover_capabilities(
        intent="code review quality",
        authorized_action="DEVELOPMENT",
        limit=5,
    )
    selected = next(
        item
        for item in discovered
        if item["capability_id"] == "addy:code-review-and-quality"
    )
    assert selected["executor_binding"] == (
        "app.services.addy_harness_service.execute_authorized_addy_skill"
    )
    authorization = _authorization(
        "DEVELOPMENT",
        selected["capability_id"],
    )

    with pytest.raises(PermissionError, match="caller executor is not the Registry binding"):
        execute_capability(
            capability_id=selected["capability_id"],
            authorization=authorization,
            payload={"task": "review"},
            executor=lambda capability, payload: {
                "capability_id": capability.capability_id,
                "observed": payload["task"],
            },
        )


def test_generic_execution_catalog_remains_bounded_to_existing_adapters():
    ids = {item.capability_id for item in CAPABILITY_CATALOG}

    assert len([item for item in ids if item.startswith("addy:")]) == 24
    assert len([item for item in ids if item.startswith("higgsfield-")]) == 4
    assert "ai.provider.nvidia-nim" not in ids
    assert "video.render" not in ids
    assert "youtube.publish-public" not in ids
