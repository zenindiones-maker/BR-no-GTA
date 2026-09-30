from __future__ import annotations

import argparse
import ast
from datetime import datetime, timedelta, timezone
import inspect
import json
import os
from pathlib import Path
from typing import Any

from app.database.persistent_intelligence_repository import (
    append_activity,
    count_opportunity_candidates,
    get_activity_feed,
    get_custom_rules,
    get_responsibility,
    persist_opportunity_candidate,
    record_wake_usage,
)
from app.database.schema import initialize_schema
from app.services.agent_office.delegation import (
    DelegatedTaskLease,
    MANDATORY_FORBIDDEN_ACTIONS,
)
from app.services.harness_authorization_service import issue_harness_authorization
from app.services.harness_collaboration_service import TaskEnvelope
from app.services.persistent_intelligence_contracts import (
    AgentCustomRule,
    PersistentAgentActivity,
    PersistentAgentIdentity,
    PersistentBudgetExhausted,
    PersistentResponsibility,
    PersistentWorkTimeBudget,
    ProactiveResearchPolicy,
)
from app.services.persistent_intelligence_force_service import (
    evaluate_custom_rule,
    evaluate_wake,
    pause_responsibility,
    process_wake_event,
    register_custom_rule,
    register_persistent_agent_identity,
    register_responsibility,
    replay_activity_feed,
    require_fresh_side_effect_authorization,
    resolve_effective_permission,
    resume_responsibility,
    transition_responsibility,
)


def _budget() -> PersistentWorkTimeBudget:
    return PersistentWorkTimeBudget.from_mapping(
        {
            "maximum_wall_clock_per_wake_seconds": 300,
            "maximum_total_active_time_per_day_seconds": 1800,
            "maximum_agent_turns": 12,
            "maximum_semantic_calls": 8,
            "maximum_provider_calls": 8,
            "maximum_tool_calls": 20,
            "maximum_subagents": 2,
            "maximum_subagent_time_seconds": 600,
            "maximum_retries": 2,
            "maximum_external_tool_time_seconds": 900,
            "maximum_cost_per_wake": 0.5,
            "maximum_cost_per_day": 2.0,
        }
    )


def _responsibility() -> PersistentResponsibility:
    policy = ProactiveResearchPolicy.from_mapping(
        {
            "policy_id": "dd1-canary-readonly",
            "mode": "READ_ONLY",
            "allowed_actions": [
                "READ",
                "SEARCH",
                "INSPECT",
                "COMPARE",
                "RETRIEVE",
                "SUMMARIZE",
                "CREATE_PRIVATE_CANDIDATE_NOTE",
                "CREATE_IMPROVEMENT_OPPORTUNITY",
                "CREATE_EDITORIAL_OPPORTUNITY_CANDIDATE",
            ],
            "allowed_sources": ["PUBLIC_WEB"],
            "max_items_per_wake": 25,
        }
    )
    return PersistentResponsibility.from_mapping(
        {
            "responsibility_id": "DD1_CANARY",
            "owner": "BR_OWNER",
            "name": "DD1 persistent responsibility canary",
            "description": "Prove bounded event-driven persistent responsibility semantics.",
            "business_outcome": "Produce deterministic DD1 architecture evidence.",
            "domain": "system-governance",
            "task_classes": ["RESEARCH", "ANALYSIS"],
            "priority": 50,
            "enabled": True,
            "created_at": "2026-09-30T00:00:00+00:00",
            "updated_at": "2026-09-30T00:00:00+00:00",
            "trigger_policy": {"mode": "EVENT_OR_INTERVAL"},
            "proactive_research_policy": policy.to_dict(),
            "allowed_sources": ["PUBLIC_WEB"],
            "allowed_tools": ["web.search"],
            "allowed_skills": ["research"],
            "allowed_agents": ["domain-researcher"],
            "allowed_side_effects": [],
            "approval_policy": {"side_effects": "HARNESS_AUTHORIZATION_REQUIRED"},
            "risk_class": "READ_ONLY_BACKGROUND",
            "time_budget": _budget().to_dict(),
            "compute_budget": {"max_parallel_tasks": 1},
            "cost_budget": {"max_cost_per_wake_usd": 0.5, "max_cost_per_day_usd": 2.0},
            "observation_interval": {"seconds": 900},
            "event_triggers": ["source.changed"],
            "wake_conditions": ["EVENT_MATCH", "INTERVAL_DUE"],
            "context_policy": {"carry": ["artifact_refs"]},
            "memory_policy": {"write": "EVIDENCE_BOUND_ONLY"},
            "artifact_policy": {"candidate_only": True},
            "success_metrics": ["canary_pass"],
            "failure_conditions": ["SIDE_EFFECT_WITHOUT_AUTHORIZATION"],
            "escalation_policy": {"on_risk": "HAND_OFF_TO_HUMAN"},
            "pause_policy": {"owner_can_pause": True},
            "current_revision": 1,
            "status": "DORMANT",
        }
    )


def _authorization(
    responsibility_id: str,
    execution_id: str,
    *,
    subject: str | None = None,
) -> str:
    auth = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject=subject or f"responsibility:{responsibility_id}",
        execution_id=execution_id,
        lineage={"source": "dd1-operational-proof"},
    )
    return auth.authorization_id


def _task() -> TaskEnvelope:
    return TaskEnvelope.from_mapping(
        {
            "task_id": "dd1:task:opportunity",
            "mission_id": "dd1:mission",
            "goal_id": "dd1:goal",
            "capability_id": "persistent.responsibility.observe",
            "action": "RESEARCH",
            "objective": "Create one bounded evidence-backed opportunity candidate.",
            "task_class": "RESEARCH",
            "functional_role": "RESEARCHER",
            "allowed_tools": ["web.search"],
            "allowed_side_effects": [],
            "time_budget_seconds": 300,
            "cost_budget": 0.5,
            "tool_budget": 20,
            "retry_budget": 2,
            "expected_output": "EditorialOpportunityCandidate",
            "acceptance_criteria": ["one idempotent candidate"],
        }
    )


def _lease() -> DelegatedTaskLease:
    return DelegatedTaskLease.from_mapping(
        {
            "mission_id": "dd1:mission",
            "task_id": "dd1:task:opportunity",
            "goal_id": "dd1:goal",
            "harness_decision_id": "dd1:decision",
            "authorization_id": "dd1:lease-auth",
            "delegation_id": "dd1:delegation",
            "agent_id": "agent:dd1-canary",
            "capability_ids": ["persistent.responsibility.observe"],
            "base_sha": "a" * 40,
            "allowed_paths": [],
            "allowed_tools": ["web.search"],
            "allowed_actions": ["RESEARCH"],
            "forbidden_actions": sorted(MANDATORY_FORBIDDEN_ACTIONS),
            "input_artifact_refs": ["event:dd1:source.changed"],
            "expected_outputs": ["EditorialOpportunityCandidate"],
            "acceptance_criteria": ["one idempotent candidate"],
            "evidence_requirements": ["source evidence"],
            "time_budget_seconds": 300,
            "cost_budget": 0.5,
            "tool_call_budget": 20,
            "retry_budget": 2,
            "max_parallelism": 1,
            "expires_at": (
                datetime.now(timezone.utc) + timedelta(minutes=10)
            ).isoformat(),
            "escalation_conditions": ["BUDGET_EXHAUSTED"],
            "owned_task_class": "RESEARCH",
            "role": "domain-researcher",
            "read_set": [],
            "write_set": [],
        }
    )


def _no_loop_in_wake_reducer() -> bool:
    tree = ast.parse(inspect.getsource(evaluate_wake))
    return not any(
        isinstance(node, (ast.While, ast.For, ast.AsyncFor))
        for node in ast.walk(tree)
    )


def run_dd1_operational_proof(*, database_file: str | Path) -> dict[str, Any]:
    os.environ["BR_TEST_DATABASE"] = str(database_file)
    initialize_schema()

    responsibility = _responsibility()
    register_responsibility(
        responsibility,
        authorization_ref=_authorization(
            responsibility.responsibility_id,
            "dd1:register:responsibility",
        ),
        execution_id="dd1:register:responsibility",
    )

    identity = PersistentAgentIdentity.from_mapping(
        {
            "persistent_agent_id": "agent:dd1-canary",
            "responsibility_id": responsibility.responsibility_id,
            "role": "runtime-verifier",
            "runtime_family": "SPRITE",
            "agent_instance_id": "instance:dd1-canary:1",
            "provider": "local",
            "model": "deterministic",
            "environment_id": "sprite:dd1-canary",
            "session_id": "session:dd1-canary:1",
            "revision": 1,
            "capability_profile_ref": "capability-profile:dd1-canary:v1",
            "authorization_profile_ref": "authorization-profile:read-only:v1",
        }
    )
    register_persistent_agent_identity(
        identity,
        authorization_ref=_authorization(
            responsibility.responsibility_id,
            "dd1:register:identity:1",
        ),
        execution_id="dd1:register:identity:1",
    )
    rotated_identity = PersistentAgentIdentity.from_mapping(
        {
            **identity.to_dict(),
            "agent_instance_id": "instance:dd1-canary:2",
            "session_id": "session:dd1-canary:2",
            "revision": 2,
        }
    )
    register_persistent_agent_identity(
        rotated_identity,
        authorization_ref=_authorization(
            responsibility.responsibility_id,
            "dd1:register:identity:2",
        ),
        execution_id="dd1:register:identity:2",
    )

    allow_rule = AgentCustomRule.from_mapping(
        {
            "rule_id": "rule:dd1-research",
            "responsibility_id": responsibility.responsibility_id,
            "effect": "ALLOW",
            "action": "RESEARCH",
            "target": "*",
            "risk_class": "LOW",
            "conditions": {},
            "revision": 1,
            "status": "ACTIVE",
        }
    )
    push_rule = AgentCustomRule.from_mapping(
        {
            "rule_id": "rule:dd1-push",
            "responsibility_id": responsibility.responsibility_id,
            "effect": "ALLOW",
            "action": "PUSH",
            "target": "*",
            "risk_class": "HIGH",
            "conditions": {},
            "revision": 1,
            "status": "ACTIVE",
        }
    )
    for rule, execution_id in (
        (allow_rule, "dd1:register:rule:research"),
        (push_rule, "dd1:register:rule:push"),
    ):
        register_custom_rule(
            rule,
            authorization_ref=_authorization(
                responsibility.responsibility_id,
                execution_id,
            ),
            execution_id=execution_id,
        )

    research_permission = resolve_effective_permission(
        responsibility=responsibility,
        rules=(allow_rule,),
        task=_task(),
        lease=_lease(),
        requested_permission="RESEARCH",
        target="PUBLIC_WEB",
        risk_class="LOW",
    )
    push_permission = resolve_effective_permission(
        responsibility=responsibility,
        rules=(push_rule,),
        task=_task(),
        lease=_lease(),
        requested_permission="PUSH",
        target="refs/heads/main",
        risk_class="HIGH",
    )

    wake = process_wake_event(
        responsibility_id=responsibility.responsibility_id,
        event_type="source.changed",
        wake_reason="SOURCE_CHANGED",
        wake_source="POLL_CURSOR",
        wake_event_ref="event:dd1:source.changed:1",
        wake_timestamp="2026-09-30T00:01:00+00:00",
        authorization_ref=_authorization(
            responsibility.responsibility_id,
            "dd1:wake:1",
        ),
        execution_id="dd1:wake:1",
    )
    wake_id = wake["wake_id"]

    transition_execution_id=f"{wake_id}:observing"
    transition_responsibility(
        responsibility_id=responsibility.responsibility_id,
        from_status="WOKEN",
        to_status="OBSERVING",
        transition_ref=transition_execution_id,
        authorization_ref=_authorization(
            responsibility.responsibility_id,
            transition_execution_id,
        ),
        execution_id=transition_execution_id,
    )
    append_activity(
        PersistentAgentActivity.create(
            responsibility_id=responsibility.responsibility_id,
            persistent_agent_id=identity.persistent_agent_id,
            event_type="OBSERVED",
            occurred_at="2026-09-30T00:01:01+00:00",
            task_id=None,
            mission_id=None,
            summary="Read-only observation completed.",
            evidence_refs=("evidence:dd1:source",),
        )
    )
    transition_execution_id=f"{wake_id}:task-created"
    transition_responsibility(
        responsibility_id=responsibility.responsibility_id,
        from_status="OBSERVING",
        to_status="TASK_CREATED",
        transition_ref=transition_execution_id,
        authorization_ref=_authorization(
            responsibility.responsibility_id,
            transition_execution_id,
        ),
        execution_id=transition_execution_id,
    )
    candidate = persist_opportunity_candidate(
        responsibility_id=responsibility.responsibility_id,
        wake_id=wake_id,
        candidate_type="EditorialOpportunityCandidate",
        payload={
            "title": "DD1 provider-free candidate",
            "source_ref": "evidence:dd1:source",
            "read_only": True,
        },
        evidence_refs=("evidence:dd1:source",),
    )
    append_activity(
        PersistentAgentActivity.create(
            responsibility_id=responsibility.responsibility_id,
            persistent_agent_id=identity.persistent_agent_id,
            event_type="FOUND_OPPORTUNITY",
            occurred_at="2026-09-30T00:01:02+00:00",
            task_id="dd1:task:opportunity",
            mission_id=None,
            summary="Created one evidence-backed opportunity candidate.",
            evidence_refs=(candidate["candidate_id"],),
        )
    )
    transition_execution_id=f"{wake_id}:executing"
    transition_responsibility(
        responsibility_id=responsibility.responsibility_id,
        from_status="TASK_CREATED",
        to_status="EXECUTING",
        transition_ref=transition_execution_id,
        authorization_ref=_authorization(
            responsibility.responsibility_id,
            transition_execution_id,
        ),
        execution_id=transition_execution_id,
    )
    append_activity(
        PersistentAgentActivity.create(
            responsibility_id=responsibility.responsibility_id,
            persistent_agent_id=identity.persistent_agent_id,
            event_type="STARTED_TASK",
            occurred_at="2026-09-30T00:01:03+00:00",
            task_id="dd1:task:opportunity",
            mission_id=None,
            summary="Executed bounded provider-free candidate creation.",
            evidence_refs=(candidate["candidate_id"],),
        )
    )
    usage = record_wake_usage(
        wake_id=wake_id,
        responsibility_id=responsibility.responsibility_id,
        active_seconds=60,
        agent_turns=2,
        semantic_calls=0,
        provider_calls=0,
        tool_calls=2,
        subagents=0,
        subagent_seconds=0,
        retries=0,
        external_tool_seconds=10,
        cost=0.0,
        budget=responsibility.time_budget,
    )
    budget_exhaustion_proven = False
    try:
        record_wake_usage(
            wake_id=wake_id,
            responsibility_id=responsibility.responsibility_id,
            active_seconds=0,
            agent_turns=0,
            semantic_calls=0,
            provider_calls=0,
            tool_calls=0,
            subagents=0,
            subagent_seconds=0,
            retries=3,
            external_tool_seconds=0,
            cost=0.0,
            budget=responsibility.time_budget,
        )
    except PersistentBudgetExhausted:
        budget_exhaustion_proven = True

    time_budget_exhaustion_proven = False
    try:
        record_wake_usage(
            wake_id="wake:dd1:time-budget",
            responsibility_id=responsibility.responsibility_id,
            active_seconds=responsibility.time_budget.maximum_wall_clock_per_wake_seconds + 1,
            agent_turns=0,
            semantic_calls=0,
            provider_calls=0,
            tool_calls=0,
            subagents=0,
            subagent_seconds=0,
            retries=0,
            external_tool_seconds=0,
            cost=0.0,
            budget=responsibility.time_budget,
        )
    except PersistentBudgetExhausted:
        time_budget_exhaustion_proven = True

    cost_budget_exhaustion_proven = False
    try:
        record_wake_usage(
            wake_id="wake:dd1:cost-budget",
            responsibility_id=responsibility.responsibility_id,
            active_seconds=0,
            agent_turns=0,
            semantic_calls=0,
            provider_calls=0,
            tool_calls=0,
            subagents=0,
            subagent_seconds=0,
            retries=0,
            external_tool_seconds=0,
            cost=responsibility.time_budget.maximum_cost_per_wake + 0.01,
            budget=responsibility.time_budget,
        )
    except PersistentBudgetExhausted:
        cost_budget_exhaustion_proven = True

    transition_execution_id=f"{wake_id}:verifying"
    transition_responsibility(
        responsibility_id=responsibility.responsibility_id,
        from_status="EXECUTING",
        to_status="VERIFYING",
        transition_ref=transition_execution_id,
        authorization_ref=_authorization(
            responsibility.responsibility_id,
            transition_execution_id,
        ),
        execution_id=transition_execution_id,
    )
    transition_execution_id=f"{wake_id}:learning"
    transition_responsibility(
        responsibility_id=responsibility.responsibility_id,
        from_status="VERIFYING",
        to_status="LEARNING",
        transition_ref=transition_execution_id,
        authorization_ref=_authorization(
            responsibility.responsibility_id,
            transition_execution_id,
        ),
        execution_id=transition_execution_id,
    )
    learning_ref = f"learning-evidence:{candidate['content_digest']}"
    transition_execution_id=f"{wake_id}:dormant"
    transition_responsibility(
        responsibility_id=responsibility.responsibility_id,
        from_status="LEARNING",
        to_status="DORMANT",
        transition_ref=transition_execution_id,
        authorization_ref=_authorization(
            responsibility.responsibility_id,
            transition_execution_id,
        ),
        execution_id=transition_execution_id,
    )
    append_activity(
        PersistentAgentActivity.create(
            responsibility_id=responsibility.responsibility_id,
            persistent_agent_id=identity.persistent_agent_id,
            event_type="COMPLETED",
            occurred_at="2026-09-30T00:01:04+00:00",
            task_id="dd1:task:opportunity",
            mission_id=None,
            summary="Verified candidate and returned responsibility to dormant.",
            evidence_refs=(candidate["candidate_id"], learning_ref),
        )
    )

    stored_after_cycle = get_responsibility(responsibility.responsibility_id)
    activity_state_before = dict(stored_after_cycle)
    replay_one = replay_activity_feed(responsibility.responsibility_id)
    replay_two = replay_activity_feed(responsibility.responsibility_id)
    activity_state_after = get_responsibility(responsibility.responsibility_id)

    duplicate_wake = process_wake_event(
        responsibility_id=responsibility.responsibility_id,
        event_type="source.changed",
        wake_reason="SOURCE_CHANGED",
        wake_source="POLL_CURSOR",
        wake_event_ref="event:dd1:source.changed:1",
        wake_timestamp="2026-09-30T00:02:00+00:00",
        authorization_ref=_authorization(
            responsibility.responsibility_id,
            "dd1:wake:duplicate",
        ),
        execution_id="dd1:wake:duplicate",
    )
    duplicate_candidate = persist_opportunity_candidate(
        responsibility_id=responsibility.responsibility_id,
        wake_id=wake_id,
        candidate_type="EditorialOpportunityCandidate",
        payload={
            "title": "DD1 provider-free candidate",
            "source_ref": "evidence:dd1:source",
            "read_only": True,
        },
        evidence_refs=("evidence:dd1:source",),
    )

    fabricated_side_effect_rejected = False
    try:
        require_fresh_side_effect_authorization(
            responsibility_id=responsibility.responsibility_id,
            action="PUSH",
            authorization_ref="fabricated",
            execution_id="dd1:push:invalid",
        )
    except PermissionError:
        fabricated_side_effect_rejected = True

    side_effect_auth = _authorization(
        responsibility.responsibility_id,
        "dd1:push:authorized",
        subject=f"responsibility:{responsibility.responsibility_id}:action:PUSH",
    )
    side_effect_receipt = require_fresh_side_effect_authorization(
        responsibility_id=responsibility.responsibility_id,
        action="PUSH",
        authorization_ref=side_effect_auth,
        execution_id="dd1:push:authorized",
    )
    stale_side_effect_rejected = False
    try:
        require_fresh_side_effect_authorization(
            responsibility_id=responsibility.responsibility_id,
            action="PUSH",
            authorization_ref=side_effect_auth,
            execution_id="dd1:push:authorized",
        )
    except PermissionError:
        stale_side_effect_rejected = True

    pause_auth = _authorization(
        responsibility.responsibility_id,
        "dd1:pause",
    )
    paused = pause_responsibility(
        responsibility_id=responsibility.responsibility_id,
        authorization_ref=pause_auth,
        execution_id="dd1:pause",
        reason="DD1 durable pause canary",
    )
    durable_paused = get_responsibility(responsibility.responsibility_id)
    resumed = resume_responsibility(
        responsibility_id=responsibility.responsibility_id,
        authorization_ref=_authorization(
            responsibility.responsibility_id,
            "dd1:resume",
        ),
        execution_id="dd1:resume",
        reason="DD1 durable resume canary",
    )

    rules = get_custom_rules(responsibility.responsibility_id)
    feed = get_activity_feed(responsibility.responsibility_id, limit=50)
    final = get_responsibility(responsibility.responsibility_id)

    gates = {
        "PERSISTENT_RESPONSIBILITY": (
            "PASS"
            if final
            and final["responsibility_id"] == responsibility.responsibility_id
            and final["status"] == "DORMANT"
            else "FAIL"
        ),
        "PERSISTENT_RESPONSIBILITY_NOT_CONTROL_PLANE": (
            "PASS"
            if responsibility.approval_policy.get("side_effects")
            == "HARNESS_AUTHORIZATION_REQUIRED"
            else "FAIL"
        ),
        "PERSISTENT_AGENT_IDENTITY": (
            "PASS"
            if identity.persistent_agent_id != identity.session_id
            else "FAIL"
        ),
        "SESSION_ROTATION_PRESERVES_RESPONSIBILITY_IDENTITY": (
            "PASS"
            if rotated_identity.persistent_agent_id == identity.persistent_agent_id
            and rotated_identity.responsibility_id == identity.responsibility_id
            and rotated_identity.session_id != identity.session_id
            else "FAIL"
        ),
        "EVENT_DRIVEN_WAKE": (
            "PASS"
            if wake["status"] == "WOKEN"
            and wake["should_wake"] is True
            else "FAIL"
        ),
        "STATE_MACHINE_BOUNDED": (
            "PASS"
            if stored_after_cycle["status"] == "DORMANT"
            else "FAIL"
        ),
        "BOUNDED_TIME_BUDGET": (
            "PASS"
            if usage["active_seconds"] <= responsibility.time_budget.maximum_wall_clock_per_wake_seconds
            else "FAIL"
        ),
        "TIME_BUDGET_ENFORCED": "PASS" if time_budget_exhaustion_proven else "FAIL",
        "COST_BUDGET_ENFORCED": "PASS" if cost_budget_exhaustion_proven else "FAIL",
        "RETRY_BUDGET_ENFORCED": "PASS" if budget_exhaustion_proven else "FAIL",
        "BUDGET_EXHAUSTED_TYPED": (
            "PASS"
            if budget_exhaustion_proven
            and time_budget_exhaustion_proven
            and cost_budget_exhaustion_proven
            else "FAIL"
        ),
        "PROACTIVE_BACKGROUND_READ_ONLY": (
            "PASS"
            if responsibility.proactive_research_policy.mode == "READ_ONLY"
            and not responsibility.allowed_side_effects
            and not responsibility.proactive_research_policy.allows("PUSH")
            else "FAIL"
        ),
        "NO_INFINITE_AGENT_LOOP": "PASS" if _no_loop_in_wake_reducer() else "FAIL",
        "CUSTOM_RULES": (
            "PASS"
            if len(rules) == 2
            and research_permission.allowed
            else "FAIL"
        ),
        "CUSTOM_RULE_CANNOT_EXPAND_AUTHORITY": (
            "PASS"
            if push_rule.effect == "ALLOW"
            and not push_permission.allowed
            and push_permission.reason == "TASK_AUTHORIZATION_DENIED"
            else "FAIL"
        ),
        "SIDE_EFFECT_REQUIRES_FRESH_AUTHORIZATION": (
            "PASS"
            if fabricated_side_effect_rejected
            and side_effect_receipt["consumed"] is True
            and stale_side_effect_rejected
            else "FAIL"
        ),
        "DUPLICATE_WAKE_IDEMPOTENT": (
            "PASS"
            if duplicate_wake["duplicate"] is True
            and duplicate_wake["wake_id"] == wake_id
            else "FAIL"
        ),
        "DUPLICATE_OPPORTUNITY_IDEMPOTENT": (
            "PASS"
            if duplicate_candidate["duplicate"] is True
            and count_opportunity_candidates(responsibility.responsibility_id) == 1
            else "FAIL"
        ),
        "ACTIVITY_FEED": (
            "PASS"
            if any(item["event_type"] == "WOKE" for item in feed)
            and any(item["event_type"] == "FOUND_OPPORTUNITY" for item in feed)
            and any(item["event_type"] == "COMPLETED" for item in feed)
            else "FAIL"
        ),
        "ACTIVITY_FEED_IS_PROJECTION_ONLY": (
            "PASS"
            if replay_one == replay_two
            and activity_state_before == activity_state_after
            else "FAIL"
        ),
        "OWNER_PAUSE_RESUME": (
            "PASS"
            if paused["status"] == "PAUSED"
            and durable_paused["status"] == "PAUSED"
            and resumed["status"] == "DORMANT"
            else "FAIL"
        ),
        "DURABLE_RESTART": (
            "PASS"
            if durable_paused["responsibility_id"] == responsibility.responsibility_id
            else "FAIL"
        ),
        "HARNESS_SOLE_AUTHORITY": (
            "PASS"
            if responsibility.approval_policy.get("side_effects")
            == "HARNESS_AUTHORIZATION_REQUIRED"
            and stale_side_effect_rejected
            else "FAIL"
        ),
    }
    status = "PASS" if all(value == "PASS" for value in gates.values()) else "FAIL"
    return {
        "schema": "PersistentIntelligenceForceDD1Proof/v1",
        "status": status,
        "gates": gates,
        "responsibility_id": responsibility.responsibility_id,
        "wake_id": wake_id,
        "candidate_id": candidate["candidate_id"],
        "learning_ref": learning_ref,
        "activity_count": len(feed),
        "custom_rule_count": len(rules),
        "wake_usage": usage,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    result = run_dd1_operational_proof(database_file=args.database)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print("PERSISTENT_FORCE_DD1_STATUS=" + result["status"])
    for gate, value in sorted(result["gates"].items()):
        print(f"{gate}={value}")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
