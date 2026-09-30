from __future__ import annotations

import argparse
from dataclasses import replace
import json
import os
import re
from pathlib import Path
from typing import Any

from app.database.openai_agents_repository import (
    get_openai_agent_session_head,
    persist_agent_environment_lease,
    persist_openai_agent_session_receipt,
)
from app.database.schema import initialize_schema
from app.services.harness_authorization_service import issue_harness_authorization
from app.services.harness_collaboration_service import TaskEnvelope
from app.services.task_result_envelope_service import build_task_result_envelope
from app.services.harness_improvement_coalition_service import TaskTopologyAssessment
from app.services.openai_agents_contracts import (
    AgentEnvironmentLease,
    OpenAIAgentSessionReceipt,
    SelectedSkillSpec,
)
from app.services.agent_office.delegation import (
    DelegatedTaskLease,
    MANDATORY_FORBIDDEN_ACTIONS,
)
from datetime import datetime, timedelta, timezone

_OPENAI_SECRET_RE = re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{6,}")


def _contains_openai_secret(value: Any) -> bool:
    raw=json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return bool(_OPENAI_SECRET_RE.search(raw) or re.search(r"(?i)(?:^|[^A-Za-z0-9_])api_key(?:[^A-Za-z0-9_]|$)", raw))


from app.services.openai_agents_runtime_service import (
    MAX_CONCURRENT_OPENAI_SUBAGENTS,
    OpenAIAgentsRuntime,
    build_openai_agent_configuration,
    build_openai_subagent_plan,
    build_tool_search_configuration,
    classify_model_eligibility,
    gpt_6_1_sol_profile,
    require_bounded_computer_use,
    verify_openai_task_completion,
)


class _FakeTransport:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.session_get_count = 0

    def __call__(
        self,
        *,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        self.calls.append({
            "method": method,
            "path": path,
            "body": body,
            "idempotency_key": idempotency_key,
        })
        if method == "POST" and path == "/agents/sessions":
            return {
                "id": "sess_dd2_proof",
                "status": "in_progress",
                "environment": {"id": "env_dd2_proof"},
                "latest_turn": {
                    "id": "turn_dd2_proof",
                    "status": "in_progress",
                },
                "required_actions": [],
            }
        if method == "GET" and path == "/agents/sessions/sess_dd2_proof":
            self.session_get_count += 1
            return {
                "id": "sess_dd2_proof",
                "status": "requires_action",
                "environment": {"id": "env_dd2_proof"},
                "agent": {
                    "model": "gpt-6.1-sol",
                    "reasoning": {"effort": "high"},
                    "multi_agent": {
                        "enabled": True,
                        "max_concurrent_subagents": 3,
                    },
                },
                "required_actions": [{
                    "type": "function_call",
                    "turn_id": "turn_dd2_proof",
                    "call_id": "call_dd2_proof",
                    "name": "lookup_evidence",
                    "arguments": {"ref": "evidence:dd2"},
                }],
            }
        if method == "POST" and path == "/agents/sessions/sess_dd2_proof/events":
            return {"_http_status": 202, "accepted": True}
        raise AssertionError((method, path))


def _auth(execution_id: str) -> str:
    auth = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject="capability:openai.agents.session",
        execution_id=execution_id,
        lineage={"source": "dd2-provider-free-operational-proof"},
    )
    return auth.authorization_id


def run_dd2_operational_proof(*, database_file: str | Path) -> dict[str, Any]:
    os.environ["BR_TEST_DATABASE"] = str(database_file)
    initialize_schema()

    environment = AgentEnvironmentLease.from_mapping({
        "lease_id": "envlease:dd2:proof",
        "environment_type": "OPENAI_HOSTED",
        "environment_id": "env_dd2_proof",
        "approved_domains": ["developers.openai.com"],
        "approved_apps": ["browser"],
        "allowed_capabilities": ["COMPUTER_USE", "SANDBOX"],
        "time_budget_seconds": 300,
        "external_tool_time_budget_seconds": 180,
        "max_artifact_bytes": 10_000_000,
        "expires_at": "2099-01-01T00:00:00+00:00",
        "task_lease_ref": "delegated-task:task-dd2-proof",
        "status": "ACTIVE",
    })
    persist_agent_environment_lease(environment)

    topology = TaskTopologyAssessment(
        topology="PARALLEL_INDEPENDENT",
        reasons=("INDEPENDENT_EVIDENCE_BRANCHES",),
        evidence={
            "parallelizable_branch_count": 5,
            "shared_mutable_state": False,
            "write_set_overlap": False,
        },
    )
    subagents = build_openai_subagent_plan(
        topology=topology,
        requested_subagents=5,
    )
    tool_search = build_tool_search_configuration(
        namespaces=("web.search", "github.read", "youtube.analytics"),
        selected_namespaces=("web.search", "github.read"),
    )
    skills = (
        SelectedSkillSpec(
            skill_id="tdd",
            version="1",
            source="superpowers",
            instruction_hash="a" * 64,
            eligible=True,
        ),
        SelectedSkillSpec(
            skill_id="deploy",
            version="1",
            source="br",
            instruction_hash="b" * 64,
            eligible=False,
        ),
    )
    config = build_openai_agent_configuration(
        model_profile=gpt_6_1_sol_profile(),
        reasoning_effort="high",
        selected_skills=skills,
        tool_search=tool_search,
        multi_agent_plan=subagents,
    )

    task_envelope = TaskEnvelope.from_mapping({
        "task_id": "task-dd2-proof",
        "mission_id": "mission-dd2-proof",
        "goal_id": "goal-dd2-proof",
        "capability_id": "openai.agents.session",
        "action": "EXECUTION",
        "objective": "Execute bounded DD2 provider-free runtime proof.",
        "task_class": "EXECUTION",
        "functional_role": "SPECIALIST_EXECUTOR",
        "allowed_tools": ["web.search"],
        "allowed_side_effects": [],
        "expected_outputs": ["artifact:dd2:proof"],
        "acceptance_criteria": ["Harness verifies typed result and required artifact"],
        "evidence_requirements": ["OpenAIAgentSessionReceipt/v1", "TaskResultEnvelope/v1"],
        "time_budget_seconds": 300,
        "cost_budget": 1.0,
        "tool_budget": 20,
        "retry_budget": 2,
        "risk_side_effect_class": "READ_ONLY",
    })

    task_lease = DelegatedTaskLease.from_mapping({
        "mission_id": "mission-dd2-proof",
        "task_id": "task-dd2-proof",
        "goal_id": "goal-dd2-proof",
        "harness_decision_id": "decision-dd2-proof",
        "authorization_id": "auth-dd2-proof",
        "delegation_id": "delegation-dd2-proof",
        "agent_id": "openai-agent-runtime",
        "capability_ids": ["openai.agents.session", "openai.computer-use"],
        "base_sha": "a" * 40,
        "allowed_paths": [],
        "allowed_tools": ["openai.agents.session", "openai.computer-use", "web.search"],
        "allowed_actions": ["EXECUTION"],
        "forbidden_actions": sorted(MANDATORY_FORBIDDEN_ACTIONS),
        "input_artifact_refs": [],
        "expected_outputs": ["OpenAIAgentSessionReceipt/v1", "TaskResultEnvelope/v1"],
        "acceptance_criteria": ["Harness verifies result"],
        "evidence_requirements": ["session receipt", "tool evidence"],
        "time_budget_seconds": 300,
        "cost_budget": 1.0,
        "tool_call_budget": 20,
        "retry_budget": 2,
        "max_parallelism": 3,
        "expires_at": (
            datetime.now(timezone.utc) + timedelta(minutes=10)
        ).isoformat(),
        "escalation_conditions": ["provider unavailable", "approval required"],
        "owned_task_class": "EXECUTION",
        "role": "specialist-executor",
        "read_set": [],
        "write_set": [],
    })
    computer = require_bounded_computer_use(
        environment_lease=environment,
        task_lease=task_lease,
        requested_domain="developers.openai.com",
        requested_app="browser",
        requested_seconds=60,
    )
    unbounded_computer_rejected = False
    try:
        require_bounded_computer_use(
            environment_lease=environment,
            task_lease=task_lease,
            requested_domain="evil.example",
            requested_app="browser",
            requested_seconds=60,
        )
    except PermissionError:
        unbounded_computer_rejected = True


    transport = _FakeTransport()
    runtime = OpenAIAgentsRuntime(transport=transport)
    created = runtime.create_session(
        authorization_ref=_auth("dd2:proof:create"),
        execution_id="dd2:proof:create",
        agent_config={
            **config,
            "instructions": "Execute only the bounded DD2 provider-free proof.",
        },
        environment={"type": "openai_hosted"},
        initial_input="Inspect independent evidence branches.",
        trace_refs=("trace:dd2:create",),
        task_id=task_envelope.task_id,
        attempt_id="attempt-dd2-proof",
        runtime_revision="dd2-operational-proof-v1",
        provider="openai",
        subagent_refs=("subagent:research-a", "subagent:research-b", "subagent:research-c"),
    )
    recovered = runtime.recover_same_session(
        session_id=created.session_id,
        prior_turn_id=created.turn_id or "turn_dd2_proof",
        trace_refs=("trace:dd2:recovery",),
    )
    accepted = runtime.submit_tool_result(
        authorization_ref=_auth("dd2:proof:tool-result"),
        execution_id="dd2:proof:tool-result",
        session_id=recovered.session_id,
        turn_id=recovered.turn_id or "turn_dd2_proof",
        call_id="call_dd2_proof",
        tool_name="lookup_evidence",
        success=True,
        output='{"evidence_ref":"evidence:dd2","status":"ok"}',
        evidence_refs=("evidence:dd2",),
    )
    duplicate_tool_result = runtime.submit_tool_result(
        authorization_ref=_auth("dd2:proof:tool-result:duplicate"),
        execution_id="dd2:proof:tool-result:duplicate",
        session_id=recovered.session_id,
        turn_id=recovered.turn_id or "turn_dd2_proof",
        call_id="call_dd2_proof",
        tool_name="lookup_evidence",
        success=True,
        output='{"evidence_ref":"evidence:dd2","status":"ok"}',
        evidence_refs=("evidence:dd2",),
    )

    current = get_openai_agent_session_head(created.session_id)
    completed = OpenAIAgentSessionReceipt.from_api(
        {
            "id": created.session_id,
            "status": "idle",
            "environment": {"id": environment.environment_id},
            "required_actions": [],
        },
        turn={
            "id": created.turn_id or "turn_dd2_proof",
            "status": "completed",
            "usage": {"input_tokens": 50, "output_tokens": 20, "total_tokens": 70},
        },
        agent_model="gpt-6.1-sol",
        reasoning_effort="high",
        multi_agent_enabled=True,
        subagent_count=3,
        tool_calls=({
            "call_id": "call_dd2_proof",
            "type": "function",
            "name": "lookup_evidence",
        },),
        artifacts=({"id": "artifact:dd2:proof"},),
        trace_refs=("trace:dd2:completed",),
        task_id=task_envelope.task_id,
        attempt_id="attempt-dd2-proof",
        runtime_revision="dd2-operational-proof-v1",
        provider="openai",
        subagent_refs=("subagent:research-a", "subagent:research-b", "subagent:research-c"),
        revision=int(current["revision"]) + 1,
    )
    persist_openai_agent_session_receipt(
        completed,
        expected_current_revision=int(current["revision"]),
    )
    task_result = build_task_result_envelope(
        mission_id=task_envelope.mission_id,
        task_id=task_envelope.task_id,
        capability_id=task_envelope.capability_id,
        agent_id="openai-agent-runtime",
        skill_id="tdd",
        executor_binding="app.services.openai_agents_runtime_service.execute_openai_agents_session",
        status="COMPLETED",
        started_at=completed.created_at,
        completed_at=completed.updated_at,
        elapsed_ms=1.0,
        result={
            "summary": "DD2 provider-free bounded runtime proof completed.",
            "artifact_refs": list(completed.artifact_refs),
            "evidence_refs": [
                "evidence:dd2",
                "subagent-result:research-a",
                "subagent-result:research-b",
                "subagent-result:research-c",
            ],
        },
        source_task_ids=("research-a", "research-b", "research-c"),
        authorization_id=task_lease.authorization_id,
    )
    verified = verify_openai_task_completion(
        completed,
        task_envelope=task_envelope,
        task_result=task_result,
        verification_ref="harness-verification:dd2:proof",
    )
    persist_openai_agent_session_receipt(
        verified,
        expected_current_revision=completed.revision,
    )
    final = get_openai_agent_session_head(created.session_id)

    sol = gpt_6_1_sol_profile()
    sol_eligibility = classify_model_eligibility(
        model_id="gpt-6.1-sol",
        credentials_present=False,
        runtime_probe=None,
    )

    gates = {
        "AGENTS_API_SESSION_CONTRACT": (
            "PASS" if created.session_id == recovered.session_id == final["session_id"] else "FAIL"
        ),
        "SESSION_RECOVERY": (
            "PASS" if transport.session_get_count == 1 and recovered.state == "REQUIRES_ACTION" else "FAIL"
        ),
        "TASK_SUCCESS_NOT_EQUAL_TURN_COMPLETED": (
            "PASS"
            if not completed.br_task_success
            and verified.br_task_success
            and task_result.schema == "task-result-envelope/v1"
            and "artifact:dd2:proof" in task_result.output_artifact_refs
            else "FAIL"
        ),
        "REQUIRED_ACTION_RESUME_SAME_SESSION": (
            "PASS" if accepted["accepted"] and not accepted["completed"] else "FAIL"
        ),
        "TOOL_RESULT_IDEMPOTENCY": (
            "PASS"
            if accepted["duplicate"] is False
            and duplicate_tool_result["duplicate"] is True
            and sum(
                1 for call in transport.calls
                if call["method"] == "POST"
                and call["path"] == "/agents/sessions/sess_dd2_proof/events"
            ) == 1
            else "FAIL"
        ),
        "COMPUTER_USE_BOUNDED": (
            "PASS" if computer["allowed"] and unbounded_computer_rejected else "FAIL"
        ),
        "SUBAGENTS_BOUNDED": (
            "PASS" if subagents.enabled and subagents.max_concurrent_subagents == MAX_CONCURRENT_OPENAI_SUBAGENTS else "FAIL"
        ),
        "MAX_CONCURRENT_DEFAULT_3": (
            "PASS" if MAX_CONCURRENT_OPENAI_SUBAGENTS == 3 else "FAIL"
        ),
        "TOOL_SEARCH": (
            "PASS" if tool_search["defer_loading"] and len(tool_search["allowed_namespaces"]) == 2 else "FAIL"
        ),
        "SKILL_LOADING": (
            "PASS"
            if [item["skill_id"] for item in config["skills"]] == ["tdd"]
            and all(item["grants_authority"] is False for item in config["skills"])
            else "FAIL"
        ),
        "GPT_6_1_SOL_TYPED_INELIGIBLE": (
            "PASS"
            if sol.model_id == "gpt-6.1-sol"
            and sol.live_proof_status == "NOT_PROVEN"
            and not sol.auto_routing_eligible
            and sol_eligibility.status == "INELIGIBLE_WITH_REASON"
            and sol_eligibility.reason == "OPENAI_CREDENTIAL_UNAVAILABLE"
            else "FAIL"
        ),
        "HARNESS_SOLE_AUTHORITY": (
            "PASS"
            if final["state"] == "TASK_VERIFIED"
            and "harness-verification:dd2:proof" in final["trace_refs"]
            and task_result.authorization_lineage_ref == "authorization:" + task_lease.authorization_id
            else "FAIL"
        ),
        "TASK_RESULT_ENVELOPE": (
            "PASS"
            if task_result.schema == "task-result-envelope/v1"
            and task_result.task_id == task_envelope.task_id
            and task_result.mission_id == task_envelope.mission_id
            and task_result.capability_id == task_envelope.capability_id
            else "FAIL"
        ),
        "NO_SECRET_IN_RECEIPT": (
            "PASS" if not _contains_openai_secret(final) else "FAIL"
        ),
    }
    gates["AGENTS_API_SESSION"] = gates["AGENTS_API_SESSION_CONTRACT"]
    gates["GPT_6_1_SOL_PROFILE"] = "PASS" if sol.model_id == "gpt-6.1-sol" and sol.auto_routing_eligible is False else "FAIL"
    status = "PASS" if all(value == "PASS" for value in gates.values()) else "FAIL"
    return {
        "schema": "OpenAIAgentsDD2OperationalProof/v1",
        "status": status,
        "gates": gates,
        "session_id": created.session_id,
        "turn_id": created.turn_id,
        "final_state": final["state"],
        "subagent_count": subagents.max_concurrent_subagents,
        "tool_search_namespaces": tool_search["allowed_namespaces"],
        "task_result_digest": task_result.content_sha256,
        "task_result_schema": task_result.schema,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    result = run_dd2_operational_proof(database_file=args.database)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print("OPENAI_AGENTS_DD2_OPERATIONAL_STATUS=" + result["status"])
    for gate, value in sorted(result["gates"].items()):
        print(f"{gate}={value}")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
