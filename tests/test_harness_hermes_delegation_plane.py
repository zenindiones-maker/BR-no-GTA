from __future__ import annotations

from dataclasses import replace

import pytest

from app.services import harness_adaptive_planning_service as adaptive
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
from scripts.audit_harness_ecosystem import audit


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
        "agent-office.codex.bounded-development"
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
