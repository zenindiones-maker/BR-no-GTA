from __future__ import annotations

from pathlib import Path

from app.services.harness_collaboration_service import TaskEnvelope
from app.services.harness_capability_adapter import CapabilityAdapter
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services import harness_adaptive_planning_service as adaptive_planning
from scripts.real_agent_self_improvement_mission import (
    _is_independent_review_task,
)
from scripts.dynamic_system_improvement_mission import (
    _artifact_content_budget_chars,
    _context_char_size,
    _executor_context_char_limit,
    _fit_parent_context_to_executor_limit,
    _structured_handoff_summary,
    _generic_payload,
    _is_mutating,
    _task_input_artifact_context,
)


def _task(*, mutating: bool) -> TaskEnvelope:
    return TaskEnvelope.from_mapping({
        "task_id": "dynamic-task",
        "capability_id": (
            "agent-office.codex.bounded-development"
            if mutating
            else "agent-office.codex.readonly-analysis"
        ),
        "authorized_action": "DEVELOPMENT",
        "objective": (
            "Create a bounded candidate"
            if mutating
            else "Analyze the bounded system problem"
        ),
        "task_class": (
            "bounded-development" if mutating else "readonly-analysis"
        ),
        "required_capability_description": (
            "bounded code mutation" if mutating else "read-only root cause analysis"
        ),
        "dependencies": [],
        "input_refs": ["artifact:input"],
        "expected_output": "StructuredEngineeringEvidence",
        "acceptance_criteria": ["stay within TaskEnvelope"],
        "read_scope": ["app", "tests"],
        "write_scope": ["app"] if mutating else [],
        "allowed_tools": ["git", "python", "pytest", "codex", "rg", "cat"],
        "allowed_side_effects": (
            ["ephemeral worktree", "local candidate commit"]
            if mutating else ["ephemeral worktree"]
        ),
        "forbidden_side_effects": ["push", "merge", "publication"],
        "time_budget_seconds": 300,
        "cost_budget": 0.0,
        "context_budget_bytes": 16384,
        "tool_budget": 12,
        "retry_budget": 1,
        "evidence_contract": "StructuredEngineeringEvidence",
        "review_policy": "INDEPENDENT_REQUIRED" if mutating else "NONE",
        "risk_side_effect_class": (
            "BOUNDED_MUTATION" if mutating else "READ_ONLY"
        ),
        "human_gate_policy": "NONE",
    })


def _payload(task: TaskEnvelope):
    return _generic_payload(
        task=task,
        human_goal="Improve a measured system inefficiency safely.",
        goal_id="goal-generic-scope",
        mission_id="mission-generic-scope",
        base_sha="a" * 40,
        branch="work/gate6f-analytics-learning",
        snapshot={"signal": "bounded"},
        parent_context={
            "evidence_refs": ["artifact:parent-evidence"],
        },
    )


def test_generic_dynamic_payload_uses_task_envelope_scope_only():
    task = _task(mutating=True)
    payload = _payload(task)
    assert payload["task_id"] == task.task_id
    assert payload["mission_read_scope"] == ["app", "tests"]
    assert payload["mission_write_scope"] == ["app"]
    assert payload["read_set"] == ["app", "tests"]
    assert payload["write_set"] == ["app"]
    assert payload["allowed_paths"] == ["app"]
    assert set(payload["allowed_actions"]) >= {
        "analyze", "inspect", "test", "benchmark", "edit", "commit_candidate"
    }
    assert payload["gaps"] == ["bounded code mutation"]
    assert "artifact:parent-evidence" in payload["evidence_refs"]
    assert _is_mutating(task) is True


def test_generic_dynamic_readonly_task_has_no_write_scope():
    task = _task(mutating=False)
    payload = _payload(task)
    assert payload["mission_write_scope"] == []
    assert payload["write_set"] == []
    assert payload["allowed_paths"] == []
    assert "edit" not in payload["allowed_actions"]
    assert "commit_candidate" not in payload["allowed_actions"]
    assert _is_mutating(task) is False


def test_dynamic_executor_contains_no_task_or_legacy_roster_hardcode():
    source = Path(
        "scripts/dynamic_system_improvement_mission.py"
    ).read_text(encoding="utf-8")
    forbidden = (
        "SPECIALISTS",
        "ROOT_CAUSE_READ_SCOPE",
        "CANDIDATE_READ_SCOPE",
        "VALIDATE_READ_SCOPE",
        "WRITE_SET",
        'if task_id == "measure"',
        'if task_id == "root-cause"',
        'if task_id == "candidate"',
        'if task_id == "validate"',
        '"legacy_fixed_specialists"',
        '"legacy_avoidable_agent_calls"',
    )
    for marker in forbidden:
        assert marker not in source



class _BudgetBroker:
    registry = GLOBAL_CAPABILITY_REGISTRY
    adapter = CapabilityAdapter()


def _addy_task() -> TaskEnvelope:
    return TaskEnvelope.from_mapping({
        "task_id": "evidence-collection",
        "capability_id": "addy:debugging-and-error-recovery",
        "authorized_action": "DEVELOPMENT",
        "objective": "Inspect bounded incident evidence",
        "task_class": "evidence-collection",
        "required_capability_description": "bounded incident evidence analysis",
        "dependencies": [],
        "input_refs": ["artifact:incident-evidence-packet.json"],
        "expected_output": "raw-evidence-bundle",
        "acceptance_criteria": ["preserve evidence lineage"],
        "read_scope": [],
        "write_scope": [],
        "allowed_tools": [],
        "allowed_side_effects": [],
        "forbidden_side_effects": ["push", "merge", "publication"],
        "time_budget_seconds": 300,
        "cost_budget": 0.0,
        "context_budget_bytes": 32768,
        "tool_budget": 8,
        "retry_budget": 1,
        "evidence_contract": "TaskResultEnvelope",
        "review_policy": "NONE",
        "risk_side_effect_class": "READ_ONLY",
        "human_gate_policy": "NONE",
    })


def test_executor_declared_context_limit_bounds_incident_artifact(tmp_path):
    task = _addy_task()
    broker = _BudgetBroker()
    limit = _executor_context_char_limit(task=task, broker=broker)
    assert limit == 16000

    parent_context = {
        "mission_id": "mission-context-budget",
        "task_id": task.task_id,
        "goal_id": "goal-context-budget",
        "task": {
            "objective": task.objective,
            "capability_id": task.capability_id,
        },
        "relevant_memory": {
            "operational_memory": [],
            "knowledge_memory": [],
            "artifact_lineage_memory": [],
            "competence_records": [],
        },
        "relevant_human_decisions": [],
        "evidence_refs": ["artifact:incident-evidence-packet.json"],
        "input_refs": ["artifact:incident-evidence-packet.json"],
    }
    packet = tmp_path / "incident-evidence-packet.json"
    packet.write_text(
        '{"evidence":"' + ("x" * 50000) + '"}',
        encoding="utf-8",
    )
    cache = {}
    metadata, first = _task_input_artifact_context(
        task=task,
        artifact_dir=tmp_path,
        cache=cache,
        include_content=False,
        max_chars=0,
    )
    parent_context["input_artifacts"] = metadata
    metadata_size = _context_char_size(parent_context)
    budget = _artifact_content_budget_chars(
        parent_context=parent_context,
        executor_context_limit_chars=limit,
        reserve_chars=192,
    )
    assert metadata_size < limit
    assert 0 < budget < limit

    artifacts, second = _task_input_artifact_context(
        task=task,
        artifact_dir=tmp_path,
        cache=cache,
        include_content=True,
        max_chars=budget,
    )
    parent_context["input_artifacts"] = artifacts

    assert first["INPUT_ARTIFACT_READ_COUNT"] == 1
    assert second["INPUT_ARTIFACT_READ_COUNT"] == 0
    assert second["INPUT_ARTIFACT_CACHE_HIT_COUNT"] == 1
    assert second["DUPLICATE_INPUT_ARTIFACT_READ_COUNT"] == 0
    assert artifacts[0]["content_truncated"] is True
    assert "content_excerpt" in artifacts[0]
    assert _context_char_size(parent_context) <= limit


def test_incident_artifact_cache_avoids_duplicate_materialization(tmp_path):
    task = _addy_task()
    packet = tmp_path / "incident-evidence-packet.json"
    packet.write_text('{"evidence":"stable"}', encoding="utf-8")
    cache = {}

    _, first = _task_input_artifact_context(
        task=task,
        artifact_dir=tmp_path,
        cache=cache,
        include_content=True,
        max_chars=2048,
    )
    _, second = _task_input_artifact_context(
        task=task,
        artifact_dir=tmp_path,
        cache=cache,
        include_content=True,
        max_chars=2048,
    )

    assert first["INPUT_ARTIFACT_READ_COUNT"] == 1
    assert second["INPUT_ARTIFACT_READ_COUNT"] == 0
    assert second["INPUT_ARTIFACT_CACHE_HIT_COUNT"] == 1
    assert second["DUPLICATE_INPUT_ARTIFACT_READ_COUNT"] == 0



def test_artifact_metadata_overhead_is_counted_before_excerpt_budget(tmp_path):
    task = _addy_task()
    limit = 16000
    packet = tmp_path / "incident-evidence-packet.json"
    packet.write_text(
        '{"raw_text_files":[{"path":"log.txt","content":"'
        + ("evidence line " * 5000)
        + '"}]}',
        encoding="utf-8",
    )
    parent_context = {
        "mission_id": "m" * 200,
        "task_id": task.task_id,
        "goal_id": "g" * 200,
        "task": {
            "objective": "diagnose " * 300,
            "capability_id": task.capability_id,
        },
        "relevant_memory": {
            "operational_memory": [],
            "knowledge_memory": [],
            "artifact_lineage_memory": [],
            "competence_records": [],
        },
        "relevant_human_decisions": [],
        "evidence_refs": ["artifact:incident-evidence-packet.json"],
        "input_refs": ["artifact:incident-evidence-packet.json"],
    }
    cache = {}
    metadata, first = _task_input_artifact_context(
        task=task,
        artifact_dir=tmp_path,
        cache=cache,
        include_content=False,
        max_chars=0,
    )
    parent_context["input_artifacts"] = metadata
    budget = _artifact_content_budget_chars(
        parent_context=parent_context,
        executor_context_limit_chars=limit,
        reserve_chars=192,
    )
    artifacts, second = _task_input_artifact_context(
        task=task,
        artifact_dir=tmp_path,
        cache=cache,
        include_content=True,
        max_chars=budget,
    )
    parent_context["input_artifacts"] = artifacts

    assert first["INPUT_ARTIFACT_READ_COUNT"] == 1
    assert second["INPUT_ARTIFACT_READ_COUNT"] == 0
    assert _context_char_size(parent_context) <= limit



def test_artifact_telemetry_is_not_embedded_in_agent_context():
    source = Path(
        "scripts/dynamic_system_improvement_mission.py"
    ).read_text(encoding="utf-8")
    assert 'parent_context["input_artifact_metrics"]' not in source
    assert '"input_artifact_metrics_by_task"' in source
    assert "INPUT_ARTIFACT_CONTEXT_CHARS" in source



def test_real_incident_collection_prefers_deterministic_artifact_reuse(monkeypatch):
    requirement = {
        "task_id": "incident-evidence",
        "task_class": "system-improvement",
        "action": "DEVELOPMENT",
        "declared_action": "DEVELOPMENT",
        "query": (
            "collect parse incident evidence artifacts runtime failure "
            "performance trace capability results before diagnosis"
        ),
        "objective": (
            "Collect and normalize already-materialized production incident "
            "evidence before root-cause diagnosis."
        ),
        "required_capability_description": (
            "incident evidence artifact reuse without semantic interpretation"
        ),
        "candidate_capability_ids": [],
        "dependencies": [],
        "expected_output": "incident evidence packet",
        "acceptance_criteria": ["preserve observed failure evidence"],
        "risk_side_effect_class": "READ_ONLY",
        "candidate_requirement": "NOT_APPLICABLE",
        "required_operations": ["CAN_PRODUCE_ARTIFACT_REFS"],
    }
    monkeypatch.setattr(
        adaptive_planning,
        "_profiled_capability_health",
        lambda capability_id: type("Health", (), {
            "to_dict": lambda self: {
                "capability_id": capability_id,
                "state": "HEALTHY",
                "reason": "focused semantic-fit guard",
            }
        })(),
    )
    monkeypatch.setattr(
        adaptive_planning,
        "_capability_failure_memory",
        lambda capability_id, context: None,
    )
    monkeypatch.setattr(
        adaptive_planning,
        "_competence_score",
        lambda record, requirement, context: (0.0, False, None),
    )

    selected, _, avoided, evidence = (
        adaptive_planning.select_capability_for_requirement(
            requirement,
            context={"mission_class": "SYSTEM_IMPROVEMENT"},
            used=set(),
        )
    )

    assert selected == "artifact.evidence.reuse"
    assert evidence["top_candidates"][0]["capability_id"] == selected
    assert any(
        item.endswith("semantic-provider-unnecessary-for-contract")
        for item in avoided
        if item.startswith("addy:")
    )



def test_independent_review_detector_uses_contract_not_english_wording():
    task = {
        "task_id": "independent-review",
        "task_class": "review",
        "objective": (
            "Revisão independente do diagnóstico, root cause e recovery proposal"
        ),
        "required_capability_description": (
            "Revisão independente por capability de code-review"
        ),
        "expected_output": "INDEPENDENT_REVIEW_ARTIFACT",
        "required_operations": [
            "CAN_CONSUME_ARTIFACT_REFS",
            "CAN_PRODUCE_ARTIFACT_REFS",
            "CAN_SEMANTIC_REASONING",
            "CAN_REVIEW",
        ],
    }
    assert _is_independent_review_task(task) is True



def test_artifact_reuse_capability_is_deterministic_and_provider_free():
    record = GLOBAL_CAPABILITY_REGISTRY.get("artifact.evidence.reuse")
    assert record is not None
    assert record.provider_id == "internal"
    assert record.health_policy == "DEFAULT"
    assert "CAN_SEMANTIC_REASONING" not in set(record.execution_operations)
    assert {
        "CAN_CONSUME_ARTIFACT_REFS",
        "CAN_PRODUCE_ARTIFACT_REFS",
    }.issubset(set(record.execution_operations))


def test_nonsemantic_artifact_task_rejects_provider_backed_addy(monkeypatch):
    requirement = {
        "task_id": "generic-artifact-reuse",
        "task_class": "system-improvement",
        "action": "DEVELOPMENT",
        "declared_action": "DEVELOPMENT",
        "query": (
            "extrair normalizar evidências incidente artifact pre-materialized"
        ),
        "objective": "normalizar evidências já materializadas sem interpretação",
        "required_capability_description": (
            "reuse pre-materialized incident evidence artifact"
        ),
        "candidate_capability_ids": ["addy:context-engineering"],
        "dependencies": [],
        "expected_output": "evidence artifact manifest",
        "acceptance_criteria": ["preserve sha256 lineage"],
        "risk_side_effect_class": "READ_ONLY",
        "candidate_requirement": "NOT_APPLICABLE",
        "required_operations": ["CAN_PRODUCE_ARTIFACT_REFS"],
    }
    monkeypatch.setattr(
        adaptive_planning,
        "_profiled_registry_discover",
        lambda **_: [
            {"capability_id": "artifact.evidence.reuse"},
            {"capability_id": "addy:context-engineering"},
        ],
    )
    monkeypatch.setattr(
        adaptive_planning,
        "_profiled_capability_health",
        lambda capability_id: type("Health", (), {
            "to_dict": lambda self: {
                "capability_id": capability_id,
                "state": "HEALTHY",
                "reason": "focused contract",
            }
        })(),
    )
    monkeypatch.setattr(
        adaptive_planning,
        "_capability_failure_memory",
        lambda capability_id, context: None,
    )
    monkeypatch.setattr(
        adaptive_planning,
        "_competence_score",
        lambda record, requirement, context: (0.0, False, None),
    )
    selected, _, avoided, evidence = (
        adaptive_planning.select_capability_for_requirement(
            requirement,
            context={"mission_class": "SYSTEM_IMPROVEMENT"},
            used=set(),
        )
    )
    assert selected == "artifact.evidence.reuse"
    assert (
        "addy:context-engineering:"
        "semantic-provider-unnecessary-for-contract"
    ) in avoided
    assert evidence["selected_capability_id"] == selected



def test_parent_handoff_compaction_fits_addy_without_losing_lineage():
    large_result = {
        "evidence_summary": [{
            "artifact_ref": "artifact:incident-evidence-packet.json",
            "summary": {"excerpt": "evidence " * 1200},
        }],
        "artifact_manifest": [{
            "artifact_ref": "artifact:incident-evidence-packet.json",
            "sha256": "a" * 64,
            "size_bytes": 32526,
        }],
    }
    parent = {
        "task_id": "evidence-ingest",
        "capability_id": "artifact.evidence.reuse",
        "agent_id": "artifact-lineage-worker",
        "skill_id": None,
        "task_result_ref": "artifact:task-results/evidence-ingest-1.json",
        "content_sha256": "b" * 64,
        "result_summary": '{"summary":"' + ("diagnostic " * 500) + '"}',
        "output_artifact_refs": [
            "incident-evidence-normalized:" + ("c" * 64)
        ],
        "evidence_refs": ["artifact:incident-evidence-packet.json"],
        "metrics_refs": [],
        "source_task_ids": [],
        "direct_dependency": True,
        "result": large_result,
    }
    context = {
        "mission_id": "mission-observed-context-overrun",
        "task_id": "agent-diagnosis",
        "goal_id": "goal-observed-context-overrun",
        "task": {
            "objective": "Diagnose the observed production incident.",
            "capability_id": "addy:debugging-and-error-recovery",
            "agent_id": "addy-agent-skills",
            "skill_id": "debugging-and-error-recovery",
            "action": "DEVELOPMENT",
        },
        "parent_handoffs": [parent],
        # Legacy alias used to serialize the same 10KB+ result twice.
        "dependency_results": [dict(parent)],
        "dependency_metrics": {},
        "dependency_context_sha256": "d" * 64,
        "relevant_memory": {
            "operational_memory": [],
            "knowledge_memory": [],
            "artifact_lineage_memory": [],
            "competence_records": [],
        },
        "relevant_human_decisions": [],
        "evidence_refs": [
            "artifact:task-results/evidence-ingest-1.json",
            "artifact:incident-evidence-packet.json",
        ],
        "allowed_tools": [],
        "memory_write": "FORBIDDEN",
        "input_refs": ["artifact:incident-evidence-packet.json"],
        "budget_bytes": 65536,
        "used_bytes": 14500,
        "bounded_memory_context": True,
    }
    assert _context_char_size(context) > 16000

    fitted, metrics = _fit_parent_context_to_executor_limit(
        parent_context=context,
        executor_context_limit_chars=16000,
    )

    assert _context_char_size(fitted) <= 16000
    assert metrics["PARENT_CONTEXT_BYTES_AVOIDED"] > 0
    assert metrics["PARENT_CONTEXT_FITS_EXECUTOR_LIMIT"] is True
    assert fitted["parent_handoffs"][0]["task_result_ref"] == (
        "artifact:task-results/evidence-ingest-1.json"
    )
    assert fitted["parent_handoffs"][0]["content_sha256"] == "b" * 64
    assert fitted["parent_handoffs"][0]["result_summary"]
    assert fitted["dependency_results"] == [{
        "task_id": "evidence-ingest",
        "task_result_ref": "artifact:task-results/evidence-ingest-1.json",
        "content_sha256": "b" * 64,
        "direct_dependency": True,
    }]
    if "result" not in fitted["parent_handoffs"][0]:
        assert (
            fitted["parent_handoffs"][0]["result_omitted"]
            == "EXECUTOR_CONTEXT_LIMIT"
        )



def test_semantic_readonly_handoff_uses_ref_hash_and_structured_summary():
    parent = {
        "mission_id": "m",
        "task_id": "task-03",
        "goal_id": "g",
        "task": {"objective": "find root cause"},
        "parent_handoffs": [
            {
                "task_id": "task-02",
                "capability_id": "addy:debugging-and-error-recovery",
                "agent_id": "addy-agent-skills",
                "skill_id": "debugging-and-error-recovery",
                "task_result_ref": "artifact:task-results/task-02-1.json",
                "content_sha256": "a" * 64,
                "result_summary": "tool chatter " * 300,
                "evidence_refs": ["artifact:incident.json"],
                "output_artifact_refs": [],
                "source_task_ids": ["task-01"],
                "direct_dependency": True,
                "result": {
                    "result": {
                        "output": (
                            'kanban_comment {"comment":"noise"}\n'
                            'br_harness_submit_evidence '
                            '{"evidence_refs":["artifact:incident.json"],'
                            '"findings":{"root_cause":"REGISTRY_HEALTH_GATE",'
                            '"failure_class":"PLANNER_CONTRACT",'
                            '"localization":"registry -> health -> zero candidates"}}'
                        )
                    }
                },
            },
            {
                "task_id": "task-01",
                "task_result_ref": "artifact:task-results/task-01-1.json",
                "content_sha256": "b" * 64,
                "direct_dependency": False,
                "result": {"huge": "x" * 6000},
            },
        ],
        "dependency_results": [],
        "relevant_memory": {
            "operational_memory": [{"memory_id": "op1"}, {"memory_id": "op2"}, {"memory_id": "op3"}],
            "knowledge_memory": [{"memory_id": "k1"}, {"memory_id": "k2"}],
            "artifact_lineage_memory": [{"memory_id": "a1"}],
            "competence_records": [{"id": "c1"}, {"id": "c2"}, {"id": "c3"}],
        },
        "relevant_human_decisions": [{"id": "h1"}, {"id": "h2"}],
        "evidence_refs": ["artifact:incident.json", "artifact:extra.json"],
    }
    compact, metrics = _fit_parent_context_to_executor_limit(
        parent_context=parent,
        executor_context_limit_chars=16000,
        semantic_read_only=True,
    )
    assert len(compact["parent_handoffs"]) == 1
    handoff = compact["parent_handoffs"][0]
    assert "result" not in handoff
    assert handoff["task_result_ref"].endswith("task-02-1.json")
    assert handoff["content_sha256"] == "a" * 64
    assert "REGISTRY_HEALTH_GATE" in handoff["result_summary"]
    assert compact["transitive_dependency_refs"][0]["task_id"] == "task-01"
    assert compact["relevant_memory"]["artifact_lineage_memory"] == []
    assert metrics["SEMANTIC_CONTEXT_MODE"] == "REF_HASH_SUMMARY"
    assert metrics["IRRELEVANT_CONTEXT_BYTES"] == 0
    assert metrics["PARENT_CONTEXT_FINAL_CHARS"] < metrics["PARENT_CONTEXT_ORIGINAL_CHARS"]


def test_structured_handoff_summary_prefers_submitted_evidence():
    value = {
        "output": (
            'kanban_comment {"comment":"noise"}\n'
            'br_harness_submit_evidence '
            '{"evidence_refs":["artifact:e"],'
            '"findings":{"root_cause":"CAUSE_A","failure_class":"CLASS_A"}}'
        )
    }
    summary = _structured_handoff_summary(value)
    assert "CAUSE_A" in summary
    assert "CLASS_A" in summary
    assert "kanban_comment" not in summary
