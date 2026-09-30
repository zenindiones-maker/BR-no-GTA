from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from app.services.persistent_intelligence_contracts import (
    AgentCustomRule,
    PersistentAgentActivity,
    PersistentAgentIdentity,
    PersistentResponsibility,
    PersistentWorkTimeBudget,
    ProactiveResearchPolicy,
)
from app.services.persistent_intelligence_force_service import (
    evaluate_custom_rule,
    evaluate_wake,
    pause_responsibility,
    register_custom_rule,
    register_persistent_agent_identity,
    register_responsibility,
    resume_responsibility,
)
from app.database.persistent_intelligence_repository import (
    append_activity,
    get_activity_feed,
    get_custom_rules,
    get_responsibility,
    persist_custom_rule,
    record_work_usage,
)


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    monkeypatch.setenv("BR_TEST_DATABASE", str(tmp_path / "persistent-force.db"))
    from app.database.schema import initialize_schema

    initialize_schema()


def _policy() -> ProactiveResearchPolicy:
    return ProactiveResearchPolicy.from_mapping(
        {
            "policy_id": "research:default",
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
            "allowed_sources": ["PUBLIC_WEB", "OWNED_READ_ONLY_ANALYTICS"],
            "max_items_per_wake": 50,
        }
    )


def _budget() -> PersistentWorkTimeBudget:
    return PersistentWorkTimeBudget.from_mapping(
        {
            "maximum_wall_clock_per_wake_seconds": 600,
            "maximum_total_active_time_per_day_seconds": 3600,
            "maximum_agent_turns": 20,
            "maximum_semantic_calls": 12,
            "maximum_provider_calls": 12,
            "maximum_tool_calls": 30,
            "maximum_subagents": 3,
            "maximum_subagent_time_seconds": 900,
            "maximum_retries": 3,
            "maximum_external_tool_time_seconds": 1200,
            "maximum_cost_per_wake": 1.0,
            "maximum_cost_per_day": 5.0,
        }
    )


def _responsibility() -> PersistentResponsibility:
    return PersistentResponsibility.from_mapping(
        {
            "responsibility_id": "BR_CONTENT_INTELLIGENCE",
            "owner": "BR_OWNER",
            "name": "BR Content Intelligence",
            "description": "Find supported high-value editorial opportunities.",
            "business_outcome": "Create evidence-backed EditorialOpportunityCandidate records.",
            "domain": "content-intelligence",
            "task_classes": ["RESEARCH", "ANALYSIS"],
            "priority": 80,
            "enabled": True,
            "created_at": "2026-09-30T10:00:00+00:00",
            "updated_at": "2026-09-30T10:00:00+00:00",
            "trigger_policy": {"mode": "EVENT_OR_INTERVAL"},
            "proactive_research_policy": _policy().to_dict(),
            "allowed_sources": ["PUBLIC_WEB", "GTA_EVIDENCE", "YOUTUBE_PUBLIC_DATA", "OWNED_READ_ONLY_ANALYTICS"],
            "allowed_tools": ["web.search", "youtube.data.read"],
            "allowed_skills": ["research", "evidence"],
            "allowed_agents": ["domain-researcher", "architecture-analyst"],
            "allowed_side_effects": [],
            "approval_policy": {"side_effects": "HARNESS_AUTHORIZATION_REQUIRED"},
            "risk_class": "READ_ONLY_BACKGROUND",
            "time_budget": _budget().to_dict(),
            "compute_budget": {"max_parallel_tasks": 2},
            "cost_budget": {"max_cost_per_wake_usd": 1.0, "max_cost_per_day_usd": 5.0},
            "observation_interval": {"seconds": 900},
            "event_triggers": ["rockstar.source.changed", "youtube.competitor.uploaded"],
            "wake_conditions": ["EVENT_MATCH", "INTERVAL_DUE"],
            "context_policy": {"carry": ["artifact_refs", "open_questions"]},
            "memory_policy": {"write": "EVIDENCE_BOUND_ONLY"},
            "artifact_policy": {"candidate_only": True},
            "success_metrics": ["supported_opportunities_created"],
            "failure_conditions": ["UNTRUSTED_CONTENT_ESCALATION_ATTEMPT"],
            "escalation_policy": {"on_risk": "HAND_OFF_TO_HUMAN"},
            "pause_policy": {"owner_can_pause": True},
            "current_revision": 1,
            "status": "DORMANT",
        }
    )


def _auth(responsibility_id: str, execution_id: str, action: str = "EXECUTION") -> str:
    from app.services.harness_authorization_service import issue_harness_authorization

    auth = issue_harness_authorization(
        authorized_action=action,
        subject=f"responsibility:{responsibility_id}",
        execution_id=execution_id,
        lineage={"source": "persistent-force-dd1-test"},
    )
    return auth.authorization_id



def _register_responsibility() -> dict:
    responsibility = _responsibility()
    return register_responsibility(
        responsibility,
        authorization_ref=_auth(responsibility.responsibility_id, "register:responsibility:1"),
        execution_id="register:responsibility:1",
    )

def test_proactive_research_policy_is_read_only_and_rejects_side_effects():
    policy = _policy()
    assert policy.mode == "READ_ONLY"
    assert policy.allows("SEARCH") is True
    assert policy.allows("CREATE_EDITORIAL_OPPORTUNITY_CANDIDATE") is True
    assert policy.allows("PUSH") is False
    assert policy.allows("YOUTUBE_PUBLICATION") is False

    with pytest.raises(ValueError, match="read-only"):
        ProactiveResearchPolicy.from_mapping(
            {
                "policy_id": "bad",
                "mode": "READ_ONLY",
                "allowed_actions": ["READ", "PUSH"],
                "allowed_sources": ["PUBLIC_WEB"],
                "max_items_per_wake": 5,
            }
        )


def test_persistent_responsibility_has_bounded_time_and_no_background_side_effects():
    responsibility = _responsibility()
    assert responsibility.status == "DORMANT"
    assert responsibility.time_budget.maximum_wall_clock_per_wake_seconds == 600
    assert responsibility.allowed_side_effects == ()
    assert responsibility.proactive_research_policy.mode == "READ_ONLY"

    bad = responsibility.to_dict()
    bad["allowed_side_effects"] = ["github.push"]
    bad["risk_class"] = "READ_ONLY_BACKGROUND"
    with pytest.raises(ValueError, match="background"):
        PersistentResponsibility.from_mapping(bad)


def test_event_driven_wake_is_single_bounded_transition_not_infinite_loop():
    responsibility = _responsibility()

    no_work = evaluate_wake(
        responsibility,
        event_type="unrelated.event",
        interval_due=False,
        now="2026-09-30T10:05:00+00:00",
    )
    assert no_work.should_wake is False
    assert no_work.next_status == "DORMANT"
    assert no_work.dispatch_count == 0

    work = evaluate_wake(
        responsibility,
        event_type="rockstar.source.changed",
        interval_due=False,
        now="2026-09-30T10:05:00+00:00",
    )
    assert work.should_wake is True
    assert work.next_status == "WOKEN"
    assert work.dispatch_count == 1
    assert work.time_budget_seconds == 600


def test_paused_or_disabled_responsibility_never_wakes():
    responsibility = replace(_responsibility(), status="PAUSED")
    decision = evaluate_wake(
        responsibility,
        event_type="rockstar.source.changed",
        interval_due=True,
        now="2026-09-30T10:05:00+00:00",
    )
    assert decision.should_wake is False
    assert decision.reason == "RESPONSIBILITY_PAUSED"

    disabled = replace(_responsibility(), enabled=False)
    decision = evaluate_wake(
        disabled,
        event_type="rockstar.source.changed",
        interval_due=True,
        now="2026-09-30T10:05:00+00:00",
    )
    assert decision.should_wake is False
    assert decision.reason == "RESPONSIBILITY_DISABLED"


def test_register_responsibility_is_versioned_and_current_head_is_stable():
    first = _register_responsibility()
    assert first["current_revision"] == 1

    revised = replace(
        _responsibility(),
        description="Find the highest-value supported opportunities.",
        updated_at="2026-09-30T10:10:00+00:00",
        current_revision=2,
    )
    second = register_responsibility(
        revised,
        authorization_ref=_auth(revised.responsibility_id, "register:rev:2"),
        execution_id="register:rev:2",
        expected_current_revision=1,
    )
    assert second["current_revision"] == 2

    stored = get_responsibility("BR_CONTENT_INTELLIGENCE")
    assert stored["current_revision"] == 2
    assert stored["description"].startswith("Find the highest-value")

    with pytest.raises(RuntimeError, match="revision"):
        stale = replace(revised, current_revision=3)
        register_responsibility(
            stale,
            authorization_ref=_auth(stale.responsibility_id, "register:rev:3"),
            execution_id="register:rev:3",
            expected_current_revision=1,
        )


def test_persistent_agent_identity_separates_identity_instance_session_model_and_runtime():
    identity = PersistentAgentIdentity.from_mapping(
        {
            "persistent_agent_id": "agent:br-content-intelligence",
            "responsibility_id": "BR_CONTENT_INTELLIGENCE",
            "role": "domain-researcher",
            "runtime_family": "OPENAI_AGENTS_API",
            "agent_instance_id": "instance:20260930:001",
            "provider": "openai",
            "model": "gpt-6.1-sol",
            "environment_id": "env:hosted:001",
            "session_id": "sess:001",
            "revision": 1,
            "capability_profile_ref": "cap-profile:content-intelligence:v1",
            "authorization_profile_ref": "auth-profile:readonly:v1",
        }
    )
    assert identity.persistent_agent_id != identity.agent_instance_id
    assert identity.agent_instance_id != identity.session_id
    assert identity.model == "gpt-6.1-sol"

    saved = register_persistent_agent_identity(
        identity,
        authorization_ref=_auth(identity.responsibility_id, "register:identity:1"),
        execution_id="register:identity:1",
    )
    assert saved["persistent_agent_id"] == "agent:br-content-intelligence"


def test_daily_time_budget_is_durable_and_fails_closed_before_overrun():
    _register_responsibility()
    day = "2026-09-30"

    first = record_work_usage(
        responsibility_id="BR_CONTENT_INTELLIGENCE",
        usage_date=day,
        active_seconds=1200,
        agent_turns=4,
        subagent_seconds=200,
        provider_calls=3,
        external_tool_seconds=250,
        budget=_budget(),
    )
    assert first["active_seconds"] == 1200

    second = record_work_usage(
        responsibility_id="BR_CONTENT_INTELLIGENCE",
        usage_date=day,
        active_seconds=1800,
        agent_turns=3,
        subagent_seconds=300,
        provider_calls=4,
        external_tool_seconds=300,
        budget=_budget(),
    )
    assert second["active_seconds"] == 3000
    assert second["provider_calls"] == 7

    with pytest.raises(PermissionError, match="BUDGET_EXHAUSTED:daily_active_time"):
        record_work_usage(
            responsibility_id="BR_CONTENT_INTELLIGENCE",
            usage_date=day,
            active_seconds=700,
            agent_turns=1,
            subagent_seconds=0,
            provider_calls=1,
            external_tool_seconds=0,
            budget=_budget(),
        )


def test_activity_feed_is_append_only_and_typed():
    _register_responsibility()
    one = PersistentAgentActivity.create(
        responsibility_id="BR_CONTENT_INTELLIGENCE",
        persistent_agent_id="agent:br-content-intelligence",
        event_type="WOKE",
        occurred_at="2026-09-30T10:01:00+00:00",
        task_id=None,
        mission_id=None,
        summary="Woke for Rockstar source change.",
        evidence_refs=("event:rockstar:1",),
    )
    two = PersistentAgentActivity.create(
        responsibility_id="BR_CONTENT_INTELLIGENCE",
        persistent_agent_id="agent:br-content-intelligence",
        event_type="FOUND_OPPORTUNITY",
        occurred_at="2026-09-30T10:02:00+00:00",
        task_id="task:opp:1",
        mission_id=None,
        summary="Created candidate opportunity.",
        evidence_refs=("artifact:editorial-opportunity:1",),
    )
    append_activity(one)
    append_activity(two)

    feed = get_activity_feed("BR_CONTENT_INTELLIGENCE", limit=10)
    assert [item["event_type"] for item in feed] == ["WOKE", "FOUND_OPPORTUNITY"]
    assert all(item["schema"] == "PersistentAgentActivity/v1" for item in feed)

    with pytest.raises(ValueError, match="event_type"):
        PersistentAgentActivity.create(
            responsibility_id="BR_CONTENT_INTELLIGENCE",
            persistent_agent_id="agent:br-content-intelligence",
            event_type="MADE_UP_STATE",
            occurred_at="2026-09-30T10:03:00+00:00",
            task_id=None,
            mission_id=None,
            summary="bad",
            evidence_refs=(),
        )


def test_owner_pause_resume_requires_harness_authorization_and_records_activity():
    _register_responsibility()

    with pytest.raises(PermissionError):
        pause_responsibility(
            responsibility_id="BR_CONTENT_INTELLIGENCE",
            authorization_ref="fabricated",
            execution_id="pause:1",
            reason="owner requested pause",
        )

    paused = pause_responsibility(
        responsibility_id="BR_CONTENT_INTELLIGENCE",
        authorization_ref=_auth("BR_CONTENT_INTELLIGENCE", "pause:1"),
        execution_id="pause:1",
        reason="owner requested pause",
    )
    assert paused["status"] == "PAUSED"

    resumed = resume_responsibility(
        responsibility_id="BR_CONTENT_INTELLIGENCE",
        authorization_ref=_auth("BR_CONTENT_INTELLIGENCE", "resume:1"),
        execution_id="resume:1",
        reason="owner requested resume",
    )
    assert resumed["status"] == "DORMANT"

    feed = get_activity_feed("BR_CONTENT_INTELLIGENCE", limit=10)
    assert [item["event_type"] for item in feed][-2:] == ["PAUSED", "RESUMED"]


def test_agent_custom_rules_are_deterministic_and_never_grant_authority():
    rules = (
        AgentCustomRule.from_mapping(
            {
                "rule_id": "rule:public-research",
                "responsibility_id": "BR_CONTENT_INTELLIGENCE",
                "effect": "ALLOW",
                "action": "RESEARCH_PUBLIC_WEB",
                "target": "*",
                "risk_class": "LOW",
                "conditions": {},
                "revision": 1,
                "status": "ACTIVE",
            }
        ),
        AgentCustomRule.from_mapping(
            {
                "rule_id": "rule:force-push",
                "responsibility_id": "BR_CONTENT_INTELLIGENCE",
                "effect": "BLOCK",
                "action": "FORCE_PUSH",
                "target": "*",
                "risk_class": "CRITICAL",
                "conditions": {},
                "revision": 1,
                "status": "ACTIVE",
            }
        ),
    )

    allowed = evaluate_custom_rule(
        rules,
        responsibility_id="BR_CONTENT_INTELLIGENCE",
        action="RESEARCH_PUBLIC_WEB",
        target="https://rockstargames.com",
        risk_class="LOW",
    )
    assert allowed.effect == "ALLOW"
    assert allowed.grants_authority is False

    blocked = evaluate_custom_rule(
        rules,
        responsibility_id="BR_CONTENT_INTELLIGENCE",
        action="FORCE_PUSH",
        target="refs/heads/main",
        risk_class="CRITICAL",
    )
    assert blocked.effect == "BLOCK"
    assert blocked.grants_authority is False


def test_custom_rule_effects_include_human_handoff_and_preapproval_without_execution_authority():
    for effect in (
        "ALLOW",
        "PREAPPROVE_IF_EXPLICITLY_REQUESTED",
        "ASK",
        "HAND_OFF_TO_HUMAN",
        "BLOCK",
    ):
        rule = AgentCustomRule.from_mapping(
            {
                "rule_id": f"rule:{effect.lower()}",
                "responsibility_id": "BR_CONTENT_INTELLIGENCE",
                "effect": effect,
                "action": "SOME_ACTION",
                "target": "*",
                "risk_class": "MEDIUM",
                "conditions": {},
                "revision": 1,
                "status": "ACTIVE",
            }
        )
        assert rule.effect == effect



def test_custom_rules_are_persisted_versioned_and_reloaded():
    first = AgentCustomRule.from_mapping(
        {
            "rule_id": "rule:public-research",
            "responsibility_id": "BR_CONTENT_INTELLIGENCE",
            "effect": "ALLOW",
            "action": "RESEARCH_PUBLIC_WEB",
            "target": "*",
            "risk_class": "LOW",
            "conditions": {},
            "revision": 1,
            "status": "ACTIVE",
        }
    )
    persist_custom_rule(first)
    loaded = get_custom_rules("BR_CONTENT_INTELLIGENCE")
    assert len(loaded) == 1
    assert loaded[0]["rule_id"] == first.rule_id
    assert loaded[0]["revision"] == 1

    second = AgentCustomRule.from_mapping(
        {
            **first.to_dict(),
            "effect": "ASK",
            "revision": 2,
        }
    )
    persist_custom_rule(second, expected_current_revision=1)
    loaded = get_custom_rules("BR_CONTENT_INTELLIGENCE")
    assert loaded[0]["revision"] == 2
    assert loaded[0]["effect"] == "ASK"

    with pytest.raises(RuntimeError, match="revision"):
        persist_custom_rule(
            AgentCustomRule.from_mapping({**second.to_dict(), "revision": 3}),
            expected_current_revision=1,
        )



def test_governance_mutations_require_persisted_harness_authorization():
    responsibility = _responsibility()
    with pytest.raises(PermissionError):
        register_responsibility(
            responsibility,
            authorization_ref="fabricated",
            execution_id="gov:responsibility",
        )

    valid = register_responsibility(
        responsibility,
        authorization_ref=_auth(responsibility.responsibility_id, "gov:responsibility"),
        execution_id="gov:responsibility",
    )
    assert valid["responsibility_id"] == responsibility.responsibility_id

    rule = AgentCustomRule.from_mapping(
        {
            "rule_id": "rule:governance-test",
            "responsibility_id": responsibility.responsibility_id,
            "effect": "ASK",
            "action": "PUSH",
            "target": "*",
            "risk_class": "HIGH",
            "conditions": {},
            "revision": 1,
            "status": "ACTIVE",
        }
    )
    with pytest.raises(PermissionError):
        register_custom_rule(
            rule,
            authorization_ref="fabricated",
            execution_id="gov:rule",
        )

    saved_rule = register_custom_rule(
        rule,
        authorization_ref=_auth(responsibility.responsibility_id, "gov:rule"),
        execution_id="gov:rule",
    )
    assert saved_rule["rule_id"] == rule.rule_id



def _extended_budget():
    from app.services.persistent_intelligence_contracts import PersistentWorkTimeBudget

    return PersistentWorkTimeBudget.from_mapping(
        {
            "maximum_wall_clock_per_wake_seconds": 60,
            "maximum_total_active_time_per_day_seconds": 600,
            "maximum_agent_turns": 6,
            "maximum_semantic_calls": 3,
            "maximum_provider_calls": 4,
            "maximum_tool_calls": 5,
            "maximum_subagents": 2,
            "maximum_subagent_time_seconds": 120,
            "maximum_retries": 2,
            "maximum_external_tool_time_seconds": 180,
            "maximum_cost_per_wake": 1.25,
            "maximum_cost_per_day": 4.0,
        }
    )


def _lease(*, action="RESEARCH"):
    from datetime import datetime, timedelta, timezone
    from app.services.agent_office.delegation import (
        DelegatedTaskLease,
        MANDATORY_FORBIDDEN_ACTIONS,
    )

    return DelegatedTaskLease.from_mapping(
        {
            "mission_id": "mission-dd1",
            "task_id": "task-dd1",
            "goal_id": "goal-dd1",
            "harness_decision_id": "decision-dd1",
            "authorization_id": "auth-dd1",
            "delegation_id": "delegation-dd1",
            "agent_id": "agent-dd1",
            "capability_ids": ["persistent.responsibility.observe"],
            "base_sha": "a" * 40,
            "allowed_paths": [],
            "allowed_tools": ["web.search"],
            "allowed_actions": [action],
            "forbidden_actions": sorted(MANDATORY_FORBIDDEN_ACTIONS),
            "input_artifact_refs": [],
            "expected_outputs": ["OpportunityCandidate"],
            "acceptance_criteria": ["bounded result"],
            "evidence_requirements": ["evidence ref"],
            "time_budget_seconds": 60,
            "cost_budget": 1.0,
            "tool_call_budget": 5,
            "retry_budget": 1,
            "max_parallelism": 1,
            "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
            "escalation_conditions": ["budget exhausted"],
            "owned_task_class": "RESEARCH",
            "role": "domain-researcher",
            "read_set": [],
            "write_set": [],
        }
    )


def _task(*, action="RESEARCH", side_effects=()):
    from app.services.harness_collaboration_service import TaskEnvelope

    return TaskEnvelope.from_mapping(
        {
            "task_id": "task-dd1",
            "mission_id": "mission-dd1",
            "goal_id": "goal-dd1",
            "capability_id": "persistent.responsibility.observe",
            "action": action,
            "objective": "bounded persistent observation",
            "task_class": "RESEARCH",
            "functional_role": "RESEARCHER",
            "allowed_tools": ["web.search"],
            "allowed_side_effects": list(side_effects),
            "time_budget_seconds": 60,
            "cost_budget": 1.0,
            "tool_budget": 5,
            "retry_budget": 1,
            "expected_output": "OpportunityCandidate",
            "acceptance_criteria": ["bounded result"],
        }
    )


def test_state_machine_enforces_bounded_sequence_and_rejects_skips():
    from app.services.persistent_intelligence_force_service import transition_responsibility

    responsibility = _responsibility()
    register_responsibility(
        responsibility,
        authorization_ref=_auth(responsibility.responsibility_id, "state:register"),
        execution_id="state:register",
    )
    current = responsibility
    sequence = (
        "WOKEN",
        "OBSERVING",
        "TASK_CREATED",
        "EXECUTING",
        "VERIFYING",
        "LEARNING",
        "DORMANT",
    )
    for index, next_state in enumerate(sequence, 1):
        execution_id=f"transition:{index}"
        current = transition_responsibility(
            responsibility_id=current.responsibility_id,
            from_status=current.status,
            to_status=next_state,
            transition_ref=execution_id,
            authorization_ref=_auth(current.responsibility_id, execution_id),
            execution_id=execution_id,
        )
        assert current.status == next_state

    with pytest.raises(PermissionError, match="transition"):
        transition_responsibility(
            responsibility_id=current.responsibility_id,
            from_status="DORMANT",
            to_status="EXECUTING",
            transition_ref="invalid-skip",
            authorization_ref=_auth(current.responsibility_id, "invalid-skip"),
            execution_id="invalid-skip",
        )


def test_matching_wake_is_persisted_idempotently_with_provenance():
    from app.services.persistent_intelligence_force_service import process_wake_event
    from app.database.persistent_intelligence_repository import get_wake_events

    responsibility = _responsibility()
    register_responsibility(
        responsibility,
        authorization_ref=_auth(responsibility.responsibility_id, "wake:register"),
        execution_id="wake:register",
    )
    auth = _auth(responsibility.responsibility_id, "wake:event:1")
    first = process_wake_event(
        responsibility_id=responsibility.responsibility_id,
        event_type="rockstar.source.changed",
        wake_reason="OFFICIAL_SOURCE_CHANGED",
        wake_source="POLL_CURSOR",
        wake_event_ref="rockstar:event:42",
        wake_timestamp="2026-09-30T11:00:00+00:00",
        authorization_ref=auth,
        execution_id="wake:event:1",
    )
    assert first["status"] == "WOKEN"
    assert first["duplicate"] is False
    assert first["wake_reason"] == "OFFICIAL_SOURCE_CHANGED"
    assert first["wake_source"] == "POLL_CURSOR"
    assert first["wake_event_ref"] == "rockstar:event:42"

    duplicate_auth = _auth(responsibility.responsibility_id, "wake:event:2")
    duplicate = process_wake_event(
        responsibility_id=responsibility.responsibility_id,
        event_type="rockstar.source.changed",
        wake_reason="OFFICIAL_SOURCE_CHANGED",
        wake_source="POLL_CURSOR",
        wake_event_ref="rockstar:event:42",
        wake_timestamp="2026-09-30T11:00:01+00:00",
        authorization_ref=duplicate_auth,
        execution_id="wake:event:2",
    )
    assert duplicate["duplicate"] is True
    assert duplicate["wake_id"] == first["wake_id"]
    assert len(get_wake_events(responsibility.responsibility_id)) == 1


def test_irrelevant_event_does_not_persist_wake():
    from app.services.persistent_intelligence_force_service import process_wake_event
    from app.database.persistent_intelligence_repository import get_wake_events

    responsibility = _responsibility()
    register_responsibility(
        responsibility,
        authorization_ref=_auth(responsibility.responsibility_id, "wake:irrelevant:register"),
        execution_id="wake:irrelevant:register",
    )
    result = process_wake_event(
        responsibility_id=responsibility.responsibility_id,
        event_type="irrelevant.event",
        wake_reason="UNRELATED",
        wake_source="POLL_CURSOR",
        wake_event_ref="event:irrelevant:1",
        wake_timestamp="2026-09-30T11:01:00+00:00",
        authorization_ref=_auth(responsibility.responsibility_id, "wake:irrelevant"),
        execution_id="wake:irrelevant",
    )
    assert result["status"] == "DORMANT"
    assert result["should_wake"] is False
    assert get_wake_events(responsibility.responsibility_id) == []


def test_extended_wake_budget_enforces_semantic_tool_subagent_retry_and_cost_limits():
    from app.database.persistent_intelligence_repository import record_wake_usage
    from app.services.persistent_intelligence_contracts import PersistentBudgetExhausted

    budget = _extended_budget()
    first = record_wake_usage(
        wake_id="wake:budget:1",
        responsibility_id="BR_CONTENT_INTELLIGENCE",
        active_seconds=30,
        agent_turns=2,
        semantic_calls=2,
        provider_calls=2,
        tool_calls=3,
        subagents=1,
        subagent_seconds=40,
        retries=1,
        external_tool_seconds=50,
        cost=0.75,
        budget=budget,
    )
    assert first["semantic_calls"] == 2
    assert first["tool_calls"] == 3
    assert first["cost"] == pytest.approx(0.75)

    with pytest.raises(PersistentBudgetExhausted, match="BUDGET_EXHAUSTED"):
        record_wake_usage(
            wake_id="wake:budget:1",
            responsibility_id="BR_CONTENT_INTELLIGENCE",
            active_seconds=1,
            agent_turns=1,
            semantic_calls=0,
            provider_calls=0,
            tool_calls=0,
            subagents=0,
            subagent_seconds=0,
            retries=2,
            external_tool_seconds=0,
            cost=0.0,
            budget=budget,
        )

    with pytest.raises(PersistentBudgetExhausted, match="BUDGET_EXHAUSTED"):
        record_wake_usage(
            wake_id="wake:budget:2",
            responsibility_id="BR_CONTENT_INTELLIGENCE",
            active_seconds=1,
            agent_turns=1,
            semantic_calls=0,
            provider_calls=0,
            tool_calls=0,
            subagents=0,
            subagent_seconds=0,
            retries=0,
            external_tool_seconds=0,
            cost=1.26,
            budget=budget,
        )


def test_custom_rule_cannot_expand_task_or_delegated_lease_authority():
    from app.services.persistent_intelligence_force_service import resolve_effective_permission

    responsibility = _responsibility()
    rule = AgentCustomRule.from_mapping(
        {
            "rule_id": "rule:allow-push",
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
    denied = resolve_effective_permission(
        responsibility=responsibility,
        rules=(rule,),
        task=_task(action="RESEARCH"),
        lease=_lease(action="RESEARCH"),
        requested_permission="PUSH",
        target="refs/heads/work/gate6f-analytics-learning",
        risk_class="HIGH",
    )
    assert denied.allowed is False
    assert denied.reason == "TASK_AUTHORIZATION_DENIED"

    research_rule = AgentCustomRule.from_mapping(
        {
            "rule_id": "rule:allow-research",
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
    allowed = resolve_effective_permission(
        responsibility=responsibility,
        rules=(research_rule,),
        task=_task(action="RESEARCH"),
        lease=_lease(action="RESEARCH"),
        requested_permission="RESEARCH",
        target="PUBLIC_WEB",
        risk_class="LOW",
    )
    assert allowed.allowed is True
    assert allowed.reason == "INTERSECTION_ALLOWED"


def test_side_effect_requires_fresh_harness_authorization_and_reuse_fails():
    from app.services.persistent_intelligence_force_service import (
        require_fresh_side_effect_authorization,
    )
    from app.services.harness_authorization_service import issue_harness_authorization

    responsibility_id = "BR_CONTENT_INTELLIGENCE"
    with pytest.raises(PermissionError):
        require_fresh_side_effect_authorization(
            responsibility_id=responsibility_id,
            action="PUSH",
            authorization_ref="fabricated",
            execution_id="push:1",
        )

    auth = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject=f"responsibility:{responsibility_id}:action:PUSH",
        execution_id="push:1",
        lineage={"source": "dd1-side-effect-test"},
    )
    receipt = require_fresh_side_effect_authorization(
        responsibility_id=responsibility_id,
        action="PUSH",
        authorization_ref=auth.authorization_id,
        execution_id="push:1",
    )
    assert receipt["consumed"] is True

    with pytest.raises(PermissionError):
        require_fresh_side_effect_authorization(
            responsibility_id=responsibility_id,
            action="PUSH",
            authorization_ref=auth.authorization_id,
            execution_id="push:1",
        )


def test_session_rotation_preserves_persistent_identity_and_responsibility():
    responsibility = _responsibility()
    register_responsibility(
        responsibility,
        authorization_ref=_auth(responsibility.responsibility_id, "rotate:register"),
        execution_id="rotate:register",
    )
    first = PersistentAgentIdentity.from_mapping(
        {
            "persistent_agent_id": "agent:stable",
            "responsibility_id": responsibility.responsibility_id,
            "role": "domain-researcher",
            "runtime_family": "OPENAI_AGENTS_API",
            "agent_instance_id": "instance:1",
            "provider": "openai",
            "model": "gpt-6.1-sol",
            "environment_id": "env:1",
            "session_id": "session:1",
            "revision": 1,
            "capability_profile_ref": "cap:stable",
            "authorization_profile_ref": "auth:readonly",
        }
    )
    register_persistent_agent_identity(
        first,
        authorization_ref=_auth(responsibility.responsibility_id, "rotate:identity:1"),
        execution_id="rotate:identity:1",
    )
    second = PersistentAgentIdentity.from_mapping(
        {
            **first.to_dict(),
            "agent_instance_id": "instance:2",
            "session_id": "session:2",
            "revision": 2,
        }
    )
    register_persistent_agent_identity(
        second,
        authorization_ref=_auth(responsibility.responsibility_id, "rotate:identity:2"),
        execution_id="rotate:identity:2",
    )
    assert second.persistent_agent_id == first.persistent_agent_id
    assert second.responsibility_id == first.responsibility_id
    assert second.session_id != first.session_id


def test_pause_survives_restart_and_resume_keeps_same_responsibility_identity():
    responsibility = _responsibility()
    register_responsibility(
        responsibility,
        authorization_ref=_auth(responsibility.responsibility_id, "restart:register"),
        execution_id="restart:register",
    )
    paused = pause_responsibility(
        responsibility_id=responsibility.responsibility_id,
        authorization_ref=_auth(responsibility.responsibility_id, "restart:pause"),
        execution_id="restart:pause",
        reason="restart test",
    )
    assert paused["status"] == "PAUSED"

    # Simulate a process restart by resolving only from durable storage.
    reloaded = get_responsibility(responsibility.responsibility_id)
    assert reloaded["status"] == "PAUSED"
    assert reloaded["responsibility_id"] == responsibility.responsibility_id

    resumed = resume_responsibility(
        responsibility_id=responsibility.responsibility_id,
        authorization_ref=_auth(responsibility.responsibility_id, "restart:resume"),
        execution_id="restart:resume",
        reason="restart complete",
    )
    assert resumed["status"] == "DORMANT"
    assert resumed["responsibility_id"] == responsibility.responsibility_id


def test_activity_replay_is_deterministic_and_cannot_mutate_responsibility_state():
    from app.services.persistent_intelligence_force_service import replay_activity_feed

    responsibility = _responsibility()
    register_responsibility(
        responsibility,
        authorization_ref=_auth(responsibility.responsibility_id, "activity:register"),
        execution_id="activity:register",
    )
    for event_type, timestamp in (
        ("WOKE", "2026-09-30T12:00:00+00:00"),
        ("OBSERVED", "2026-09-30T12:00:01+00:00"),
        ("COMPLETED", "2026-09-30T12:00:02+00:00"),
    ):
        append_activity(
            PersistentAgentActivity.create(
                responsibility_id=responsibility.responsibility_id,
                persistent_agent_id="agent:activity",
                event_type=event_type,
                occurred_at=timestamp,
                task_id=None,
                mission_id=None,
                summary=event_type,
                evidence_refs=(f"evidence:{event_type}",),
            )
        )

    before = get_responsibility(responsibility.responsibility_id)
    first = replay_activity_feed(responsibility.responsibility_id)
    second = replay_activity_feed(responsibility.responsibility_id)
    after = get_responsibility(responsibility.responsibility_id)
    assert first == second
    assert [item["event_type"] for item in first] == ["WOKE", "OBSERVED", "COMPLETED"]
    assert before == after


def test_capability_registry_contains_bounded_persistent_observation_executor():
    from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY

    record = GLOBAL_CAPABILITY_REGISTRY.get("persistent.responsibility.observe")
    assert record is not None
    assert record.allowed_actions == ("RESEARCH",)
    assert record.side_effect_class == "LOCAL_STATE_ONLY"
    assert "DeepSeek Harness" in record.security_boundary


def test_operational_proof_is_idempotent_for_duplicate_wake_and_candidate(tmp_path):
    from scripts.persistent_intelligence_force_dd1_proof import run_dd1_operational_proof

    result = run_dd1_operational_proof(database_file=tmp_path / "dd1-operational-proof.db")
    assert result["status"] == "PASS"
    assert result["gates"]["DUPLICATE_WAKE_IDEMPOTENT"] == "PASS"
    assert result["gates"]["DUPLICATE_OPPORTUNITY_IDEMPOTENT"] == "PASS"
    assert result["gates"]["SIDE_EFFECT_REQUIRES_FRESH_AUTHORIZATION"] == "PASS"



def test_activity_append_cannot_mutate_harness_mission_state():
    from copy import deepcopy
    from app.services.harness_durable_execution_v3 import (
        DurableExecutionV3,
        MissionIdentity,
    )

    responsibility = _responsibility()
    register_responsibility(
        responsibility,
        authorization_ref=_auth(responsibility.responsibility_id, "mission-state:register"),
        execution_id="mission-state:register",
    )
    mission_state = DurableExecutionV3.mission_head(
        identity=MissionIdentity(
            mission_id="mission-dd1-activity",
            human_goal_id="goal-dd1-activity",
            lineage_id="lineage-dd1-activity",
        ),
        active_plan_ref="plans/plan.json",
        active_plan_hash="b" * 64,
        runtime_revision="dd1-runtime",
        orchestration_version="dd1",
    )
    before = deepcopy(mission_state)
    append_activity(
        PersistentAgentActivity.create(
            responsibility_id=responsibility.responsibility_id,
            persistent_agent_id="agent:activity-projection",
            event_type="OBSERVED",
            occurred_at="2026-09-30T12:30:00+00:00",
            task_id=None,
            mission_id=mission_state["mission_id"],
            summary="projection-only activity",
            evidence_refs=("evidence:projection",),
        )
    )
    assert mission_state == before
    assert get_responsibility(responsibility.responsibility_id)["status"] == "DORMANT"
