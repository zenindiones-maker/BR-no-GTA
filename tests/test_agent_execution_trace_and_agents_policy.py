from __future__ import annotations

from pathlib import Path

import pytest

from app.services.agent_execution_trace_service import AgentExecutionTrace
from app.services.agents_policy_validation_service import validate_agents_policy


ROOT=Path(__file__).resolve().parents[1]


def test_trace_tree_binds_full_causal_chain_without_sensitive_payloads():
    trace=AgentExecutionTrace.create(
        mission_ref="mission:m1",
        task_ref="task:t1",
        blueprint_ref="sha256:"+"a"*64,
        worker_ref="worker:codex",
        environment_ref="sprite:s1",
        codex_session_ref="codex:session-1",
        skill_refs=("skill:tdd@v1",),
        tool_calls=(
            {"gen_ai.tool.call.id":"call-1","gen_ai.tool.name":"shell"},
        ),
        artifact_refs=("artifact:result:sha256:abc",),
        review_ref="review:r1",
        result_ref="task-result:r1",
        reducer_ref="harness-reducer:r1",
        gen_ai_agent_id="codex-readonly",
        gen_ai_operation_name="execute_task",
        request_model="gpt-5.6-codex",
        response_model="gpt-5.6-codex",
        usage={"input_tokens":100,"output_tokens":20},
    )
    data=trace.to_dict()
    assert trace.schema=="AgentExecutionTrace/v1"
    assert data["authority"]=="DEEPSEEK_HARNESS"
    assert data["causal_chain"]==(
        "mission:m1","task:t1","sha256:"+"a"*64,"worker:codex",
        "sprite:s1","codex:session-1","skill:tdd@v1","call-1",
        "artifact:result:sha256:abc","review:r1","task-result:r1","harness-reducer:r1",
    )
    serialized=str(data).lower()
    assert "prompt_content" not in serialized
    assert "tool_output" not in serialized
    assert len(trace.content_sha256)==64


def test_agents_policy_is_short_progressive_and_references_resolve():
    result=validate_agents_policy(repo_root=ROOT,agents_path=ROOT/"AGENTS.md")
    assert result.status=="PASS"
    assert result.line_count <= 80
    assert result.broken_references==()
    assert result.stale_mandatory_references==()
    assert result.authority_conflicts==()


def test_agents_policy_detects_conflicting_authority_and_broken_ref(tmp_path):
    root=tmp_path
    (root/"AGENTS.md").write_text(
        "# Agents\nHarness is sole authority.\nAgent is final authority.\n"
        "Required: docs/missing.md\n",
        encoding="utf-8",
    )
    result=validate_agents_policy(repo_root=root,agents_path=root/"AGENTS.md")
    assert result.status=="FAIL"
    assert "docs/missing.md" in result.broken_references
    assert result.authority_conflicts
