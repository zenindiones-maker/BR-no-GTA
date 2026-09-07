from __future__ import annotations

import pytest

from app.services.gta6_action_dispatcher import (
    GTA6ActionDispatcher,
)
from app.services.gta6_brain import BrainDecision


def make_dispatcher(calls: list[str]) -> GTA6ActionDispatcher:
    return GTA6ActionDispatcher(
        monitor=lambda: calls.append("monitor") or {"ok": "monitor"},
        research=lambda: calls.append("research") or {"ok": "research"},
        editorial=lambda: calls.append("editorial") or {"ok": "editorial"},
        execution=lambda: calls.append("execution") or {"ok": "execution"},
    )


@pytest.mark.parametrize(
    ("action", "expected_call", "expected_tool"),
    [
        (
            "MONITOR",
            "monitor",
            "br_gta6_monitor_run_once",
        ),
        (
            "RESEARCH",
            "research",
            "br_research_run",
        ),
        (
            "EDITORIAL",
            "editorial",
            "br_editorial_process_next",
        ),
        (
            "EXECUTION",
            "execution",
            "br_execution_run_once",
        ),
    ],
)
def test_dispatch_executes_only_authorized_action(
    action: str,
    expected_call: str,
    expected_tool: str,
):
    calls: list[str] = []
    dispatcher = make_dispatcher(calls)

    decision = BrainDecision(
        action=action,
        reason="test",
        priority="HIGH",
        confidence=0.9,
    )

    result = dispatcher.dispatch(decision)

    assert calls == [expected_call]
    assert result.action == action
    assert result.tool == expected_tool
    assert result.success is True


def test_wait_does_not_execute_any_action():
    calls: list[str] = []
    dispatcher = make_dispatcher(calls)

    decision = BrainDecision(
        action="WAIT",
        reason="nothing to do",
        priority="LOW",
        confidence=0.99,
    )

    result = dispatcher.dispatch(decision)

    assert calls == []
    assert result.action == "WAIT"
    assert result.tool is None
    assert result.success is True
    assert result.result is None


def test_action_failure_is_returned_as_result():
    def failing_research():
        raise RuntimeError("research failed")

    dispatcher = GTA6ActionDispatcher(
        monitor=lambda: None,
        research=failing_research,
        editorial=lambda: None,
        execution=lambda: None,
    )

    decision = BrainDecision(
        action="RESEARCH",
        reason="test failure",
        priority="HIGH",
        confidence=0.9,
    )

    result = dispatcher.dispatch(decision)

    assert result.action == "RESEARCH"
    assert result.tool == "br_research_run"
    assert result.success is False
    assert result.result["error_type"] == "RuntimeError"
    assert result.result["error"] == "research failed"


def test_unsupported_action_is_rejected():
    dispatcher = make_dispatcher([])

    decision = BrainDecision(
        action="DELETE_DATABASE",
        reason="invalid",
        priority="CRITICAL",
        confidence=1.0,
    )

    with pytest.raises(
        ValueError,
        match="Unsupported GTA6 Brain action",
    ):
        dispatcher.dispatch(decision)


def test_result_can_be_serialized_to_dict():
    dispatcher = make_dispatcher([])

    decision = BrainDecision(
        action="MONITOR",
        reason="test",
        priority="MEDIUM",
        confidence=0.8,
    )

    result = dispatcher.dispatch(decision)
    payload = dispatcher.to_dict(result)

    assert payload == {
        "action": "MONITOR",
        "tool": "br_gta6_monitor_run_once",
        "success": True,
        "result": {"ok": "monitor"},
    }
