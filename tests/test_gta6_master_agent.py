from __future__ import annotations
import pytest
from app.database.gta6_master_agent_repository import list_gta6_master_agent_runs
from app.services.ai_provider import AIResponse
from app.services.gta6_master_agent import GTA6MasterAgent
from app.services.harness_authorization_service import issue_harness_authorization

class FakeAIProvider:
    def generate(self, prompt):
        return AIResponse(text='{"action":"RESEARCH","reason":"research needed","priority":"HIGH","confidence":0.9}')
class WaitAIProvider:
    def generate(self, prompt):
        return AIResponse(text='{"action":"WAIT","reason":"nothing to do","priority":"LOW","confidence":0.99}')

def auth(action="RESEARCH"):
    return issue_harness_authorization(authorized_action=action, subject=f"action:{action}")

def test_master_agent_recommends_without_side_effect():
    calls=[]; agent=GTA6MasterAgent(ai_provider=FakeAIProvider())
    agent.dispatcher._actions["RESEARCH"]=("br_research_run", lambda context: calls.append("research"))
    decision=agent.recommend(); assert decision.action == "RESEARCH" and calls == []

def test_master_agent_requires_harness_authorization_for_side_effect():
    agent=GTA6MasterAgent(ai_provider=FakeAIProvider())
    with pytest.raises(PermissionError, match="Harness authorization"):
        agent.run_once()

def test_master_agent_executes_exact_authorized_action_and_persists_lineage():
    calls=[]; agent=GTA6MasterAgent(ai_provider=FakeAIProvider())
    agent.dispatcher._actions["RESEARCH"]=("br_research_run", lambda context: calls.append("research") or {"ok":True, "context":context})
    authorization=auth(); decision=agent.recommend(); result=agent.execute_authorized(decision, authorization)
    assert calls == ["research"] and result.action.execution_id == authorization.execution_id
    runs=list_gta6_master_agent_runs(); assert any(r["execution_id"] == authorization.execution_id for r in runs)

def test_master_agent_rejects_mismatched_authorization():
    agent=GTA6MasterAgent(ai_provider=FakeAIProvider()); decision=agent.recommend()
    with pytest.raises(PermissionError, match="action mismatch"):
        agent.execute_authorized(decision, auth("EXECUTION"))

def test_wait_is_passive_and_needs_no_authorization():
    agent=GTA6MasterAgent(ai_provider=WaitAIProvider()); result=agent.run_once()
    assert result.decision.action == "WAIT" and result.action.tool is None and result.action.success
