from __future__ import annotations
import pytest
from app.services.gta6_action_dispatcher import GTA6ActionDispatcher
from app.services.gta6_brain import BrainDecision
from app.services.harness_authorization_service import issue_harness_authorization


def make_dispatcher(calls):
    return GTA6ActionDispatcher(
        monitor=lambda *, execution_id: calls.append("monitor") or {"ok":"monitor"},
        research=lambda context: calls.append("research") or {"ok":"research","context":context},
        editorial=lambda context: calls.append("editorial") or {"ok":"editorial","context":context},
        execution=lambda context: calls.append("execution") or {"ok":"execution","context":context},
        youtube=lambda context: calls.append("youtube") or {"ok":"youtube","context":context},
    )


def decision(action): return BrainDecision(action=action, reason="test", priority="HIGH", confidence=.9)
def auth(action): return issue_harness_authorization(authorized_action=action, subject=f"action:{action}")

@pytest.mark.parametrize("action,call", [("MONITOR","monitor"),("RESEARCH","research"),("EDITORIAL","editorial"),("EXECUTION","execution"),("YOUTUBE","youtube")])
def test_dispatch_executes_only_harness_authorized_action(action, call):
    calls=[]; result=make_dispatcher(calls).dispatch(decision(action), authorization=auth(action))
    assert calls == [call] and result.success is True and result.harness_decision_id


def test_dispatch_rejects_missing_and_fabricated_authorization():
    dispatcher=make_dispatcher([])
    with pytest.raises(PermissionError): dispatcher.dispatch(decision("EXECUTION"))
    with pytest.raises(PermissionError): dispatcher.dispatch(decision("EXECUTION"), authorization="fake")


def test_dispatch_rejects_action_mismatch_before_handler():
    calls=[]; dispatcher=make_dispatcher(calls)
    with pytest.raises(PermissionError, match="action mismatch"):
        dispatcher.dispatch(decision("EXECUTION"), authorization=auth("RESEARCH"))
    assert calls == []


def test_wait_never_requires_authorization_or_executes():
    calls=[]; result=make_dispatcher(calls).dispatch(decision("WAIT")); assert calls == [] and result.success


def test_context_uses_canonical_harness_decision_and_compatibility_alias():
    calls=[]; authorization=auth("EXECUTION")
    result=make_dispatcher(calls).dispatch(decision("EXECUTION"), authorization=authorization)
    context=result.result["context"]
    assert context["authorization_id"] == authorization.authorization_id
    assert context["harness_decision_id"] == authorization.harness_decision_id
    assert context["brain_decision_id"] == authorization.harness_decision_id


@pytest.mark.parametrize("action", ["RESEARCH", "EXECUTION", "YOUTUBE"])
def test_side_effecting_actions_receive_canonical_persisted_harness_context(action):
    calls = []
    authorization = auth(action)
    result = make_dispatcher(calls).dispatch(
        decision(action),
        authorization=authorization,
    )

    context = result.result["context"]

    assert context["authorization_id"] == authorization.authorization_id
    assert context["execution_id"] == authorization.execution_id
    assert context["authorized_action"] == action
    assert context["authorization_subject"] == f"action:{action}"
    assert context["issued_by"] == "deepseek_harness"


def test_action_tool_mapping_matches_registered_mcp_surfaces():
    from app.integrations.deepseek_harness import server

    expected = {
        "MONITOR": "br_gta6_monitor_run_once",
        "RESEARCH": "br_research_run",
        "EDITORIAL": "br_editorial_process_next",
        "EXECUTION": "br_execution_process_next",
        "YOUTUBE": "br_youtube_publish_next",
    }
    registered = {tool.name for tool in server.mcp._tool_manager.list_tools()}
    assert GTA6ActionDispatcher.ACTION_TO_TOOL == expected
    assert set(expected.values()) <= registered
    assert "br_youtube_pode_postar" in registered
    assert "br_youtube_pode_postar" not in expected.values()


@pytest.mark.parametrize("action", ["EXECUTION", "YOUTUBE"])
def test_dispatch_result_reports_canonical_mcp_tool(action):
    calls = []
    result = make_dispatcher(calls).dispatch(decision(action), authorization=auth(action))
    expected = {
        "EXECUTION": "br_execution_process_next",
        "YOUTUBE": "br_youtube_publish_next",
    }
    assert result.success is True
    assert result.tool == expected[action]
    assert calls == [action.lower()]
