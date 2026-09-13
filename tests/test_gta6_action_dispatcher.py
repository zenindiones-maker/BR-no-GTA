from __future__ import annotations
import pytest
from app.services.gta6_action_dispatcher import GTA6ActionDispatcher
from app.services.gta6_brain import BrainDecision
from app.services.harness_authorization_service import issue_harness_authorization


def make_dispatcher(calls):
    return GTA6ActionDispatcher(
        monitor=lambda *, execution_id: calls.append("monitor") or {"ok":"monitor"},
        research=lambda: calls.append("research") or {"ok":"research"},
        editorial=lambda context: calls.append("editorial") or {"ok":"editorial","context":context},
        execution=lambda context: calls.append("execution") or {"ok":"execution","context":context},
        youtube=lambda: calls.append("youtube") or {"ok":"youtube"},
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
