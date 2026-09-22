from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import json

import pytest

from app.services import harness_adaptive_planning_service as adaptive
from app.services import capability_health_service as capability_health_module
from app.services import provider_health_service as provider_health_module
from app.services import semantic_mission_planner_service as semantic_planner_module
from app.services.capability_health_service import (
    CapabilityHealth,
    BLOCKED,
    HEALTHY,
)
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.harness_collaboration_service import (
    TaskEnvelope,
    build_collaboration_plan,
)
from app.services.harness_mission_execution_router import (
    execute_harness_mission_plan,
    select_mission_execution_route,
)
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest,
    route_harness_request,
)
from app.services.hermes_multiagent.contracts import (
    DelegationEnvelope,
    TypedHandoff,
)
from app.services.harness_authorization_service import (
    consume_harness_authorization,
    issue_harness_authorization,
)
from app.services.harness_capability_adapter import (
    CapabilityAdapter,
    CapabilityReturnedFailure,
)
from app.services.harness_capability_service import CapabilityEvidence
from app.services.hermes_multiagent.capability_broker import (
    DelegatedCapabilityFailure,
    HermesHarnessCapabilityBroker,
)
from app.services.hermes_multiagent.runtime import (
    export_hermes_mission_checkpoint,
    restore_hermes_mission_checkpoint,
)
from app.services.hermes_multiagent.profile_factory import HermesProfileFactory
from app.services.agent_office.contracts import AgentOfficeTask
from app.services.agent_office.munder_adapter import deterministic_read_only_worker
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from scripts.audit_harness_ecosystem import audit
from scripts import dynamic_system_improvement_mission as dynamic_mission


def _competence(
    capability_id: str,
    *,
    tested: int,
    success_rate: float,
    task_class: str = "bounded-development",
) -> dict:
    return {
        "capability_id": capability_id,
        "task_class": task_class,
        "version": "1",
        "tested_cases": tested,
        "success_rate": success_rate,
        "failure_rate": max(0.0, 1.0 - success_rate),
        "human_correction_rate": 0.0,
        "retry_rate": 0.0,
        "mean_latency_seconds": 10.0,
        "mean_cost": 0.0,
        "freshness_score": 1.0,
        "confidence": 0.9,
        "status": "ACTIVE",
    }


def test_canonical_task_envelope_carries_scope_budget_review_and_idempotency():
    task = TaskEnvelope.from_mapping({
        "task_id": "inspect-cache",
        "capability_id": "gta6.knowledge.retrieve",
        "authorized_action": "RESEARCH",
        "objective": "Inspect relevant canonical knowledge without mutation",
        "task_class": "readonly-analysis",
        "required_capability_description": "bounded canonical knowledge retrieval",
        "dependencies": [],
        "input_refs": ["artifact:input-1"],
        "expected_output": "KnowledgeEvidence",
        "acceptance_criteria": ["return provenance", "stay bounded"],
        "read_scope": [],
        "write_scope": [],
        "allowed_tools": [],
        "allowed_side_effects": [],
        "forbidden_side_effects": ["publication", "canonical_memory_write"],
        "time_budget_seconds": 90,
        "cost_budget": 0.0,
        "context_budget_bytes": 8192,
        "tool_budget": 4,
        "retry_budget": 1,
        "evidence_contract": "claim/evidence provenance",
        "review_policy": "NONE",
        "risk_side_effect_class": "READ_ONLY",
        "human_gate_policy": "NONE",
    })
    first = build_collaboration_plan(
        mission_id="mission-task-envelope",
        goal_id="goal-task-envelope",
        tasks=[task],
    )
    second = build_collaboration_plan(
        mission_id="mission-task-envelope",
        goal_id="goal-task-envelope",
        tasks=[task],
    )
    routed = first.tasks[0]
    assert routed.authorized_action == "RESEARCH"
    assert routed.task_class == "readonly-analysis"
    assert routed.acceptance_criteria == ("return provenance", "stay bounded")
    assert routed.context_budget_bytes == 8192
    assert routed.tool_budget == 4
    assert routed.retry_budget == 1
    assert routed.review_policy == "NONE"
    assert routed.risk_side_effect_class == "READ_ONLY"
    assert routed.idempotency_key.startswith("task:")
    assert routed.idempotency_key == second.tasks[0].idempotency_key
    assert routed.mission_id == "mission-task-envelope"
    assert routed.goal_id == "goal-task-envelope"


def test_dynamic_mission_generic_payload_carries_semantic_query_without_capability_hardcode():
    task = TaskEnvelope.from_mapping({
        "task_id": "inspect-system",
        "capability_id": "gta6.knowledge.retrieve",
        "authorized_action": "RESEARCH",
        "objective": "Inspect architecture evidence",
        "task_class": "system-root-cause-analysis",
        "required_capability_description": (
            "bounded repository architecture evidence retrieval"
        ),
        "dependencies": [],
        "input_refs": [],
        "expected_output": "Evidence",
        "acceptance_criteria": ["return evidence"],
        "read_scope": [],
        "write_scope": [],
        "allowed_tools": [],
        "allowed_side_effects": [],
        "forbidden_side_effects": [],
        "time_budget_seconds": 90,
        "cost_budget": 0.0,
        "context_budget_bytes": 8192,
        "tool_budget": 4,
        "retry_budget": 1,
        "review_policy": "NONE",
        "risk_side_effect_class": "READ_ONLY",
        "human_gate_policy": "NONE",
    })
    payload = dynamic_mission._generic_payload(
        task=task,
        human_goal="Analyze the current system.",
        goal_id="goal-query-contract",
        mission_id="mission-query-contract",
        base_sha="a" * 40,
        branch="work/gate6f-analytics-learning",
        snapshot={},
        parent_context={},
    )
    assert payload["query"] == (
        "bounded repository architecture evidence retrieval"
    )
    assert payload["query"] == payload["gaps"][0]
    assert "capability_id" not in payload["query"]


def test_mutating_payload_consumes_only_allowlisted_parent_evidence():
    task = TaskEnvelope(
        task_id="implement-candidate",
        capability_id="agent-office.codex.bounded-development",
        action="DEVELOPMENT",
        objective="Implement the safe bounded candidate selected by the Harness.",
        dependencies=("inspect-system",),
        expected_output="Candidate",
        task_class="bounded-development",
        acceptance_criteria=("address the observed parent evidence",),
        read_scope=("app", "tests"),
        write_scope=("app/services/agent_office", "tests"),
        allowed_tools=("git", "python", "pytest", "codex", "rg", "cat", "ls"),
        risk_side_effect_class="BOUNDED_MUTATION",
    )
    parent_context = {
        "parent_handoffs": [
            {
                "task_id": "inspect-system",
                "result": {
                    "observed_gaps": [
                        "repository scan repeats the same traversal four times"
                    ],
                    "proposed_actions": [
                        "reuse one bounded traversal result for repeated local checks"
                    ],
                    "summary": "Measured duplicate local traversal in the inspected path.",
                    "performance_evidence": {
                        "metric_name": "traversals",
                        "baseline": 4,
                        "candidate": 1,
                        "unit": "count",
                        "direction": "LOWER_IS_BETTER",
                        "measurement_command": "python scripts/local_probe.py",
                        "raw_provider_payload": "MUST_NOT_LEAK",
                    },
                    "authority": "MUST_NOT_ENTER_WORKER_PROMPT",
                    "credential": "MUST_NOT_ENTER_WORKER_PROMPT",
                    "nested_arbitrary": {
                        "secret": "MUST_NOT_ENTER_WORKER_PROMPT",
                    },
                },
            }
        ],
        "evidence_refs": ["artifact:parent.json"],
    }

    payload = dynamic_mission._generic_payload(
        task=task,
        human_goal="Improve the system safely.",
        goal_id="goal-parent-guidance",
        mission_id="mission-parent-guidance",
        base_sha="a" * 40,
        branch="work/gate6f-analytics-learning",
        snapshot={},
        parent_context=parent_context,
    )

    objective = payload["objective"]
    assert "AUTHORIZED_PARENT_EVIDENCE" in objective
    assert "repository scan repeats the same traversal four times" in objective
    assert "reuse one bounded traversal result" in objective
    assert "Measured duplicate local traversal" in objective
    assert '"metric_name":"traversals"' in objective
    assert "MUST_NOT_LEAK" not in objective
    assert "MUST_NOT_ENTER_WORKER_PROMPT" not in objective
    assert len(objective) <= 3900

    readonly = replace(
        task,
        task_id="inspect-only",
        capability_id="agent-office.codex.readonly-analysis",
        write_scope=(),
        risk_side_effect_class="READ_ONLY",
    )
    readonly_payload = dynamic_mission._generic_payload(
        task=readonly,
        human_goal="Inspect only.",
        goal_id="goal-readonly-parent-guidance",
        mission_id="mission-readonly-parent-guidance",
        base_sha="a" * 40,
        branch="work/gate6f-analytics-learning",
        snapshot={},
        parent_context=parent_context,
    )
    assert "AUTHORIZED_PARENT_EVIDENCE" not in readonly_payload["objective"]


def test_hermes_profiles_are_task_scoped_when_one_specialist_owns_multiple_tasks():
    tasks = [
        TaskEnvelope(
            task_id="inspect-one",
            capability_id="agent-office.deterministic.readonly-analysis",
            action="DEVELOPMENT",
            objective="Inspect first bounded architecture concern",
            task_class="system-root-cause-analysis",
            expected_output="EvidenceOne",
            review_policy="NONE",
            risk_side_effect_class="READ_ONLY",
        ),
        TaskEnvelope(
            task_id="inspect-two",
            capability_id="agent-office.deterministic.readonly-analysis",
            action="DEVELOPMENT",
            objective="Inspect second bounded architecture concern",
            task_class="system-root-cause-analysis",
            expected_output="EvidenceTwo",
            review_policy="NONE",
            risk_side_effect_class="READ_ONLY",
        ),
    ]
    plan = build_collaboration_plan(
        mission_id="mission-shared-specialist",
        goal_id="goal-shared-specialist",
        tasks=tasks,
    )
    assert len(plan.tasks) == 2
    assert plan.tasks[0].selected_agent_id == plan.tasks[1].selected_agent_id

    factory = HermesProfileFactory()
    first = factory.project_plan(plan)
    second = factory.project_plan(plan)

    assert len({profile.profile_name for profile in first}) == 2
    assert [profile.profile_name for profile in first] == [
        profile.profile_name for profile in second
    ]
    assert [profile.task_id for profile in first] == [
        "inspect-one",
        "inspect-two",
    ]
    assert first[0].runtime_role == first[1].runtime_role
    assert first[0].canonical_agent_id == first[1].canonical_agent_id
    assert all(profile.profile_name.startswith("hermes-") for profile in first)


def test_competence_confidence_adjustment_prefers_robust_history_over_one_of_one():
    record = GLOBAL_CAPABILITY_REGISTRY.get(
        "agent-office.codex.bounded-development"
    )
    assert record is not None
    requirement = {
        "task_class": "bounded-development",
        "task_id": "bounded-change",
    }
    weak_context = {
        "competence_evidence": [
            _competence(record.capability_id, tested=1, success_rate=1.0)
        ]
    }
    strong_context = {
        "competence_evidence": [
            _competence(record.capability_id, tested=50, success_rate=46 / 50)
        ]
    }
    weak_score, _, weak = adaptive._competence_score(
        record,
        requirement=requirement,
        context=weak_context,
    )
    strong_score, _, strong = adaptive._competence_score(
        record,
        requirement=requirement,
        context=strong_context,
    )
    assert strong_score > weak_score
    assert strong["wilson_success_lower_bound"] > weak["wilson_success_lower_bound"]
    assert strong["sample_strength"] > weak["sample_strength"]
    assert weak["sample_size_interpretation"] == "LOW_CONFIDENCE"
    assert strong["sample_size_interpretation"] == "ESTABLISHED"


def test_selector_excludes_blocked_health_and_records_health_evidence(monkeypatch):
    primary = GLOBAL_CAPABILITY_REGISTRY.get(
        "agent-office.codex.readonly-analysis"
    )
    alternate = GLOBAL_CAPABILITY_REGISTRY.get(
        "agent-office.deterministic.readonly-analysis"
    )
    assert primary is not None and alternate is not None

    class FakeRegistry:
        def discover(self, **_kwargs):
            return [
                {"capability_id": primary.capability_id},
                {"capability_id": alternate.capability_id},
            ]

        def get(self, capability_id):
            return {
                primary.capability_id: primary,
                alternate.capability_id: alternate,
            }.get(capability_id)

    def health(capability_id: str):
        state = BLOCKED if capability_id == primary.capability_id else HEALTHY
        return CapabilityHealth(
            capability_id=capability_id,
            state=state,
            reason="test health",
            retry_allowed=state == HEALTHY,
            confidence=0.95,
            sample_size=20,
            last_success_at=None,
            last_failure_at=None,
            evidence_refs=("test:health",),
            source="TEST_CAPTURED",
        )

    monkeypatch.setattr(adaptive, "GLOBAL_CAPABILITY_REGISTRY", FakeRegistry())
    monkeypatch.setattr(adaptive, "capability_health", health)

    selected, _, avoided, evidence = adaptive.select_capability_for_requirement(
        {
            "task_id": "readonly",
            "task_class": "readonly-analysis",
            "action": "DEVELOPMENT",
            "query": "readonly source code analysis",
            "objective": "analyze without mutation",
            "candidate_capability_ids": [
                primary.capability_id,
                alternate.capability_id,
            ],
            "risk_side_effect_class": "READ_ONLY",
        },
        context={"competence_evidence": [], "relevant_failure_memories": []},
        used=set(),
    )
    assert selected == alternate.capability_id
    assert any(primary.capability_id in item for item in avoided)
    assert evidence["health_evidence"]["state"] == HEALTHY
    assert evidence["top_candidates"][0]["health_state"] == HEALTHY


def test_task_selection_skips_registry_executor_incompatible_with_capability_adapter(
    monkeypatch,
):
    incompatible = GLOBAL_CAPABILITY_REGISTRY.get("executor.omniroute-gateway")
    compatible = GLOBAL_CAPABILITY_REGISTRY.get(
        "agent-office.deterministic.readonly-analysis"
    )
    assert incompatible is not None and compatible is not None
    assert incompatible.execution_enabled is True
    assert adaptive.registry_executor_is_task_adapter_compatible(
        incompatible.executor_binding
    ) is False
    assert adaptive.registry_executor_is_task_adapter_compatible(
        compatible.executor_binding
    ) is True

    class Registry:
        def discover(self, **_kwargs):
            return [
                {"capability_id": incompatible.capability_id},
                {"capability_id": compatible.capability_id},
            ]

        def get(self, capability_id):
            return {
                incompatible.capability_id: incompatible,
                compatible.capability_id: compatible,
            }.get(capability_id)

    monkeypatch.setattr(adaptive, "GLOBAL_CAPABILITY_REGISTRY", Registry())
    monkeypatch.setattr(
        adaptive,
        "capability_health",
        lambda capability_id: CapabilityHealth(
            capability_id=capability_id,
            state=HEALTHY,
            reason="healthy",
            retry_allowed=True,
            confidence=1.0,
            sample_size=20,
            last_success_at=None,
            last_failure_at=None,
            evidence_refs=("test:health",),
            source="TEST",
        ),
    )

    selected, _, avoided, evidence = adaptive.select_capability_for_requirement(
        {
            "task_id": "review-and-compare",
            "task_class": "baseline-candidate-comparison",
            "action": "DEVELOPMENT",
            "query": "independent review compare baseline candidate evidence",
            "objective": "review and compare evidence without mutation",
            "candidate_capability_ids": [
                incompatible.capability_id,
                compatible.capability_id,
            ],
            "risk_side_effect_class": "READ_ONLY",
        },
        context={"competence_evidence": [], "relevant_failure_memories": []},
        used=set(),
    )

    assert selected == compatible.capability_id
    assert (
        f"{incompatible.capability_id}:task-adapter-incompatible"
        in avoided
    )
    assert evidence["selected_capability_id"] == compatible.capability_id


def test_mutating_requirement_rejects_readonly_profiler(monkeypatch):
    profiler = GLOBAL_CAPABILITY_REGISTRY.get(
        "agent-office.deterministic.readonly-analysis"
    )
    assert profiler is not None

    class Registry:
        def discover(self, **_kwargs):
            return [{"capability_id": profiler.capability_id}]

        def get(self, capability_id):
            return profiler if capability_id == profiler.capability_id else None

    monkeypatch.setattr(adaptive, "GLOBAL_CAPABILITY_REGISTRY", Registry())
    monkeypatch.setattr(
        adaptive,
        "capability_health",
        lambda capability_id: CapabilityHealth(
            capability_id=capability_id,
            state=HEALTHY,
            reason="healthy readonly profiler",
            retry_allowed=True,
            confidence=1.0,
            sample_size=20,
            last_success_at=None,
            last_failure_at=None,
            evidence_refs=("test:readonly",),
            source="TEST",
        ),
    )
    with pytest.raises(RuntimeError, match="no healthy Registry capability"):
        adaptive.select_capability_for_requirement(
            {
                "task_id": "implement",
                "task_class": "bounded-development",
                "action": "DEVELOPMENT",
                "query": "implement bounded repository change",
                "objective": "create isolated candidate",
                "candidate_capability_ids": [profiler.capability_id],
                "risk_side_effect_class": "BOUNDED_MUTATION",
            },
            context={"competence_evidence": [], "relevant_failure_memories": []},
            used=set(),
        )


def test_readonly_requirement_rejects_mutating_executor(monkeypatch):
    profiler = GLOBAL_CAPABILITY_REGISTRY.get(
        "agent-office.deterministic.readonly-analysis"
    )
    mutator = GLOBAL_CAPABILITY_REGISTRY.get(
        "agent-office.codex.bounded-development"
    )
    assert profiler is not None and mutator is not None

    class Registry:
        def discover(self, **_kwargs):
            return [
                {"capability_id": mutator.capability_id},
                {"capability_id": profiler.capability_id},
            ]

        def get(self, capability_id):
            return {
                mutator.capability_id: mutator,
                profiler.capability_id: profiler,
            }.get(capability_id)

    monkeypatch.setattr(adaptive, "GLOBAL_CAPABILITY_REGISTRY", Registry())
    monkeypatch.setattr(
        adaptive,
        "capability_health",
        lambda capability_id: CapabilityHealth(
            capability_id=capability_id,
            state=HEALTHY,
            reason="healthy",
            retry_allowed=True,
            confidence=1.0,
            sample_size=20,
            last_success_at=None,
            last_failure_at=None,
            evidence_refs=("test:health",),
            source="TEST",
        ),
    )
    selected, _, avoided, _ = adaptive.select_capability_for_requirement(
        {
            "task_id": "observe",
            "task_class": "system-observation",
            "action": "DEVELOPMENT",
            "query": "profile repository performance without mutation",
            "objective": "measure current repository state",
            "candidate_capability_ids": [
                mutator.capability_id,
                profiler.capability_id,
            ],
            "risk_side_effect_class": "READ_ONLY",
        },
        context={"competence_evidence": [], "relevant_failure_memories": []},
        used=set(),
    )
    assert selected == profiler.capability_id
    assert any(
        item == f"{mutator.capability_id}:side-effect-exceeds:read-only"
        for item in avoided
    )


def _live_tuxevil_provider_overlay(
    run_id: str,
    *,
    evidence_run_id: str | None = None,
    tool_calling: str = "PASS",
) -> str:
    evidence_run_id = evidence_run_id or run_id
    return json.dumps({
        "tuxevil": {
            "provider_id": "tuxevil",
            "state": "AVAILABLE",
            "scope": "CURRENT_GITHUB_RUN",
            "github_run_id": run_id,
            "model_id": "gemini-3-flash",
            "zero_cost_eligible": True,
            "proof": {
                "TUXEVIL_RESPONSES_API": "PASS",
                "ANTIGRAVITY_UPSTREAM_AUTH": "PASS",
                "TUXEVIL_LIVE_INFERENCE": "PASS",
                "TUXEVIL_TOOL_CALLING": tool_calling,
                "OPENAI_PLATFORM_API_KEY_REQUIRED": "NO",
            },
            "evidence_refs": [
                f"github:run:{evidence_run_id}:tuxevil-live-proof"
            ],
        }
    })


def test_tuxevil_static_health_remains_auth_required_without_runtime_proof(
    monkeypatch,
):
    monkeypatch.delenv("BR_RUNTIME_PROVIDER_HEALTH_JSON", raising=False)
    monkeypatch.setenv("GITHUB_RUN_ID", "1001")
    health = provider_health_module.provider_health("tuxevil")
    semantic = provider_health_module.semantic_provider_health()
    assert health.state == "AUTH_REQUIRED"
    assert health.zero_cost_eligible is False
    assert "tuxevil" not in semantic["eligible_zero_cost_provider_ids"]
    assert semantic["semantic_reasoning_available"] is False


def test_compact_provider_health_preserves_live_semantic_contract():
    source = {
        "semantic_reasoning_available": True,
        "eligible_zero_cost_provider_ids": ["tuxevil"],
        "providers": [
            {
                "provider_id": "tuxevil",
                "state": "AVAILABLE",
                "retry_allowed": True,
                "zero_cost_eligible": True,
            }
        ],
    }
    compact = adaptive._compact_provider_health(source)
    assert compact["semantic_reasoning_available"] is True
    assert compact["eligible_zero_cost_provider_ids"] == ["tuxevil"]
    assert compact["semantic_available"] is True
    assert compact["eligible_zero_cost"] == ["tuxevil"]


def test_tuxevil_current_run_live_proof_enables_semantic_reasoning(monkeypatch):
    monkeypatch.setenv("GITHUB_RUN_ID", "1002")
    monkeypatch.setenv(
        "BR_RUNTIME_PROVIDER_HEALTH_JSON",
        _live_tuxevil_provider_overlay("1002"),
    )
    health = provider_health_module.provider_health("tuxevil")
    semantic = provider_health_module.semantic_provider_health()
    binding = provider_health_module.runtime_provider_binding("tuxevil")
    assert health.state == "AVAILABLE"
    assert health.zero_cost_eligible is True
    assert binding is not None
    assert binding["model_id"] == "gemini-3-flash"
    assert semantic["semantic_reasoning_available"] is True
    assert "tuxevil" in semantic["eligible_zero_cost_provider_ids"]


@pytest.mark.parametrize(
    ("overlay_run_id", "evidence_run_id", "tool_calling"),
    (
        ("9999", "9999", "PASS"),
        ("1003", "9999", "PASS"),
        ("1003", "1003", "FAIL"),
    ),
)
def test_tuxevil_stale_or_fabricated_runtime_health_does_not_authorize(
    monkeypatch,
    overlay_run_id,
    evidence_run_id,
    tool_calling,
):
    monkeypatch.setenv("GITHUB_RUN_ID", "1003")
    monkeypatch.setenv(
        "BR_RUNTIME_PROVIDER_HEALTH_JSON",
        _live_tuxevil_provider_overlay(
            overlay_run_id,
            evidence_run_id=evidence_run_id,
            tool_calling=tool_calling,
        ),
    )
    assert provider_health_module.runtime_provider_binding("tuxevil") is None
    health = provider_health_module.provider_health("tuxevil")
    assert health.state == "AUTH_REQUIRED"
    assert health.zero_cost_eligible is False


def test_harness_routes_current_run_live_tuxevil_with_runtime_model(monkeypatch):
    monkeypatch.setenv("GITHUB_RUN_ID", "1004")
    monkeypatch.setenv(
        "BR_RUNTIME_PROVIDER_HEALTH_JSON",
        _live_tuxevil_provider_overlay("1004"),
    )
    decision = route_harness_request(
        HarnessRoutingRequest(
            intent="semantic mission planning proposal only",
            authorized_action="DECISION",
            domain="ai",
            goal_id="goal-live-tuxevil",
            task_class="semantic-mission-planning",
            required_capability_id="ai.reasoning.text",
            provider_required=True,
            preferred_providers=("tuxevil",),
            fallback_allowed=False,
            zero_cost_operation=True,
            learning_required=False,
        )
    )
    assert decision.selected_capability_id == "ai.reasoning.text"
    assert decision.selected_provider == "tuxevil"
    assert decision.selected_model == "gemini-3-flash"
    assert decision.policy_metadata["runtime_provider_binding_used"] is True
    assert decision.selected_provider_executor_binding == (
        "app.services.ai_provider_factory.create_ai_provider"
    )


def test_semantic_live_inference_preserves_harness_authority(monkeypatch):
    context = {
        "goal_id": "goal-live-semantic",
        "provider_health": {
            "eligible_zero_cost_provider_ids": ["tuxevil"],
        },
    }
    routing = SimpleNamespace(
        routing_id="route-live-semantic",
        selected_provider="tuxevil",
    )
    authorization = SimpleNamespace(
        authorization_id="auth-live-semantic",
        authority="DEEPSEEK_HARNESS",
    )
    evidence = SimpleNamespace(
        status="EXECUTED",
        active=True,
        error={},
        result={"text": '{"g":"ok"}', "usage": {}, "finish_reason": "stop"},
        provider="tuxevil",
        model="gemini-3-flash",
        authorization_id="auth-live-semantic",
        executor_binding="app.services.ai_provider_factory.create_ai_provider",
        latency_seconds=0.1,
        performance={},
        evidence_refs=("github:run:1005:tuxevil-live-proof",),
        authority="DEEPSEEK_HARNESS",
    )

    import app.services.harness_routing_policy_service as routing_module
    import app.services.harness_authorization_service as authorization_module
    import app.services.harness_ai_provider_service as provider_module

    monkeypatch.setattr(
        routing_module,
        "route_harness_request",
        lambda _request: routing,
    )
    monkeypatch.setattr(
        authorization_module,
        "issue_harness_authorization",
        lambda **_kwargs: authorization,
    )
    monkeypatch.setattr(
        authorization_module,
        "consume_harness_authorization",
        lambda _authorization: None,
    )
    monkeypatch.setattr(
        provider_module,
        "execute_harness_ai_generation",
        lambda **_kwargs: evidence,
    )

    raw, provider_evidence = semantic_planner_module._live_inference(
        "planner prompt",
        context,
    )
    assert raw == '{"g":"ok"}'
    assert provider_evidence["provider"] == "tuxevil"
    assert provider_evidence["authority"] == "DEEPSEEK_HARNESS"
    assert provider_evidence["planner_authority"] == "NONE"


def test_semantic_schema_replan_rejects_invalid_uncertainty_type_without_coercion(
    monkeypatch,
):
    invalid = {
        "interpreted_goal": "inspect repository safely",
        "assumptions": [],
        "required_outcomes": ["bounded observation"],
        "tasks": [
            {
                "task_id": "observe",
                "objective": "Inspect current repository evidence",
                "task_class": "readonly-analysis",
                "required_capability_description": "bounded repository analysis",
                "candidate_capability_ids": [],
                "dependencies": [],
                "expected_output": "analysis evidence",
                "acceptance_criteria": ["stay read only"],
                "risk_side_effect_class": "READ_ONLY",
                "action": "DEVELOPMENT",
            }
        ],
        "rationale": "observe before mutation",
        "context_usage_notes": [],
        "uncertainty": [0.2],
        "needs_human_clarification": False,
        "clarification_question": None,
        "memory_strategy_notes": [],
        "reused_artifact_refs": [],
        "avoided_bad_paths": [],
    }
    valid = dict(invalid)
    valid["uncertainty"] = 0.2

    with pytest.raises(ValueError, match="uncertainty must be numeric"):
        semantic_planner_module.MissionPlanProposal.from_mapping(
            invalid,
            max_tasks=4,
        )

    prompts = []
    def inference(prompt, _context):
        prompts.append(prompt)
        return invalid if len(prompts) == 1 else valid

    monkeypatch.setattr(
        adaptive,
        "proposal_registry_errors",
        lambda _proposal: (),
    )
    result, evidence = adaptive.propose_validated_semantic_plan(
        {
            "human_goal": "Inspect repository and plan safely",
            "resource_bounds": {"max_tasks_per_mission": 4},
        },
        inference=inference,
        max_replans=1,
    )

    assert result.proposal.uncertainty == 0.2
    assert evidence["proposal_attempts"] == 2
    assert evidence["replan_count"] == 1
    assert len(prompts) == 2
    assert "u is exactly one JSON number in 0..1" in prompts[0]
    assert "uncertainty must be numeric" in prompts[1]
    assert "u must be exactly one JSON number in 0..1" in prompts[1]


def test_semantic_schema_replan_rejects_invalid_task_id_without_normalizing(
    monkeypatch,
):
    invalid = {
        "interpreted_goal": "inspect repository safely",
        "assumptions": [],
        "required_outcomes": ["bounded observation"],
        "tasks": [
            {
                "task_id": "T1_Observe_BR_no_GTA",
                "objective": "Inspect current repository evidence",
                "task_class": "readonly-analysis",
                "required_capability_description": "bounded repository analysis",
                "candidate_capability_ids": [],
                "dependencies": [],
                "expected_output": "analysis evidence",
                "acceptance_criteria": ["stay read only"],
                "risk_side_effect_class": "READ_ONLY",
                "action": "DEVELOPMENT",
            }
        ],
        "rationale": "observe before mutation",
        "context_usage_notes": [],
        "uncertainty": 0.2,
        "needs_human_clarification": False,
        "clarification_question": None,
        "memory_strategy_notes": [],
        "reused_artifact_refs": [],
        "avoided_bad_paths": [],
    }
    valid = {
        **invalid,
        "tasks": [
            {
                **invalid["tasks"][0],
                "task_id": "t1_observe_br_no_gta",
            }
        ],
    }

    with pytest.raises(ValueError, match="invalid task_id"):
        semantic_planner_module.MissionPlanProposal.from_mapping(
            invalid,
            max_tasks=4,
        )

    prompts = []
    def inference(prompt, _context):
        prompts.append(prompt)
        return invalid if len(prompts) == 1 else valid

    monkeypatch.setattr(
        adaptive,
        "proposal_registry_errors",
        lambda _proposal: (),
    )
    result, evidence = adaptive.propose_validated_semantic_plan(
        {
            "human_goal": "Inspect repository and plan safely",
            "resource_bounds": {"max_tasks_per_mission": 4},
        },
        inference=inference,
        max_replans=1,
    )

    assert result.proposal.tasks[0].task_id == "t1_observe_br_no_gta"
    assert evidence["proposal_attempts"] == 2
    assert evidence["replan_count"] == 1
    assert "^[a-z0-9][a-z0-9._-]{0,79}$" in prompts[0]
    assert "invalid task_id" in prompts[1]
    assert "task id must be lowercase" in prompts[1]


def test_semantic_registry_mismatch_replans_to_harness_selected_capability(
    monkeypatch,
):
    invalid = {
        "interpreted_goal": "inspect repository safely",
        "assumptions": [],
        "required_outcomes": ["bounded observation"],
        "tasks": [
            {
                "task_id": "observe",
                "objective": "Inspect current repository evidence",
                "task_class": "readonly-analysis",
                "required_capability_description": "",
                "candidate_capability_ids": [
                    "agent-office.deterministic.readonly-analysis"
                ],
                "dependencies": [],
                "expected_output": "analysis evidence",
                "acceptance_criteria": ["stay bounded"],
                "risk_side_effect_class": "READ_ONLY",
                "action": "RESEARCH",
            }
        ],
        "rationale": "observe before mutation",
        "context_usage_notes": [],
        "uncertainty": 0.2,
        "needs_human_clarification": False,
        "clarification_question": None,
        "memory_strategy_notes": [],
        "reused_artifact_refs": [],
        "avoided_bad_paths": [],
    }
    valid = {
        **invalid,
        "tasks": [
            {
                **invalid["tasks"][0],
                "required_capability_description": (
                    "bounded read-only repository analysis"
                ),
                "candidate_capability_ids": [],
                "action": "DEVELOPMENT",
            }
        ],
    }

    prompts = []
    def inference(prompt, _context):
        prompts.append(prompt)
        return invalid if len(prompts) == 1 else valid

    def registry_errors(proposal):
        task = proposal.tasks[0]
        if task.candidate_capability_ids:
            return (
                "observe: action RESEARCH not allowed by "
                "agent-office.deterministic.readonly-analysis",
            )
        return ()

    monkeypatch.setattr(adaptive, "proposal_registry_errors", registry_errors)
    result, evidence = adaptive.propose_validated_semantic_plan(
        {
            "human_goal": "Inspect repository and plan safely",
            "resource_bounds": {"max_tasks_per_mission": 4},
        },
        inference=inference,
        max_replans=1,
    )

    assert result.proposal.tasks[0].candidate_capability_ids == ()
    assert result.proposal.tasks[0].action == "DEVELOPMENT"
    assert evidence["proposal_attempts"] == 2
    assert evidence["replan_count"] == 1
    assert "Prefer caps=[]" in prompts[0]
    assert "action RESEARCH not allowed" in prompts[1]
    assert "candidate_capability_ids=[]" in prompts[1]
    assert "DeepSeek Harness performs final Registry selection" in prompts[1]


def test_final_replan_discards_registered_incompatible_hint_and_preserves_harness_selection(
    monkeypatch,
):
    invalid = {
        "interpreted_goal": "inspect repository safely",
        "assumptions": [],
        "required_outcomes": ["bounded observation"],
        "tasks": [
            {
                "task_id": "analyze-repo",
                "objective": "Inspect current repository evidence",
                "task_class": "readonly-analysis",
                "required_capability_description": "",
                "candidate_capability_ids": [
                    "agent-office.deterministic.readonly-analysis"
                ],
                "dependencies": [],
                "expected_output": "analysis evidence",
                "acceptance_criteria": ["stay bounded"],
                "risk_side_effect_class": "READ_ONLY",
                "action": "RESEARCH",
            }
        ],
        "rationale": "observe before mutation",
        "context_usage_notes": [],
        "uncertainty": 0.2,
        "needs_human_clarification": False,
        "clarification_question": None,
        "memory_strategy_notes": [],
        "reused_artifact_refs": [],
        "avoided_bad_paths": [],
    }
    prompts = []

    def inference(prompt, _context):
        prompts.append(prompt)
        return invalid

    def registry_errors(proposal):
        task = proposal.tasks[0]
        if task.candidate_capability_ids:
            return (
                "analyze-repo: action RESEARCH not allowed by "
                "agent-office.deterministic.readonly-analysis",
            )
        return ()

    monkeypatch.setattr(adaptive, "proposal_registry_errors", registry_errors)
    result, evidence = adaptive.propose_validated_semantic_plan(
        {
            "human_goal": "Inspect repository and plan safely",
            "resource_bounds": {"max_tasks_per_mission": 4},
        },
        inference=inference,
        max_replans=1,
    )

    task = result.proposal.tasks[0]
    assert len(prompts) == 2
    assert task.candidate_capability_ids == ()
    assert task.required_capability_description == task.objective
    assert evidence["candidate_hints_discarded"] == [
        "analyze-repo:agent-office.deterministic.readonly-analysis"
    ]
    assert evidence["planner_authority"] == "NONE"
    assert evidence["selection_authority"] == "DEEPSEEK_HARNESS"
    assert evidence["validated_by"] == "DEEPSEEK_HARNESS"


def test_operational_proof_installs_pinned_hermes_runtime_dependencies():
    operational = Path(
        ".github/workflows/delegation-plane-operational-proof.yml"
    ).read_text(encoding="utf-8")
    manifest_path = "config/delegation-plane-preflight-extra-requirements.txt"
    manifest = Path(manifest_path).read_text(encoding="utf-8")
    proven = Path(
        ".github/workflows/hermes-real-agent-synergy.yml"
    ).read_text(encoding="utf-8")
    assert f"-r {manifest_path}" in operational
    for requirement in (
        "psutil==7.2.2",
        "pyyaml==6.0.3",
        "python-dotenv==1.2.2",
        "rich==14.3.3",
        "pathspec==1.1.1",
    ):
        assert requirement in manifest
        assert requirement in proven


def test_natural_goal_plan_uses_canonical_learning_competence_api():
    source = Path(
        "scripts/delegation_plane_natural_goal_plan.py"
    ).read_text(encoding="utf-8")
    assert "list_competence_profiles" not in source
    assert "learning_repository.list_competence(" in source
    assert 'status="ACTIVE"' in source


def test_bounded_development_normalizes_low_risk_to_bounded_mutation():
    assert adaptive.effective_required_side_effect_class(
        task_class="bounded-development",
        declared="LOW",
    ) == "BOUNDED_MUTATION"
    assert adaptive.effective_required_side_effect_class(
        task_class="readonly-analysis",
        declared="READ_ONLY",
    ) == "READ_ONLY"


def test_bounded_development_rejects_readonly_candidate_before_handoff(
    monkeypatch,
):
    profiler = GLOBAL_CAPABILITY_REGISTRY.get(
        "agent-office.deterministic.readonly-analysis"
    )
    bounded = GLOBAL_CAPABILITY_REGISTRY.get(
        "agent-office.codex.bounded-development"
    )
    assert profiler is not None and bounded is not None

    class Registry:
        def discover(self, **_kwargs):
            return [
                {"capability_id": profiler.capability_id},
                {"capability_id": bounded.capability_id},
            ]

        def get(self, capability_id):
            return {
                profiler.capability_id: profiler,
                bounded.capability_id: bounded,
            }.get(capability_id)

        def all(self):
            return [profiler, bounded]

    monkeypatch.setattr(adaptive, "GLOBAL_CAPABILITY_REGISTRY", Registry())
    monkeypatch.setattr(
        adaptive,
        "capability_health",
        lambda capability_id: CapabilityHealth(
            capability_id=capability_id,
            state=HEALTHY,
            reason="current-run test health",
            retry_allowed=True,
            confidence=1.0,
            sample_size=1,
            last_success_at=None,
            last_failure_at=None,
            evidence_refs=("test:bounded-development",),
            source="TEST",
        ),
    )

    selected, _, avoided, _ = adaptive.select_capability_for_requirement(
        {
            "task_id": "candidate",
            "task_class": "bounded-development",
            "action": "DEVELOPMENT",
            "query": "implement bounded candidate in isolated worktree",
            "objective": "implement candidate",
            "candidate_capability_ids": [profiler.capability_id],
            "risk_side_effect_class": "LOW",
        },
        context={"competence_evidence": [], "relevant_failure_memories": []},
        used=set(),
    )
    assert selected == bounded.capability_id
    assert (
        f"{profiler.capability_id}:side-effect-insufficient:read_only"
        in avoided
    )


def test_runtime_health_preflight_blocks_unavailable_codex(monkeypatch):
    monkeypatch.setenv(
        "BR_RUNTIME_CAPABILITY_HEALTH_JSON",
        """{
          "agent-office.codex.bounded-development": {
            "state": "BLOCKED",
            "reason": "OPENAI_FEDERATION_RULE_ID and OPENAI_FEDERATION_AUDIENCE missing",
            "retry_allowed": false,
            "confidence": 1.0,
            "evidence_refs": ["github:run:35684698046"]
          }
        }""",
    )
    health = capability_health_module.capability_health(
        "agent-office.codex.bounded-development"
    )
    assert health.state == BLOCKED
    assert health.retry_allowed is False
    assert health.confidence == 1.0
    assert health.source == "RUNTIME_PREFLIGHT"
    assert health.evidence_refs == ("github:run:35684698046",)
    assert "OPENAI_FEDERATION_RULE_ID" in health.reason


def test_selector_reports_no_healthy_write_executor_when_only_write_candidate_is_blocked(
    monkeypatch,
):
    bounded = GLOBAL_CAPABILITY_REGISTRY.get(
        "agent-office.codex.bounded-development"
    )
    assert bounded is not None

    class WriteOnlyRegistry:
        def discover(self, **_kwargs):
            return [{"capability_id": bounded.capability_id}]

        def get(self, capability_id):
            return bounded if capability_id == bounded.capability_id else None

    monkeypatch.setenv(
        "BR_RUNTIME_CAPABILITY_HEALTH_JSON",
        """{
          "agent-office.codex.bounded-development": {
            "state": "BLOCKED",
            "reason": "current runner has no configured workload identity",
            "retry_allowed": false,
            "confidence": 1.0,
            "evidence_refs": ["github:run:35684698046"]
          }
        }""",
    )
    monkeypatch.setattr(adaptive, "GLOBAL_CAPABILITY_REGISTRY", WriteOnlyRegistry())

    with pytest.raises(RuntimeError, match="no healthy Registry capability"):
        adaptive.select_capability_for_requirement(
            {
                "task_id": "bounded-change",
                "task_class": "bounded-development",
                "action": "DEVELOPMENT",
                "query": "bounded code mutation candidate implementation",
                "objective": "create a bounded code candidate",
                "candidate_capability_ids": [bounded.capability_id],
                "risk_side_effect_class": "BOUNDED_MUTATION",
            },
            context={"competence_evidence": [], "relevant_failure_memories": []},
            used=set(),
        )


def test_selector_excludes_execution_topology_from_task_capability(monkeypatch):
    office = GLOBAL_CAPABILITY_REGISTRY.get("agent-office.execute")
    hermes = GLOBAL_CAPABILITY_REGISTRY.get("collaboration.hermes.execute")
    profiler = GLOBAL_CAPABILITY_REGISTRY.get(
        "agent-office.deterministic.readonly-analysis"
    )
    assert office is not None and hermes is not None and profiler is not None

    class Registry:
        def discover(self, **_kwargs):
            return [
                {"capability_id": office.capability_id},
                {"capability_id": hermes.capability_id},
                {"capability_id": profiler.capability_id},
            ]

        def get(self, capability_id):
            return {
                office.capability_id: office,
                hermes.capability_id: hermes,
                profiler.capability_id: profiler,
            }.get(capability_id)

    monkeypatch.setattr(adaptive, "GLOBAL_CAPABILITY_REGISTRY", Registry())
    monkeypatch.setattr(
        adaptive,
        "capability_health",
        lambda capability_id: CapabilityHealth(
            capability_id=capability_id,
            state=HEALTHY,
            reason="test",
            retry_allowed=True,
            confidence=1.0,
            sample_size=20,
            last_success_at=None,
            last_failure_at=None,
            evidence_refs=("test:health",),
            source="TEST",
        ),
    )
    selected, _, avoided, evidence = adaptive.select_capability_for_requirement(
        {
            "task_id": "profile",
            "task_class": "system-observation",
            "action": "DEVELOPMENT",
            "query": "deterministic repository performance profiling observability",
            "objective": "measure repository architecture without mutation",
            "candidate_capability_ids": [
                office.capability_id,
                hermes.capability_id,
                profiler.capability_id,
            ],
            "risk_side_effect_class": "READ_ONLY",
        },
        context={"competence_evidence": [], "relevant_failure_memories": []},
        used=set(),
    )
    assert selected == profiler.capability_id
    assert any(
        "agent-office.execute:execution-topology-not-task-capability" == item
        for item in avoided
    )
    assert any(
        "collaboration.hermes.execute:execution-topology-not-task-capability" == item
        for item in avoided
    )
    assert evidence["selected_capability_id"] == profiler.capability_id


def test_addy_health_follows_opencode_circuit_breaker(monkeypatch):
    addy = GLOBAL_CAPABILITY_REGISTRY.get("addy:performance-optimization")
    assert addy is not None
    assert addy.health_policy == "OPENCODE_REQUIRED"

    class ProviderState:
        state = "UPSTREAM_DENIED"
        reason = "OpenCode free-tier admission blocked upstream"
        retry_allowed = False
        evidence_refs = ("github:run:blocked-opencode",)

    monkeypatch.setattr(
        capability_health_module,
        "provider_health",
        lambda provider_id: ProviderState(),
    )
    health = capability_health_module.capability_health(addy.capability_id)
    assert health.state == BLOCKED
    assert health.retry_allowed is False
    assert health.source == "PROVIDER_HEALTH"
    assert "OpenCode" in health.reason


def test_deterministic_agent_office_profiler_emits_real_repository_metrics(tmp_path):
    import subprocess

    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "-C", str(root), "init"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(root), "config", "user.email", "test@example.com"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(root), "config", "user.name", "Test"],
        check=True,
    )
    (root / "app").mkdir()
    (root / "scripts").mkdir()
    (root / "app" / "large.py").write_text(
        "\n".join(f"line_{index} = {index}" for index in range(1100)) + "\n",
        encoding="utf-8",
    )
    (root / "scripts" / "small.py").write_text("value = 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-m", "fixture"], check=True)

    task = AgentOfficeTask.from_mapping({
        "task_id": "profile-repo",
        "agent": "deterministic-analysis",
        "capability": "agent-office.deterministic.readonly-analysis",
        "action": "analyze",
        "objective": "profile repository concentration",
        "allowed_tools": ["git"],
        "allowed_actions": ["analyze", "inspect"],
        "read_set": ["app", "scripts"],
        "write_set": [],
    })
    result = deterministic_read_only_worker(task, root, 30.0)
    assert result["status"] == "SUCCEEDED"
    analysis = result["analysis"]
    assert analysis["scoped_file_count"] == 2
    assert analysis["total_lines"] >= 1101
    assert analysis["files_over_1000_lines"] == 1
    assert analysis["largest_files"][0]["path"] == "app/large.py"
    assert analysis["observed_fragilities"][0]["kind"] == "LARGE_MODULE_CONCENTRATION"
    assert analysis["profile_latency_ms"] >= 0
    assert result["commands"] == ["git ls-files"]


def test_hermes_subordinate_check_requires_harness_authority_and_bounded_evidence():
    spec = SimpleNamespace(authority="DELEGATED_ONLY")
    canonical = {
        "authority": "deepseek_harness",
        "evidence": {
            "hermes_authority": "DELEGATED_ONLY",
            "global_registry_canonical": True,
            "canonical_memory": False,
            "publication_authority": "NONE",
        },
    }
    assert dynamic_mission._hermes_subordinate_proven(
        canonical,
        spec=spec,
    ) is True

    expanded = {
        **canonical,
        "evidence": {
            **canonical["evidence"],
            "hermes_authority": "DEEPSEEK_HARNESS",
        },
    }
    assert dynamic_mission._hermes_subordinate_proven(
        expanded,
        spec=spec,
    ) is False

    publisher = {
        **canonical,
        "evidence": {
            **canonical["evidence"],
            "publication_authority": "PUBLIC",
        },
    }
    assert dynamic_mission._hermes_subordinate_proven(
        publisher,
        spec=spec,
    ) is False


def test_capability_adapter_rejects_failed_capability_evidence(
    monkeypatch,
):
    record = GLOBAL_CAPABILITY_REGISTRY.get(
        "agent-office.deterministic.readonly-analysis"
    )
    assert record is not None

    task = TaskEnvelope.from_mapping({
        "task_id": "observe-failure",
        "capability_id": record.capability_id,
        "authorized_action": "DEVELOPMENT",
        "objective": "observe executor failure boundary",
        "task_class": "readonly-analysis",
        "required_capability_description": "read-only analysis",
        "dependencies": [],
        "input_refs": [],
        "expected_output": "Evidence",
        "acceptance_criteria": ["fail closed"],
        "read_scope": list(record.default_read_scope),
        "write_scope": [],
        "allowed_tools": list(record.allowed_tools),
        "allowed_side_effects": [],
        "forbidden_side_effects": ["publication"],
        "time_budget_seconds": 60,
        "cost_budget": 0.0,
        "context_budget_bytes": 4096,
        "tool_budget": 4,
        "retry_budget": 0,
        "evidence_contract": str(record.evidence_contract or ""),
        "review_policy": "NONE",
        "risk_side_effect_class": "READ_ONLY",
        "human_gate_policy": "NONE",
    })

    def executor(*, authorization, routing_decision, payload):
        return CapabilityEvidence(
            capability_id=record.capability_id,
            provider=record.provider,
            status="FAILED",
            active=False,
            authority=authorization.authority,
            authorized_action=authorization.authorized_action,
            harness_decision_id=authorization.harness_decision_id,
            execution_id=authorization.execution_id,
            result={"errors": ["bounded worker produced no candidate patch"]},
            boundary=record.security_boundary,
        )

    adapter = CapabilityAdapter()
    monkeypatch.setattr(adapter, "resolve_binding", lambda _binding: executor)
    decision = SimpleNamespace(
        selected_capability_id=record.capability_id,
        selected_executor_binding=record.executor_binding,
        routing_id="route-failed-evidence",
    )
    authorization = issue_harness_authorization(
        authorized_action="DEVELOPMENT",
        subject=f"capability:{record.capability_id}",
        harness_decision_id="decision-failed-evidence",
        execution_id="execution-failed-evidence",
    )
    try:
        with pytest.raises(
            CapabilityReturnedFailure,
            match="bounded worker produced no candidate patch",
        ):
            adapter.execute(
                authorization=authorization,
                task_envelope=task,
                routing_decision=decision,
                payload={},
            )
    finally:
        consume_harness_authorization(authorization)


def test_bounded_development_prompt_requires_non_empty_candidate_patch():
    source = Path(
        "app/services/agent_office/codex_bounded_worker.py"
    ).read_text(encoding="utf-8")
    assert "successful completion requires a " in source
    assert "non-empty candidate patch entirely inside WRITE_SET" in source
    assert "report a blocker instead of claiming success" in source
    assert "Do NOT commit" in source


def test_system_improvement_gates_require_measured_profiler_evidence():
    profile = {
        "metric_schema": "agent-office-repository-profile/v1",
        "scoped_file_count": 42,
        "total_lines": 12345,
        "total_bytes": 987654,
        "files_over_1000_lines": 2,
        "largest_file_lines": 1900,
        "largest_file_share_of_scoped_lines": 0.1539,
        "profile_latency_ms": 12.5,
        "inventory_sha256": "a" * 64,
        "observed_fragilities": [{
            "kind": "LARGE_MODULE_CONCENTRATION",
            "metric": "files_over_1000_lines",
            "value": 2,
            "evidence": ["app/a.py", "scripts/b.py"],
        }],
    }
    nested = {
        "result": {
            "per_agent_results": {
                "deterministic-analysis": {"analysis": profile}
            }
        }
    }
    profiles = dynamic_mission._repository_profiles(nested)
    assert profiles == [profile]
    fragilities = dynamic_mission._observed_fragilities(profiles)
    assert fragilities[0]["kind"] == "LARGE_MODULE_CONCENTRATION"
    gaps = dynamic_mission._grounded_profile_gaps({
        "parent_handoffs": [{"result": nested}]
    })
    assert any("Measured repository baseline" in item for item in gaps)
    assert any("LARGE_MODULE_CONCENTRATION" in item for item in gaps)


def test_registry_execution_contract_is_single_and_exposes_execution_metadata():
    records = [
        record
        for record in GLOBAL_CAPABILITY_REGISTRY.all()
        if record.capability_type != "PROVIDER" and record.execution_enabled
    ]
    assert records
    for record in records:
        assert isinstance(record.supports_parallelism, bool)
        assert isinstance(record.supports_retry, bool)
        assert isinstance(record.supports_resume, bool)
        assert isinstance(record.supports_review, bool)
        assert record.side_effect_class
        assert record.health_policy
    assert len({
        record.capability_id for record in GLOBAL_CAPABILITY_REGISTRY.all()
    }) == len(GLOBAL_CAPABILITY_REGISTRY.all())


def test_ecosystem_has_no_second_capability_authority():
    result = audit()
    assert result["authority"] == "DEEPSEEK_HARNESS"
    assert result["NO_DUPLICATE_AUTHORITY"] is True
    assert all(
        row["AUTHORITY_LEVEL"] in {"INHERITED", "NONE", "DELEGATED_ONLY"}
        for row in result["capabilities"]
    )


def _mission_plan_for_route(*tasks: TaskEnvelope, mission_class: str = "OPEN_SEMANTIC"):
    collaboration = build_collaboration_plan(
        mission_id="mission-route-test",
        goal_id="goal-route-test",
        tasks=list(tasks),
    )
    return {
        "authority": "DEEPSEEK_HARNESS",
        "goal": {
            "goal_id": "goal-route-test",
            "human_goal": "route this work",
            "mission_class": mission_class,
        },
        "collaboration_plan": collaboration.to_dict(),
    }


def test_topology_simple_task_avoids_hermes():
    plan = _mission_plan_for_route(TaskEnvelope(
        task_id="retrieve",
        capability_id="gta6.knowledge.retrieve",
        action="RESEARCH",
        objective="Retrieve bounded existing GTA6 knowledge",
        task_class="readonly-retrieval",
        expected_output="KnowledgeEvidence",
        review_policy="NONE",
    ))
    route = select_mission_execution_route(plan)
    assert route.runtime == "DIRECT_CAPABILITY"
    assert route.hermes_used is False
    assert route.coordination_benefit is False


def test_topology_parallel_readonly_uses_light_hermes_coordination():
    plan = _mission_plan_for_route(
        TaskEnvelope(
            task_id="retrieve-a",
            capability_id="gta6.knowledge.retrieve",
            action="RESEARCH",
            objective="Retrieve knowledge A",
            task_class="readonly-retrieval",
            expected_output="KnowledgeEvidence",
            review_policy="NONE",
        ),
        TaskEnvelope(
            task_id="retrieve-b",
            capability_id="gta6.knowledge.retrieve",
            action="RESEARCH",
            objective="Retrieve knowledge B",
            task_class="readonly-retrieval",
            expected_output="KnowledgeEvidence",
            review_policy="NONE",
        ),
    )
    route = select_mission_execution_route(plan)
    assert route.runtime == "HERMES_COLLABORATION"
    assert route.hermes_used is True
    assert route.coordination_benefit is True
    assert route.durable is False


def test_topology_dependency_or_review_uses_durable_hermes_kanban():
    plan = _mission_plan_for_route(
        TaskEnvelope(
            task_id="analyze",
            capability_id="agent-office.codex.readonly-analysis",
            action="DEVELOPMENT",
            objective="Analyze a bounded system problem",
            task_class="root-cause-analysis",
            expected_output="AnalysisEvidence",
            review_policy="NONE",
        ),
        TaskEnvelope(
            task_id="change",
            capability_id="agent-office.codex.bounded-development",
            action="DEVELOPMENT",
            objective="Create a bounded candidate",
            task_class="bounded-development",
            dependencies=("analyze",),
            expected_output="CandidateEvidence",
            write_scope=("app",),
            review_policy="INDEPENDENT_REQUIRED",
            risk_side_effect_class="BOUNDED_MUTATION",
        ),
    )
    route = select_mission_execution_route(plan)
    assert route.runtime == "HERMES_KANBAN"
    assert route.hermes_used is True
    assert route.durable is True
    assert route.has_dependencies is True


class _FakeHermesBoard:
    def __init__(self):
        self.created = []
        self.comments = []

    def find_task_by_idempotency_key(self, idempotency_key):
        for item in self.created:
            if item.get("idempotency_key") == idempotency_key:
                return dict(item)
        return None

    def create_task(self, **kwargs):
        task_id = f"board-{len(self.created) + 1}"
        self.created.append({"id": task_id, **kwargs})
        return task_id

    def comment(self, task_id, *, author, body):
        self.comments.append({"task_id": task_id, "author": author, "body": body})
        return len(self.comments)


def _delegation_fixture():
    plan = build_collaboration_plan(
        mission_id="mission-delegation-envelope",
        goal_id="goal-delegation-envelope",
        tasks=[
            TaskEnvelope(
                task_id="profile",
                capability_id="agent-office.codex.readonly-analysis",
                action="DEVELOPMENT",
                objective="profile application performance bottleneck",
                task_class="performance-profiling",
                expected_output="ProfileEvidence",
                read_scope=("app", "scripts"),
                write_scope=(),
                allowed_tools=("git", "python", "pytest", "codex", "rg", "cat"),
                allowed_side_effects=(
                    "ephemeral worktree",
                    "structured runtime artifact",
                ),
                time_budget_seconds=300,
                context_budget_bytes=16384,
                tool_budget=12,
                retry_budget=1,
                review_policy="NONE",
            )
        ],
    )
    parent = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject="capability:collaboration.hermes.execute",
        harness_decision_id="decision-delegation-envelope",
        execution_id="execution-delegation-envelope",
        lineage={"test": "delegation-envelope"},
    )
    envelope = DelegationEnvelope.from_plan(
        collaboration_plan=plan,
        harness_decision_id="decision-delegation-envelope",
        authorization_id=parent.authorization_id,
        base_sha="a" * 40,
        expires_at=(
            datetime.now(timezone.utc) + timedelta(minutes=15)
        ).isoformat(),
        max_child_depth=2,
        max_child_tasks=3,
    )
    return plan, parent, envelope


def test_delegation_envelope_blocks_authority_scope_and_budget_expansion():
    _plan, parent_auth, envelope = _delegation_fixture()
    try:
        allowed = envelope.validate_child_task(
            parent_task_id="profile",
            child={
                "task_id": "profile-python",
                "capability_id": "agent-office.codex.readonly-analysis",
                "authorized_action": "DEVELOPMENT",
                "objective": "profile python performance bottleneck",
                "read_scope": ["app"],
                "write_scope": [],
                "allowed_side_effects": ["ephemeral worktree"],
                "time_budget_seconds": 120,
                "context_budget_bytes": 8192,
                "tool_budget": 6,
                "retry_budget": 1,
            },
            depth=1,
            existing_child_count=0,
        )
        assert allowed.read_scope == ("app",)
        assert allowed.write_scope == ()
        assert allowed.action == "DEVELOPMENT"

        for bad in (
            {
                "task_id": "bad-action",
                "capability_id": "agent-office.codex.readonly-analysis",
                "authorized_action": "PUBLICATION",
                "objective": "profile python performance bottleneck",
            },
            {
                "task_id": "bad-write",
                "capability_id": "agent-office.codex.readonly-analysis",
                "authorized_action": "DEVELOPMENT",
                "objective": "profile python performance bottleneck",
                "write_scope": ["app"],
            },
            {
                "task_id": "bad-budget",
                "capability_id": "agent-office.codex.readonly-analysis",
                "authorized_action": "DEVELOPMENT",
                "objective": "profile python performance bottleneck",
                "time_budget_seconds": 301,
            },
        ):
            with pytest.raises(PermissionError):
                envelope.validate_child_task(
                    parent_task_id="profile",
                    child=bad,
                    depth=1,
                    existing_child_count=0,
                )
    finally:
        consume_harness_authorization(parent_auth)


def test_hermes_child_proposal_routes_through_harness_and_is_idempotent():
    _plan, parent_auth, envelope = _delegation_fixture()
    board = _FakeHermesBoard()
    try:
        broker = HermesHarnessCapabilityBroker(
            spec=envelope,
            parent_authorization=parent_auth,
            board=board,
            task_mapping={"profile": "board-parent"},
            artifact_dir="/tmp/hermes-delegation-plane-test",
        )
        child = {
            "task_id": "profile-python",
            "capability_id": "agent-office.codex.readonly-analysis",
            "authorized_action": "DEVELOPMENT",
            "objective": "profile python performance bottleneck",
            "read_scope": ["app"],
            "write_scope": [],
            "allowed_side_effects": ["ephemeral worktree"],
            "time_budget_seconds": 120,
            "context_budget_bytes": 8192,
            "tool_budget": 6,
            "retry_budget": 1,
        }
        first = broker.propose_child_task(
            parent_task_id="profile",
            child=child,
        )
        assert first["status"] == "AUTHORIZED"
        assert first["HERMES_SUBDELEGATION_WITHIN_ENVELOPE"] == "PASS"
        assert first["HERMES_AUTHORITY_EXPANSION"] == "NO"
        routed = first["task"]
        assert routed["routing_id"]
        assert routed["selected_executor_binding"]
        assert routed["idempotency_key"].startswith("child:")
        assert len(board.created) == 1

        second = broker.propose_child_task(
            parent_task_id="profile",
            child={**child, "idempotency_key": routed["idempotency_key"]},
        )
        assert second["status"] == "REUSED"
        assert second["DUPLICATE_AGENT_EXECUTION_AVOIDED"] == "PASS"
        assert len(board.created) == 1
    finally:
        consume_harness_authorization(parent_auth)


def test_typed_handoff_has_bounded_cross_agent_lineage():
    handoff = TypedHandoff(
        from_task_id="analyze",
        to_task_id="review",
        evidence_refs=("artifact:analysis.json",),
        result_ref="artifact:analysis.json",
        output_contract="AnalysisEvidence",
        summary="Root cause isolated with bounded evidence.",
        acceptance_state="ACCEPTED_FOR_DEPENDENCY",
        artifact_lineage={
            "sha256": "b" * 64,
            "authorization_id": "auth-1",
            "routing_id": "route-1",
        },
        producer_capability_id="agent-office.codex.readonly-analysis",
        producer_agent_id="codex-readonly",
        producer_skill_id=None,
        producer_version="1",
        observed_at=datetime.now(timezone.utc).isoformat(),
    )
    assert handoff.to_dict()["evidence_refs"] == ("artifact:analysis.json",)
    with pytest.raises(ValueError):
        TypedHandoff(
            from_task_id="a",
            to_task_id="b",
            evidence_refs=("artifact:x",),
            result_ref="artifact:x",
            output_contract="x",
            summary="x" * 5000,
            acceptance_state="ACCEPTED_FOR_DEPENDENCY",
            artifact_lineage={},
            producer_capability_id="x",
            producer_agent_id=None,
            producer_skill_id=None,
            producer_version="1",
            observed_at=datetime.now(timezone.utc).isoformat(),
        )


def test_execution_idempotency_reuses_persisted_result_after_broker_restart(
    monkeypatch,
    tmp_path,
):
    _plan, parent_auth, envelope = _delegation_fixture()
    board = _FakeHermesBoard()
    calls = []

    def fake_execute(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            result={"status": "PASS", "evidence": "captured"},
            elapsed_seconds=0.01,
        )

    try:
        broker = HermesHarnessCapabilityBroker(
            spec=envelope,
            parent_authorization=parent_auth,
            board=board,
            task_mapping={"profile": "board-parent"},
            artifact_dir=tmp_path,
        )
        monkeypatch.setattr(broker.adapter, "execute", fake_execute)
        first = broker.execute_delegated_capability(
            task_id="profile",
            capability_id="agent-office.codex.readonly-analysis",
            payload={"goal_id": envelope.goal_id, "task": "profile safely"},
        )
        assert first["executed"] is True
        assert first["reused"] is False
        assert len(calls) == 1

        same = broker.execute_delegated_capability(
            task_id="profile",
            capability_id="agent-office.codex.readonly-analysis",
            payload={"goal_id": envelope.goal_id, "task": "profile safely"},
        )
        assert same["executed"] is False
        assert same["reused"] is True
        assert same["DUPLICATE_AGENT_EXECUTION_AVOIDED"] == "PASS"
        assert len(calls) == 1

        resumed = HermesHarnessCapabilityBroker(
            spec=envelope,
            parent_authorization=parent_auth,
            board=board,
            task_mapping={"profile": "board-parent"},
            artifact_dir=tmp_path,
        )
        monkeypatch.setattr(resumed.adapter, "execute", fake_execute)
        after_restart = resumed.execute_delegated_capability(
            task_id="profile",
            capability_id="agent-office.codex.readonly-analysis",
            payload={"goal_id": envelope.goal_id, "task": "profile safely"},
        )
        assert after_restart["reused"] is True
        assert after_restart["DUPLICATE_AGENT_EXECUTION_AVOIDED"] == "PASS"
        assert len(calls) == 1
    finally:
        consume_harness_authorization(parent_auth)


def test_durable_checkpoint_restores_results_into_clean_runner(tmp_path, monkeypatch):
    _plan, parent_auth, envelope = _delegation_fixture()
    board = _FakeHermesBoard()
    source_artifacts = tmp_path / "runner-a-artifacts"
    source_home = tmp_path / "runner-a-hermes-home"
    source_home.mkdir(parents=True)
    (source_home / "kanban-marker.db").write_bytes(b"durable-kanban-state")
    calls = []

    def fake_execute(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            result={"status": "PASS", "measurement": 42},
            elapsed_seconds=0.01,
        )

    try:
        broker = HermesHarnessCapabilityBroker(
            spec=envelope,
            parent_authorization=parent_auth,
            board=board,
            task_mapping={"profile": "board-parent"},
            artifact_dir=source_artifacts,
        )
        monkeypatch.setattr(broker.adapter, "execute", fake_execute)
        first = broker.execute_delegated_capability(
            task_id="profile",
            capability_id="agent-office.codex.readonly-analysis",
            payload={"goal_id": envelope.goal_id, "task": "profile safely"},
        )
        assert first["executed"] is True
        assert len(calls) == 1

        checkpoint = tmp_path / "checkpoint"
        manifest = export_hermes_mission_checkpoint(
            spec=envelope,
            hermes_home=source_home,
            artifact_dir=source_artifacts,
            checkpoint_dir=checkpoint,
        )
        assert manifest["mission_id"] == envelope.mission_id
        assert manifest["result_files"]
        assert (checkpoint / "hermes-home" / "kanban-marker.db").is_file()

        clean_home = tmp_path / "runner-b-hermes-home"
        clean_artifacts = tmp_path / "runner-b-artifacts"
        restored = restore_hermes_mission_checkpoint(
            spec=envelope,
            checkpoint_dir=checkpoint,
            hermes_home=clean_home,
            artifact_dir=clean_artifacts,
        )
        assert restored["CANONICAL_CHECKPOINT_RESTORED"] == "PASS"
        assert restored["DURABLE_MISSION_IDENTITY_PRESERVED"] == "PASS"
        assert (clean_home / "kanban-marker.db").read_bytes() == b"durable-kanban-state"

        resumed = HermesHarnessCapabilityBroker(
            spec=envelope,
            parent_authorization=parent_auth,
            board=board,
            task_mapping={"profile": "board-parent"},
            artifact_dir=clean_artifacts,
        )
        monkeypatch.setattr(resumed.adapter, "execute", fake_execute)
        second = resumed.execute_delegated_capability(
            task_id="profile",
            capability_id="agent-office.codex.readonly-analysis",
            payload={"goal_id": envelope.goal_id, "task": "profile safely"},
        )
        assert second["executed"] is False
        assert second["reused"] is True
        assert second["DUPLICATE_AGENT_EXECUTION_AVOIDED"] == "PASS"
        assert len(calls) == 1

        result_file = next((checkpoint / "capability-results").glob("*.json"))
        result_file.write_text(result_file.read_text() + "tamper", encoding="utf-8")
        with pytest.raises(PermissionError, match="hash mismatch"):
            restore_hermes_mission_checkpoint(
                spec=envelope,
                checkpoint_dir=checkpoint,
                hermes_home=tmp_path / "tampered-home",
                artifact_dir=tmp_path / "tampered-artifacts",
            )
    finally:
        consume_harness_authorization(parent_auth)


def test_retry_stays_same_capability_and_exhaustion_requires_harness_replan(
    monkeypatch,
    tmp_path,
):
    _plan, parent_auth, envelope = _delegation_fixture()
    board = _FakeHermesBoard()
    attempts = {"count": 0}

    def fail_then_pass(**_kwargs):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("captured transient failure")
        return SimpleNamespace(
            result={"status": "PASS"},
            elapsed_seconds=0.01,
        )

    try:
        broker = HermesHarnessCapabilityBroker(
            spec=envelope,
            parent_authorization=parent_auth,
            board=board,
            task_mapping={"profile": "board-parent"},
            artifact_dir=tmp_path,
        )
        monkeypatch.setattr(broker.adapter, "execute", fail_then_pass)
        with pytest.raises(DelegatedCapabilityFailure) as raised:
            broker.execute_delegated_capability(
                task_id="profile",
                capability_id="agent-office.codex.readonly-analysis",
                payload={"goal_id": envelope.goal_id, "task": "profile safely"},
            )
        failure = raised.value
        assert failure.retry_allowed is True
        assert failure.requires_harness_replan is False

        retried = broker.retry_delegated_capability(
            failure=failure,
            payload={"goal_id": envelope.goal_id, "task": "profile safely"},
        )
        assert retried["executed"] is True
        assert attempts["count"] == 2

        with pytest.raises(PermissionError, match="cannot reroute"):
            broker.execute_delegated_capability(
                task_id="profile",
                capability_id="system.improvement.propose",
                payload={},
            )
    finally:
        consume_harness_authorization(parent_auth)

    # Separate mission proves exhaustion becomes a structured replan request.
    _plan2, parent_auth2, envelope2 = _delegation_fixture()
    board2 = _FakeHermesBoard()

    def always_fail(**_kwargs):
        raise RuntimeError("persistent captured failure")

    try:
        broker2 = HermesHarnessCapabilityBroker(
            spec=envelope2,
            parent_authorization=parent_auth2,
            board=board2,
            task_mapping={"profile": "board-parent"},
            artifact_dir=tmp_path / "exhausted",
        )
        monkeypatch.setattr(broker2.adapter, "execute", always_fail)
        with pytest.raises(DelegatedCapabilityFailure) as first_error:
            broker2.execute_delegated_capability(
                task_id="profile",
                capability_id="agent-office.codex.readonly-analysis",
                payload={"goal_id": envelope2.goal_id, "task": "profile safely"},
            )
        with pytest.raises(DelegatedCapabilityFailure) as second_error:
            broker2.retry_delegated_capability(
                failure=first_error.value,
                payload={"goal_id": envelope2.goal_id, "task": "profile safely"},
            )
        exhausted = second_error.value
        assert exhausted.retry_allowed is False
        assert exhausted.requires_harness_replan is True
        assert broker2.audit_snapshot()[-1]["requires_harness_replan"] is True
        with pytest.raises(PermissionError, match="requires DeepSeek Harness replan"):
            broker2.retry_delegated_capability(
                failure=exhausted,
                payload={"goal_id": envelope2.goal_id, "task": "profile safely"},
            )
    finally:
        consume_harness_authorization(parent_auth2)


def test_simple_direct_task_executes_real_registry_capability_without_hermes():
    collaboration = build_collaboration_plan(
        mission_id="mission-direct-real",
        goal_id="goal-direct-real",
        tasks=[
            TaskEnvelope(
                task_id="task-01",
                capability_id="gta6.knowledge.retrieve",
                action="RESEARCH",
                objective="Retrieve bounded canonical GTA6 knowledge about Lucia",
                task_class="readonly-retrieval",
                expected_output="KnowledgeEvidence",
                context_budget_bytes=8192,
                review_policy="NONE",
            )
        ],
    )
    mission_plan = {
        "mission_id": "mission-direct-real",
        "plan_id": "plan-direct-real",
        "authority": "DEEPSEEK_HARNESS",
        "goal": {
            "goal_id": "goal-direct-real",
            "human_goal": "O que sabemos sobre Lucia?",
            "mission_class": "GTA6_INTELLIGENCE",
        },
        "collaboration_plan": collaboration.to_dict(),
    }
    result = execute_harness_mission_plan(
        plan={"mission_plan": mission_plan},
        state={},
        message="O que sabemos sobre Lucia?",
    )
    assert result["status"] == "COMPLETED"
    assert result["authority"] == "DEEPSEEK_HARNESS"
    assert result["MISSION_EXECUTION_ROUTER"] == "PASS"
    assert result["HERMES_USED"] == "NO"
    assert result["mission_execution_route"]["runtime"] == "DIRECT_CAPABILITY"
    assert result["result"]["adapter"] == "HARNESS_CAPABILITY_ADAPTER_V1"
    assert result["result"]["capability_id"] == "gta6.knowledge.retrieve"


def test_single_engineering_task_never_executes_heavy_agent_office_on_control_surface():
    collaboration = build_collaboration_plan(
        mission_id="mission-office-cloud-only",
        goal_id="goal-office-cloud-only",
        tasks=[
            TaskEnvelope(
                task_id="task-01",
                capability_id="agent-office.codex.bounded-development",
                action="DEVELOPMENT",
                objective="Create one isolated bounded code candidate",
                task_class="bounded-development",
                expected_output="BoundedCandidatePatch",
                read_scope=("app", "tests"),
                write_scope=("app", "tests"),
                review_policy="INDEPENDENT_REQUIRED",
                risk_side_effect_class="BOUNDED_MUTATION",
            )
        ],
    )
    mission_plan = {
        "mission_id": "mission-office-cloud-only",
        "plan_id": "plan-office-cloud-only",
        "authority": "DEEPSEEK_HARNESS",
        "goal": {
            "goal_id": "goal-office-cloud-only",
            "human_goal": "Faça uma mudança limitada e segura.",
            "mission_class": "SYSTEM_IMPROVEMENT",
        },
        "collaboration_plan": collaboration.to_dict(),
    }
    result = execute_harness_mission_plan(
        plan={"mission_plan": mission_plan},
        state={},
        message="Faça uma mudança limitada e segura.",
    )
    assert result["status"] == "CLOUD_EXECUTION_REQUIRED"
    assert result["mission_execution_route"]["runtime"] == "AGENT_OFFICE"
    assert result["HERMES_USED"] == "NO"
    assert result["TERMUX_HEAVY_PROCESSING"] == "NO"


def test_candidate_requirement_is_typed_and_preserved_through_task_envelope():
    semantic_task = semantic_planner_module.MissionTaskProposal.from_mapping({
        "task_id": "implement-candidate-fix",
        "objective": "Implement only if diagnosis proves a safe change.",
        "task_class": "bounded-development",
        "required_capability_description": "bounded candidate implementation",
        "candidate_capability_ids": [],
        "dependencies": ["diagnose"],
        "expected_output": "CandidateEvidence",
        "acceptance_criteria": ["measurable improvement", "bounded patch"],
        "risk_side_effect_class": "MEDIUM",
        "action": "DEVELOPMENT",
    })
    requirements = adaptive.proposal_requirements(
        SimpleNamespace(tasks=(semantic_task,))
    )
    assert requirements[0]["candidate_requirement"] == "CONDITIONAL"

    task = TaskEnvelope.from_mapping({
        "task_id": "implement-candidate-fix",
        "capability_id": "agent-office.codex.bounded-development",
        "authorized_action": "DEVELOPMENT",
        "objective": "Implement only if diagnosis proves a safe change.",
        "task_class": "bounded-development",
        "dependencies": [],
        "expected_output": "CandidateEvidence",
        "acceptance_criteria": ["measurable improvement"],
        "read_scope": ["app", "tests"],
        "write_scope": ["app/services/agent_office"],
        "allowed_tools": ["git", "python", "pytest", "codex", "rg", "cat"],
        "candidate_requirement": "CONDITIONAL",
        "risk_side_effect_class": "BOUNDED_MUTATION",
    })
    routed = build_collaboration_plan(
        mission_id="mission-candidate-requirement",
        goal_id="goal-candidate-requirement",
        tasks=[task],
    ).tasks[0]
    assert task.candidate_requirement == "CONDITIONAL"
    assert routed.candidate_requirement == "CONDITIONAL"
    assert routed.to_dict()["candidate_requirement"] == "CONDITIONAL"


def test_grounded_repair_context_propagates_across_readonly_parent_handoff():
    target = "app/services/agent_office/codex_bounded_worker.py"
    task = TaskEnvelope(
        task_id="implement-candidate-fix",
        capability_id="agent-office.codex.bounded-development",
        action="DEVELOPMENT",
        objective="Implement the smallest measured safe improvement.",
        dependencies=("diagnose",),
        expected_output="CandidateEvidence",
        task_class="bounded-development",
        acceptance_criteria=(
            "reduce the measured duplication without regression",
        ),
        candidate_requirement="CONDITIONAL",
        read_scope=("app", "tests"),
        write_scope=("app/services/agent_office",),
        allowed_tools=("git", "python", "pytest", "codex", "rg", "cat"),
        risk_side_effect_class="BOUNDED_MUTATION",
    )
    parent_context = {
        "parent_handoffs": [{
            "task_id": "diagnose",
            "result": {
                "summary": "Diagnosis preserved the measured parent facts.",
                "grounded_context": [
                    "Measured repository baseline: files=42, lines=9000, "
                    "bytes=320000, files_over_1000_lines=1, "
                    "largest_file_lines=1420, profile_latency_ms=4.2.",
                    "Observed measurable fragility: LARGE_MODULE_CONCENTRATION "
                    "files_over_1000_lines=1 "
                    f"evidence={target}.",
                ],
                "engine_result": {
                    "inspected_paths": [target],
                },
            },
        }],
        "evidence_refs": ["artifact:diagnose.json"],
    }
    decision = dynamic_mission._candidate_execution_decision(
        task=task,
        parent_context=parent_context,
    )
    assert decision["decision"] == "REQUIRED"
    assert decision["actionable"] is True
    assert decision["baseline_present"] is True
    assert decision["problem_observed"] is True
    assert target in decision["grounded_writable_targets"]

    payload = dynamic_mission._generic_payload(
        task=task,
        human_goal="Improve only when grounded evidence requires it.",
        goal_id="goal-grounded-repair",
        mission_id="mission-grounded-repair",
        base_sha="a" * 40,
        branch="work/gate6f-analytics-learning",
        snapshot={},
        parent_context=parent_context,
    )
    assert target in payload["objective"]
    assert any(target in row for row in payload["gaps"])

    from app.services.agent_office_harness_service import (
        build_agent_office_specialist_contract,
    )
    record = GLOBAL_CAPABILITY_REGISTRY.get(task.capability_id)
    contract = build_agent_office_specialist_contract(
        record=record,
        payload=payload,
    )
    assert target in contract["task"]["objective"]
    assert contract["task"]["write_set"] == [
        "app/services/agent_office"
    ]


def test_conditional_candidate_has_legitimate_not_required_path():
    task = TaskEnvelope(
        task_id="conditional-candidate",
        capability_id="agent-office.codex.bounded-development",
        action="DEVELOPMENT",
        objective="Change code only if a measurable problem is observed.",
        expected_output="CandidateEvidence",
        acceptance_criteria=("preserve quality",),
        candidate_requirement="CONDITIONAL",
        read_scope=("app",),
        write_scope=("app/services",),
        risk_side_effect_class="BOUNDED_MUTATION",
    )
    decision = dynamic_mission._candidate_execution_decision(
        task=task,
        parent_context={
            "parent_handoffs": [{
                "task_id": "diagnose",
                "result": {
                    "summary": (
                        "No measurable repository fragility requiring "
                        "a code mutation was observed."
                    )
                },
            }],
            "evidence_refs": ["artifact:diagnose-no-change.json"],
        },
    )
    assert decision["decision"] == "NOT_REQUIRED"
    assert decision["problem_observed"] is False
    assert decision["actionable"] is False


def test_required_candidate_rejects_ungrounded_context_before_worker():
    task = TaskEnvelope(
        task_id="required-candidate",
        capability_id="agent-office.codex.bounded-development",
        action="DEVELOPMENT",
        objective="Implement the required bounded change.",
        expected_output="CandidateEvidence",
        acceptance_criteria=("produce a measured improvement",),
        candidate_requirement="REQUIRED",
        read_scope=("app",),
        write_scope=("app/services",),
        risk_side_effect_class="BOUNDED_MUTATION",
    )
    decision = dynamic_mission._candidate_execution_decision(
        task=task,
        parent_context={
            "parent_handoffs": [{
                "task_id": "diagnose",
                "result": {
                    "observed_gaps": ["A problem was described but not measured."]
                },
            }],
        },
    )
    assert decision["decision"] == "BLOCKED_UNGROUNDED"
    assert "baseline" in decision["reason"]
    assert "grounded_writable_target" in decision["reason"]


def test_broker_not_required_result_is_typed_and_preserves_handoff_lineage(
    tmp_path,
):
    plan = build_collaboration_plan(
        mission_id="mission-not-required-handoff",
        goal_id="goal-not-required-handoff",
        tasks=[
            TaskEnvelope(
                task_id="candidate",
                capability_id="agent-office.codex.bounded-development",
                action="DEVELOPMENT",
                objective="Change code only if grounded evidence requires it.",
                expected_output="CandidateEvidence",
                acceptance_criteria=("bounded change only",),
                candidate_requirement="CONDITIONAL",
                read_scope=("app",),
                write_scope=("app/services",),
                allowed_tools=("git", "python", "pytest", "codex", "rg", "cat"),
                risk_side_effect_class="BOUNDED_MUTATION",
            ),
            TaskEnvelope(
                task_id="review",
                capability_id="agent-office.codex.readonly-analysis",
                action="DEVELOPMENT",
                objective="Review the candidate decision evidence.",
                dependencies=("candidate",),
                expected_output="ReviewEvidence",
                read_scope=("app",),
                write_scope=(),
                allowed_tools=("git", "python", "pytest", "codex", "rg", "cat"),
                review_policy="NONE",
            ),
        ],
    )
    parent = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject="capability:collaboration.hermes.execute",
        harness_decision_id="decision-not-required-handoff",
        execution_id="execution-not-required-handoff",
        lineage={"test": "not-required-handoff"},
    )
    envelope = DelegationEnvelope.from_plan(
        collaboration_plan=plan,
        harness_decision_id=parent.harness_decision_id,
        authorization_id=parent.authorization_id,
        base_sha="a" * 40,
        expires_at=(
            datetime.now(timezone.utc) + timedelta(minutes=10)
        ).isoformat(),
    )
    board = _FakeHermesBoard()
    try:
        broker = HermesHarnessCapabilityBroker(
            spec=envelope,
            parent_authorization=parent,
            board=board,
            task_mapping={
                "candidate": "board-candidate",
                "review": "board-review",
            },
            artifact_dir=tmp_path,
        )
        result = broker.record_candidate_not_required(
            task_id="candidate",
            reason="No measurable problem requires mutation.",
            evidence_refs=("artifact:diagnosis.json",),
        )
        assert result["executed"] is False
        assert result["not_required"] is True
        assert result["result"]["candidate_decision"] == "NOT_REQUIRED"
        assert result["result"]["builder_self_approval"] is False

        handoff = broker.submit_handoff(
            from_task_id="candidate",
            to_task_id="review",
            evidence_refs=(result["evidence_ref"],),
            summary="Typed candidate decision evidence.",
        )
        assert handoff["acceptance_state"] == "ACCEPTED_FOR_DEPENDENCY"
        context = broker.parent_context(task_id="review")
        assert context["parent_handoffs"][0]["result"][
            "candidate_decision"
        ] == "NOT_REQUIRED"
        assert any(
            row["event"] == "TASK_COMPLETED_NOT_REQUIRED"
            and row["builder_self_approval"] is False
            for row in broker.audit_snapshot()
        )
    finally:
        consume_harness_authorization(parent)


def test_broker_not_required_does_not_require_allocated_write_scope(
    tmp_path,
):
    plan = build_collaboration_plan(
        mission_id="mission-not-required-no-write-scope",
        goal_id="goal-not-required-no-write-scope",
        tasks=[
            TaskEnvelope(
                task_id="conditional-candidate",
                capability_id="agent-office.codex.bounded-development",
                action="DEVELOPMENT",
                objective="Mutate only if grounded evidence proves it necessary.",
                expected_output="CandidateEvidence",
                acceptance_criteria=("no mutation without evidence",),
                candidate_requirement="CONDITIONAL",
                read_scope=("app",),
                write_scope=(),
                allowed_tools=("git", "python", "pytest", "codex", "rg", "cat"),
                risk_side_effect_class="BOUNDED_MUTATION",
            ),
        ],
    )
    parent = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject="capability:collaboration.hermes.execute",
        harness_decision_id="decision-not-required-no-write-scope",
        execution_id="execution-not-required-no-write-scope",
        lineage={"test": "not-required-no-write-scope"},
    )
    envelope = DelegationEnvelope.from_plan(
        collaboration_plan=plan,
        harness_decision_id=parent.harness_decision_id,
        authorization_id=parent.authorization_id,
        base_sha="a" * 40,
        expires_at=(
            datetime.now(timezone.utc) + timedelta(minutes=10)
        ).isoformat(),
    )
    try:
        broker = HermesHarnessCapabilityBroker(
            spec=envelope,
            parent_authorization=parent,
            board=_FakeHermesBoard(),
            task_mapping={"conditional-candidate": "board-candidate"},
            artifact_dir=tmp_path,
        )
        result = broker.record_candidate_not_required(
            task_id="conditional-candidate",
            reason="No measurable problem requires a code mutation.",
            evidence_refs=("artifact:diagnosis.json",),
        )
        assert result["executed"] is False
        assert result["not_required"] is True
        assert result["result"]["candidate_decision"] == "NOT_REQUIRED"
        assert result["result"]["candidate"] is None
        assert result["result"]["builder_self_approval"] is False
        assert not any(
            row.get("event") == "TASK_COMPLETED"
            and row.get("capability_id") == "agent-office.codex.bounded-development"
            for row in broker.audit_snapshot()
        )
    finally:
        consume_harness_authorization(parent)


def test_task_envelope_mutation_candidate_matrix():
    readonly = TaskEnvelope.from_mapping({
        "task_id": "inspect-readonly",
        "capability_id": "agent-office.codex.readonly-analysis",
        "authorized_action": "DEVELOPMENT",
        "objective": "Inspect without mutation.",
        "candidate_requirement": "NOT_APPLICABLE",
        "read_scope": ["app"],
        "write_scope": [],
        "risk_side_effect_class": "READ_ONLY",
    })
    assert readonly.candidate_requirement == "NOT_APPLICABLE"
    assert readonly.write_scope == ()

    required = TaskEnvelope.from_mapping({
        "task_id": "mutate-required",
        "capability_id": "agent-office.codex.bounded-development",
        "authorized_action": "DEVELOPMENT",
        "objective": "Produce a bounded candidate.",
        "candidate_requirement": "REQUIRED",
        "read_scope": ["app", "tests"],
        "write_scope": ["app/services"],
        "risk_side_effect_class": "BOUNDED_MUTATION",
    })
    assert required.candidate_requirement == "REQUIRED"

    conditional = TaskEnvelope.from_mapping({
        "task_id": "mutate-conditional",
        "capability_id": "agent-office.codex.bounded-development",
        "authorized_action": "DEVELOPMENT",
        "objective": "Produce a bounded candidate only when evidence justifies it.",
        "candidate_requirement": "CONDITIONAL",
        "read_scope": ["app", "tests"],
        "write_scope": ["app/services"],
        "risk_side_effect_class": "BOUNDED_MUTATION",
    })
    assert conditional.candidate_requirement == "CONDITIONAL"

    derived_readonly = TaskEnvelope.from_mapping({
        "task_id": "inspect-derived",
        "capability_id": "agent-office.codex.readonly-analysis",
        "authorized_action": "DEVELOPMENT",
        "objective": "Derive readonly candidate semantics.",
        "read_scope": ["app"],
        "write_scope": [],
        "risk_side_effect_class": "READ_ONLY",
    })
    assert derived_readonly.candidate_requirement == "NOT_APPLICABLE"

    derived_mutating = TaskEnvelope.from_mapping({
        "task_id": "mutate-derived",
        "capability_id": "agent-office.codex.bounded-development",
        "authorized_action": "DEVELOPMENT",
        "objective": "Derive mutating candidate semantics.",
        "read_scope": ["app", "tests"],
        "write_scope": ["app/services"],
        "risk_side_effect_class": "BOUNDED_MUTATION",
    })
    assert derived_mutating.candidate_requirement == "REQUIRED"

    with pytest.raises(
        ValueError,
        match="mutating TaskEnvelope cannot mark candidate NOT_APPLICABLE",
    ):
        TaskEnvelope.from_mapping({
            "task_id": "mutate-invalid",
            "capability_id": "agent-office.codex.bounded-development",
            "authorized_action": "DEVELOPMENT",
            "objective": "Invalid mutation semantics must fail closed.",
            "candidate_requirement": "NOT_APPLICABLE",
            "read_scope": ["app", "tests"],
            "write_scope": ["app/services"],
            "risk_side_effect_class": "BOUNDED_MUTATION",
        })
