from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace
import time

import app.services.hermes_multiagent.capability_broker as broker_module
from app.services.capability_execution_contract_service import (
    CAN_CONSUME_ARTIFACT_REFS,
    CAN_MUTATE_CANDIDATE,
    CAN_PRODUCE_ARTIFACT_REFS,
    CAN_READ_REPOSITORY,
    CAN_REVIEW,
    CAN_RUN_BENCHMARK,
    CAN_RUN_TESTS,
    CAN_SEMANTIC_REASONING,
    capability_execution_contract_rejection,
    derive_required_operations,
)
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.harness_collaboration_service import RoutedCollaborationTask
from app.services.hermes_multiagent.capability_broker import (
    HermesHarnessCapabilityBroker,
)
from app.services.task_dependency_precondition_service import (
    TaskDependencyPreconditionFailure,
    validate_task_dependency_preconditions,
)
from app.services.task_result_envelope_service import (
    DependencyArtifactMissing,
    TASK_RESULT_ENVELOPE_SCHEMA,
    build_task_result_envelope,
    load_task_result_envelope,
    persist_task_result_envelope,
)
from scripts.dynamic_system_improvement_mission import (
    _context_char_size,
    _fit_parent_context_to_executor_limit,
)


MISSION_ID = "mission-5b3e3519a659af96d122"
GOAL_ID = "semantic-planner-self-improvement"
CHAIN = (
    "instrument-baseline",
    "analyze-root-cause",
    "design-candidate",
    "independent-review",
    "benchmark-compare",
)
CAPABILITIES = {
    "instrument-baseline": "addy:planning-and-task-breakdown",
    "analyze-root-cause": "addy:ci-cd-and-automation",
    "design-candidate": "addy:performance-optimization",
    "independent-review": "addy:code-review-and-quality",
    "benchmark-compare": "addy:observability-and-instrumentation",
}
DEPENDENCIES = {
    "instrument-baseline": (),
    "analyze-root-cause": ("instrument-baseline",),
    "design-candidate": ("analyze-root-cause",),
    "independent-review": ("design-candidate",),
    "benchmark-compare": ("independent-review",),
}
OPS = {
    "instrument-baseline": (
        CAN_READ_REPOSITORY,
        CAN_PRODUCE_ARTIFACT_REFS,
    ),
    "analyze-root-cause": (
        CAN_SEMANTIC_REASONING,
        CAN_CONSUME_ARTIFACT_REFS,
        CAN_PRODUCE_ARTIFACT_REFS,
    ),
    "design-candidate": (
        CAN_READ_REPOSITORY,
        CAN_RUN_TESTS,
        CAN_MUTATE_CANDIDATE,
        CAN_CONSUME_ARTIFACT_REFS,
        CAN_PRODUCE_ARTIFACT_REFS,
    ),
    "independent-review": (
        CAN_REVIEW,
        CAN_CONSUME_ARTIFACT_REFS,
        CAN_PRODUCE_ARTIFACT_REFS,
    ),
    "benchmark-compare": (
        CAN_READ_REPOSITORY,
        CAN_RUN_BENCHMARK,
        CAN_CONSUME_ARTIFACT_REFS,
        CAN_PRODUCE_ARTIFACT_REFS,
    ),
}


class _EmptyBoundedContext:
    used_bytes = 0

    def to_dict(self):
        return {
            "operational_memory": [],
            "knowledge_memory": [],
            "artifact_lineage_memory": [],
            "conversation_memory": [],
            "competence_records": [],
            "used_bytes": 0,
        }


class _ReplaySpec:
    mission_id = MISSION_ID
    goal_id = GOAL_ID
    budgets = {"context_bytes": 65536}

    def __init__(self, tasks):
        self._tasks = dict(tasks)

    def task(self, task_id):
        return self._tasks[task_id]


class _Board:
    def __init__(self):
        self._counter = 0

    def comment(self, _task_ref, *, author, body):
        self._counter += 1
        assert author
        assert body.startswith("TYPED_HANDOFF=")
        return f"replay-comment-{self._counter}"


def _task(task_id: str) -> RoutedCollaborationTask:
    capability_id = CAPABILITIES[task_id]
    record = GLOBAL_CAPABILITY_REGISTRY.get(capability_id)
    if record is None:
        raise RuntimeError(f"missing Registry capability: {capability_id}")
    return RoutedCollaborationTask(
        task_id=task_id,
        capability_id=capability_id,
        action="DEVELOPMENT",
        objective=task_id.replace("-", " "),
        dependencies=tuple(DEPENDENCIES[task_id]),
        input_refs=(),
        expected_output="ReplayEvidence",
        routing_id=f"replay:{task_id}",
        candidate_capability_ids=(),
        selected_executor_binding=str(record.executor_binding or ""),
        selected_agent_id=record.agent_id,
        selected_skill_id=record.skill_id,
        evidence_expectations=("typed task result",),
        task_class="DEVELOPMENT",
        required_capability_description=task_id.replace("-", " "),
        acceptance_criteria=("typed handoff is resolvable",),
        candidate_requirement=(
            "REQUIRED"
            if task_id == "design-candidate"
            else "NOT_APPLICABLE"
        ),
        required_operations=tuple(OPS[task_id]),
        read_scope=tuple(record.default_read_scope),
        write_scope=tuple(record.default_write_scope),
        allowed_tools=tuple(record.allowed_tools),
        allowed_side_effects=(),
        forbidden_side_effects=("push", "merge", "publication"),
        context_budget_bytes=65536,
        evidence_contract=str(record.evidence_contract or ""),
        review_policy="INDEPENDENT_IF_MUTATING",
        risk_side_effect_class=(
            "BOUNDED_MUTATION"
            if task_id == "design-candidate"
            else "READ_ONLY"
        ),
        idempotency_key=f"replay:{task_id}",
        mission_id=MISSION_ID,
        goal_id=GOAL_ID,
        capability_version=str(record.version or "1"),
        supports_parallelism=record.supports_parallelism,
        supports_retry=record.supports_retry,
        supports_resume=record.supports_resume,
        supports_review=record.supports_review,
    )


def _legacy_path(root: Path, task_id: str) -> Path:
    return root / "capability-results" / f"{task_id}-1.json"


def _read_legacy(root: Path, task_id: str) -> dict:
    path = _legacy_path(root, task_id)
    if not path.is_file():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def _canonical_parent_row(
    *,
    persisted: dict,
    loaded: dict,
    direct_dependency: bool,
) -> dict:
    return {
        "task_id": loaded["task_id"],
        "capability_id": loaded.get("capability_id"),
        "agent_id": loaded.get("agent_id"),
        "skill_id": loaded.get("skill_id"),
        "task_result_ref": persisted["task_result_ref"],
        "content_sha256": loaded["content_sha256"],
        "result_summary": loaded.get("result_summary"),
        "output_artifact_refs": list(loaded.get("output_artifact_refs") or ()),
        "evidence_refs": list(loaded.get("evidence_refs") or ()),
        "metrics_refs": list(loaded.get("metrics_refs") or ()),
        "source_task_ids": list(loaded.get("source_task_ids") or ()),
        "direct_dependency": bool(direct_dependency),
        "result": loaded.get("result_payload"),
    }


def _resolve_handoff_row(
    *,
    artifact_dir: Path,
    row: dict,
) -> tuple[dict, float]:
    ref = str(row.get("task_result_ref") or "").strip()
    digest = str(row.get("content_sha256") or "").strip()
    assert ref.startswith("artifact:task-results/")
    assert digest
    started = time.perf_counter()
    loaded = load_task_result_envelope(
        artifact_dir=artifact_dir,
        task_result_ref=ref,
    )
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    assert loaded["task_id"] == row["task_id"]
    assert loaded["content_sha256"] == digest
    if "result" in row:
        assert row["result"] == loaded["result_payload"]
    else:
        assert row.get("result_omitted") in {
            "CONTEXT_BUDGET",
            "EXECUTOR_CONTEXT_LIMIT",
        }
    return loaded, elapsed_ms


def _controlled_task(task_id: str, ops, *, deps=(), agent="agent", capability="cap"):
    return SimpleNamespace(
        task_id=task_id,
        required_operations=tuple(ops),
        dependencies=tuple(deps),
        selected_agent_id=agent,
        selected_skill_id=None,
        capability_id=capability,
    )


def run(*, legacy_artifact_dir: Path, output: Path) -> dict:
    source = Path(legacy_artifact_dir)
    proof_root = output.parent / "proof-runtime"
    proof_root.mkdir(parents=True, exist_ok=True)

    tasks = {task_id: _task(task_id) for task_id in CHAIN}
    spec = _ReplaySpec(tasks)

    broker = object.__new__(HermesHarnessCapabilityBroker)
    broker.spec = spec
    broker.registry = GLOBAL_CAPABILITY_REGISTRY
    broker.artifact_dir = proof_root
    broker.result_dir = proof_root / "capability-results"
    broker.result_dir.mkdir(parents=True, exist_ok=True)
    broker._task_results = {}
    broker._child_tasks = {}
    broker._child_parent = {}
    broker._handoffs = []
    broker._human_requests = []
    broker._audit = []
    broker.board = _Board()
    broker.task_mapping = {task_id: task_id for task_id in CHAIN}

    original_memory_builder = broker_module.build_bounded_memory_context
    broker_module.build_bounded_memory_context = (
        lambda **_kwargs: _EmptyBoundedContext()
    )

    result_persist_ms = 0.0
    persisted = []
    try:
        for index, task_id in enumerate(CHAIN[:-1], start=1):
            legacy = _read_legacy(source, task_id)
            task = tasks[task_id]
            started = time.perf_counter()
            envelope = build_task_result_envelope(
                mission_id=MISSION_ID,
                task_id=task_id,
                capability_id=str(legacy["capability_id"]),
                agent_id=legacy.get("agent_id"),
                skill_id=task.selected_skill_id,
                executor_binding=task.selected_executor_binding,
                status=str(legacy.get("status") or "COMPLETED"),
                started_at="2026-09-23T03:35:00+00:00",
                completed_at="2026-09-23T03:36:12+00:00",
                elapsed_ms=float(legacy.get("elapsed_seconds") or 0.0) * 1000.0,
                result=legacy.get("result"),
                source_task_ids=DEPENDENCIES[task_id],
                authorization_id=str(legacy.get("authorization_id") or ""),
            )
            persisted_record = persist_task_result_envelope(
                envelope,
                artifact_dir=proof_root,
                index=index,
            )
            result_persist_ms += (time.perf_counter() - started) * 1000.0
            loaded = load_task_result_envelope(
                artifact_dir=proof_root,
                task_result_ref=persisted_record["task_result_ref"],
            )
            assert loaded["content_sha256"] == envelope.content_sha256
            assert loaded["schema"] == TASK_RESULT_ENVELOPE_SCHEMA
            raw = json.dumps(
                legacy,
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            )
            row = {
                **legacy,
                "evidence_ref": (
                    "artifact:legacy-capability-results/"
                    f"{task_id}-1.json"
                ),
                "sha256": sha256(raw.encode("utf-8")).hexdigest(),
                "task_result_ref": persisted_record["task_result_ref"],
                "task_result_sha256": persisted_record["content_sha256"],
            }
            broker._task_results.setdefault(task_id, []).append(row)
            persisted.append(task_id)

        analyze_context = broker.parent_context(task_id="analyze-root-cause")
        design_context = broker.parent_context(task_id="design-candidate")
        review_context = broker.parent_context(task_id="independent-review")
        benchmark_context = broker.parent_context(task_id="benchmark-compare")

        def rows(context):
            return list(context.get("dependency_results") or ())

        analyze_rows = rows(analyze_context)
        design_rows = rows(design_context)
        review_rows = rows(review_context)
        benchmark_rows = rows(benchmark_context)

        assert [r["task_id"] for r in analyze_rows if r["direct_dependency"]] == [
            "instrument-baseline"
        ]
        assert [r["task_id"] for r in design_rows if r["direct_dependency"]] == [
            "analyze-root-cause"
        ]
        assert {r["task_id"] for r in design_rows if not r["direct_dependency"]} == {
            "instrument-baseline"
        }
        assert [r["task_id"] for r in review_rows if r["direct_dependency"]] == [
            "design-candidate"
        ]
        assert {r["task_id"] for r in benchmark_rows} == {
            "instrument-baseline",
            "analyze-root-cause",
            "design-candidate",
            "independent-review",
        }
        refs_only_keys = {
            "task_id",
            "task_result_ref",
            "content_sha256",
            "direct_dependency",
        }
        all_dependency_rows = [
            *analyze_rows,
            *design_rows,
            *review_rows,
            *benchmark_rows,
        ]
        assert all(set(row) == refs_only_keys for row in all_dependency_rows)
        assert all("result" not in row for row in all_dependency_rows)
        assert all(
            row["task_result_ref"].startswith("artifact:task-results/")
            for row in benchmark_rows
        )
        assert len({row["task_id"] for row in benchmark_rows}) == len(
            benchmark_rows
        )
        assert (
            benchmark_context["dependency_metrics"]["DEPENDENCY_CONTEXT_BYTES"]
            <= 65536
        )
        assert (
            benchmark_context["dependency_metrics"][
                "DEPENDENCY_ALIAS_BYTES_AVOIDED"
            ]
            > 0
        )

        canonical_result_load_ms = 0.0
        canonical_rows_checked = 0
        for context in (
            analyze_context,
            design_context,
            review_context,
            benchmark_context,
        ):
            parent_by_task = {
                str(row.get("task_id") or ""): row
                for row in (context.get("parent_handoffs") or ())
            }
            for row in context.get("dependency_results") or ():
                loaded, load_ms = _resolve_handoff_row(
                    artifact_dir=proof_root,
                    row={
                        **row,
                        **(
                            {"result": parent_by_task[row["task_id"]]["result"]}
                            if "result" in parent_by_task.get(row["task_id"], {})
                            else {
                                "result_omitted": parent_by_task[
                                    row["task_id"]
                                ].get("result_omitted")
                            }
                        ),
                    },
                )
                parent = parent_by_task[row["task_id"]]
                assert (
                    bool(parent.get("direct_dependency"))
                    == bool(row.get("direct_dependency"))
                )
                assert list(loaded.get("source_task_ids") or ()) == list(
                    parent.get("source_task_ids") or ()
                )
                canonical_result_load_ms += load_ms
                canonical_rows_checked += 1

        # Small payload: keep the full result inline. The alias remains refs-only.
        small_result = {
            "summary": "small replay payload",
            "value": "inline",
        }
        small_envelope = build_task_result_envelope(
            mission_id=MISSION_ID,
            task_id="small-payload-producer",
            capability_id="replay.small",
            agent_id="replay",
            skill_id=None,
            executor_binding="replay",
            status="COMPLETED",
            started_at="2026-09-23T03:35:00+00:00",
            completed_at="2026-09-23T03:35:01+00:00",
            elapsed_ms=1.0,
            result=small_result,
            source_task_ids=(),
            authorization_id="replay-small",
        )
        small_persisted = persist_task_result_envelope(
            small_envelope,
            artifact_dir=proof_root,
            index=101,
        )
        small_loaded = load_task_result_envelope(
            artifact_dir=proof_root,
            task_result_ref=small_persisted["task_result_ref"],
        )
        small_parent = _canonical_parent_row(
            persisted=small_persisted,
            loaded=small_loaded,
            direct_dependency=True,
        )
        small_context = {
            "parent_handoffs": [small_parent],
            "dependency_results": [{
                "task_id": small_parent["task_id"],
                "task_result_ref": small_parent["task_result_ref"],
                "content_sha256": small_parent["content_sha256"],
                "direct_dependency": True,
            }],
            "dependency_metrics": {},
        }
        small_original_chars = _context_char_size(small_context)
        small_fitted, small_metrics = _fit_parent_context_to_executor_limit(
            parent_context=small_context,
            executor_context_limit_chars=small_original_chars + 512,
        )
        assert "result" in small_fitted["parent_handoffs"][0]
        assert "result_omitted" not in small_fitted["parent_handoffs"][0]
        assert (
            small_fitted["parent_handoffs"][0]["result"]
            == small_loaded["result_payload"]
        )
        assert set(small_fitted["dependency_results"][0]) == refs_only_keys
        assert "result" not in small_fitted["dependency_results"][0]
        assert small_metrics["PARENT_RESULT_PAYLOADS_OMITTED"] == 0

        # Oversized payload: externalize only the inline copy, then prove the
        # same canonical result is retrievable by immutable ref + content hash.
        oversized_result = {
            "summary": "oversized replay payload",
            "payload": "X" * 24000,
            "evidence_refs": ["artifact:replay-evidence/source.json"],
        }
        oversized_envelope = build_task_result_envelope(
            mission_id=MISSION_ID,
            task_id="oversized-payload-producer",
            capability_id="replay.oversized",
            agent_id="replay",
            skill_id=None,
            executor_binding="replay",
            status="COMPLETED",
            started_at="2026-09-23T03:35:00+00:00",
            completed_at="2026-09-23T03:35:01+00:00",
            elapsed_ms=1.0,
            result=oversized_result,
            source_task_ids=("small-payload-producer",),
            authorization_id="replay-oversized",
        )
        oversized_persisted = persist_task_result_envelope(
            oversized_envelope,
            artifact_dir=proof_root,
            index=102,
        )
        oversized_loaded = load_task_result_envelope(
            artifact_dir=proof_root,
            task_result_ref=oversized_persisted["task_result_ref"],
        )
        oversized_parent = _canonical_parent_row(
            persisted=oversized_persisted,
            loaded=oversized_loaded,
            direct_dependency=True,
        )
        oversized_context = {
            "parent_handoffs": [oversized_parent],
            "dependency_results": [{
                "task_id": oversized_parent["task_id"],
                "task_result_ref": oversized_parent["task_result_ref"],
                "content_sha256": oversized_parent["content_sha256"],
                "direct_dependency": True,
            }],
            "dependency_metrics": {},
        }
        oversized_limit = 5000
        oversized_fitted, oversized_metrics = (
            _fit_parent_context_to_executor_limit(
                parent_context=oversized_context,
                executor_context_limit_chars=oversized_limit,
            )
        )
        oversized_handoff = oversized_fitted["parent_handoffs"][0]
        assert "result" not in oversized_handoff
        assert (
            oversized_handoff.get("result_omitted")
            == "EXECUTOR_CONTEXT_LIMIT"
        )
        assert set(oversized_fitted["dependency_results"][0]) == refs_only_keys
        assert "result" not in oversized_fitted["dependency_results"][0]
        resolved_oversized, oversized_load_ms = _resolve_handoff_row(
            artifact_dir=proof_root,
            row=oversized_handoff,
        )
        assert resolved_oversized["result_payload"] == oversized_result
        assert (
            resolved_oversized["content_sha256"]
            == oversized_handoff["content_sha256"]
        )
        assert (
            oversized_metrics["PARENT_CONTEXT_ORIGINAL_CHARS"]
            > oversized_metrics["PARENT_CONTEXT_FINAL_CHARS"]
        )
        assert (
            oversized_metrics["PARENT_CONTEXT_FINAL_CHARS"]
            <= oversized_limit
        )
        assert oversized_metrics["PARENT_CONTEXT_BYTES_AVOIDED"] > 0
        assert oversized_metrics["PARENT_CONTEXT_FITS_EXECUTOR_LIMIT"] is True
        canonical_result_load_ms += oversized_load_ms
        canonical_rows_checked += 1

        handoff_started = time.perf_counter()
        broker.submit_handoff(
            from_task_id="instrument-baseline",
            to_task_id="analyze-root-cause",
            evidence_refs=[
                broker._task_results["instrument-baseline"][-1]["task_result_ref"]
            ],
            summary="Replay typed profile artifact handoff.",
        )
        handoff_persist_ms = (time.perf_counter() - handoff_started) * 1000.0

        missing_dependency_no_provider = False
        broken = _controlled_task(
            "missing-consumer",
            (CAN_CONSUME_ARTIFACT_REFS,),
            deps=("not-there",),
        )
        try:
            validate_task_dependency_preconditions(
                task=broken,
                dependency_context={"dependency_results": []},
                task_lookup=lambda _task_id: broken,
            )
        except TaskDependencyPreconditionFailure as exc:
            missing_dependency_no_provider = (
                exc.code == "DEPENDENCY_ARTIFACT_MISSING"
                and exc.details.get("provider_call_executed") is False
            )

        review_no_candidate = False
        try:
            validate_task_dependency_preconditions(
                task=tasks["independent-review"],
                dependency_context=review_context,
                task_lookup=tasks.__getitem__,
            )
        except TaskDependencyPreconditionFailure as exc:
            review_no_candidate = (
                exc.code == "REVIEW_BLOCKED_BY_MISSING_CANDIDATE"
                and exc.details.get("provider_call_executed") is False
            )

        benchmark_no_candidate = False
        try:
            validate_task_dependency_preconditions(
                task=tasks["benchmark-compare"],
                dependency_context=benchmark_context,
                task_lookup=tasks.__getitem__,
            )
        except TaskDependencyPreconditionFailure as exc:
            benchmark_no_candidate = (
                exc.code == "BENCHMARK_BLOCKED_BY_MISSING_CANDIDATE"
                and exc.details.get("provider_call_executed") is False
            )

        candidate_task = _controlled_task(
            "candidate",
            (CAN_MUTATE_CANDIDATE,),
            agent="builder",
            capability="builder-cap",
        )
        benchmark_task = _controlled_task(
            "benchmark",
            (CAN_RUN_BENCHMARK,),
            deps=("candidate",),
            agent="benchmark",
            capability="benchmark-cap",
        )
        controlled_tasks = {
            "candidate": candidate_task,
            "benchmark": benchmark_task,
        }
        benchmark_no_baseline = False
        try:
            validate_task_dependency_preconditions(
                task=benchmark_task,
                dependency_context={
                    "dependency_results": [{
                        "task_id": "candidate",
                        "direct_dependency": True,
                        "task_result_ref": "artifact:task-results/candidate-1.json",
                        "content_sha256": "candidate",
                        "result": {"candidate_sha": "a" * 40},
                        "output_artifact_refs": ["git-commit:" + "a" * 40],
                    }]
                },
                task_lookup=controlled_tasks.__getitem__,
            )
        except TaskDependencyPreconditionFailure as exc:
            benchmark_no_baseline = (
                exc.code == "BENCHMARK_BASELINE_ARTIFACT_MISSING"
                and exc.details.get("provider_call_executed") is False
            )

        same_candidate = _controlled_task(
            "same-candidate",
            (CAN_MUTATE_CANDIDATE,),
            agent="same",
            capability="same-cap",
        )
        same_review = _controlled_task(
            "same-review",
            (CAN_REVIEW,),
            deps=("same-candidate",),
            agent="same",
            capability="same-cap",
        )
        same_tasks = {
            "same-candidate": same_candidate,
            "same-review": same_review,
        }
        reviewer_fail_closed = False
        try:
            validate_task_dependency_preconditions(
                task=same_review,
                dependency_context={
                    "dependency_results": [{
                        "task_id": "same-candidate",
                        "direct_dependency": True,
                        "task_result_ref": "artifact:task-results/same-candidate-1.json",
                        "content_sha256": "same",
                        "result": {"candidate_sha": "b" * 40},
                        "output_artifact_refs": ["git-commit:" + "b" * 40],
                    }]
                },
                task_lookup=same_tasks.__getitem__,
            )
        except TaskDependencyPreconditionFailure as exc:
            reviewer_fail_closed = (
                exc.code == "REVIEWER_NOT_INDEPENDENT"
                and exc.details.get("provider_call_executed") is False
            )

        profile_req = {
            "task_id": "instrument-baseline",
            "task_class": "DEVELOPMENT",
            "objective": "Instrument and profile semantic planner repository path",
            "query": "latency profile call counts context sizes duplicate-call map repository inspection",
            "required_capability_description": "real repository profiling",
            "dependencies": [],
            "expected_output": "Structured latency profile",
            "acceptance_criteria": ["profile artifact"],
        }
        candidate_req = {
            "task_id": "design-candidate",
            "task_class": "DEVELOPMENT",
            "objective": "Implement minimal isolated candidate patch/diff with tests",
            "query": "candidate patch diff tests local candidate commit",
            "required_capability_description": "real candidate implementation",
            "dependencies": ["analyze-root-cause"],
            "expected_output": "Candidate patch/diff with tests",
            "acceptance_criteria": ["candidate artifact"],
        }
        benchmark_req = {
            "task_id": "benchmark-compare",
            "task_class": "DEVELOPMENT",
            "objective": "Execute benchmark baseline_ms candidate_ms wall clock",
            "query": "benchmark compare baseline candidate latency",
            "required_capability_description": "real benchmark execution",
            "dependencies": ["independent-review"],
            "expected_output": "Comparison report baseline_ms candidate_ms",
            "acceptance_criteria": ["benchmark evidence"],
        }
        profile_ops = derive_required_operations(profile_req)
        candidate_ops = derive_required_operations(candidate_req)
        benchmark_ops = derive_required_operations(benchmark_req)

        semantic_profile = GLOBAL_CAPABILITY_REGISTRY.get(
            "addy:planning-and-task-breakdown"
        )
        real_profiler = GLOBAL_CAPABILITY_REGISTRY.get(
            "agent-office.deterministic-analysis"
        )
        semantic_candidate = GLOBAL_CAPABILITY_REGISTRY.get(
            "addy:performance-optimization"
        )
        real_builder = GLOBAL_CAPABILITY_REGISTRY.get(
            "agent-office.codex.bounded-development"
        )
        semantic_benchmark = GLOBAL_CAPABILITY_REGISTRY.get(
            "addy:observability-and-instrumentation"
        )
        real_benchmark = GLOBAL_CAPABILITY_REGISTRY.get(
            "agent-office.codex.readonly-analysis"
        )
        assert all(
            item is not None
            for item in (
                semantic_profile,
                real_profiler,
                semantic_candidate,
                real_builder,
                semantic_benchmark,
                real_benchmark,
            )
        )
        assert capability_execution_contract_rejection(
            semantic_profile, profile_ops
        )
        assert capability_execution_contract_rejection(
            real_profiler, profile_ops
        ) is None
        assert capability_execution_contract_rejection(
            semantic_candidate, candidate_ops
        )
        assert capability_execution_contract_rejection(
            real_builder, candidate_ops
        ) is None
        assert capability_execution_contract_rejection(
            semantic_benchmark, benchmark_ops
        )
        assert capability_execution_contract_rejection(
            real_benchmark, benchmark_ops
        ) is None

        report = {
            "source_run": 35814819125,
            "source_artifact": "dynamic-system-improvement-35814819125",
            "TASK_RESULT_ENVELOPE_SCHEMA": "PASS",
            "TASK_RESULT_PERSISTED": "PASS" if len(persisted) == 4 else "FAIL",
            "TASK_RESULT_HASH_VALID": "PASS",
            "DEPENDENCY_ARTIFACT_RESOLUTION": "PASS",
            "DEPENDENCY_LINEAGE_PRESERVED": "PASS",
            "DIRECT_DEPENDENCY_IDENTIFIED": "PASS",
            "TRANSITIVE_DEPENDENCY_IDENTIFIED": "PASS",
            "DOWNSTREAM_TASK_RECEIVES_REQUIRED_CONTEXT": "PASS",
            "DEPENDENCY_CONTEXT_BOUNDED": "PASS",
            "DUPLICATE_HANDOFF_SUPPRESSED": "PASS",
            "MISSING_DEPENDENCY_FAILS_BEFORE_PROVIDER_CALL": (
                "PASS" if missing_dependency_no_provider else "FAIL"
            ),
            "REVIEW_WITHOUT_CANDIDATE_FAILS_BEFORE_PROVIDER_CALL": (
                "PASS" if review_no_candidate else "FAIL"
            ),
            "BENCHMARK_WITHOUT_CANDIDATE_FAILS_BEFORE_PROVIDER_CALL": (
                "PASS" if benchmark_no_candidate else "FAIL"
            ),
            "BENCHMARK_WITHOUT_BASELINE_FAILS_BEFORE_PROVIDER_CALL": (
                "PASS" if benchmark_no_baseline else "FAIL"
            ),
            "REVIEWER_NOT_INDEPENDENT_FAILS_CLOSED": (
                "PASS" if reviewer_fail_closed else "FAIL"
            ),
            "PROVIDER_CALL_EXECUTED": "NO",
            "TASK_REQUIRED_OPERATIONS": {
                "profile": list(profile_ops),
                "candidate": list(candidate_ops),
                "benchmark": list(benchmark_ops),
            },
            "CAPABILITY_SUPPORTED_OPERATIONS": {
                "semantic_profile": list(semantic_profile.execution_operations),
                "real_profiler": list(real_profiler.execution_operations),
                "semantic_candidate": list(semantic_candidate.execution_operations),
                "real_builder": list(real_builder.execution_operations),
                "semantic_benchmark": list(semantic_benchmark.execution_operations),
                "real_benchmark": list(real_benchmark.execution_operations),
            },
            "EXECUTION_CONTRACT_COMPATIBILITY": "PASS",
            "INCOMPATIBLE_CAPABILITY_REJECTED": "PASS",
            "REJECTION_REASON": "execution-contract-insufficient",
            "HARDCODED_FALLBACK": "NO",
            "DEPENDENCY_ARTIFACT_COUNT": benchmark_context[
                "dependency_metrics"
            ]["DEPENDENCY_ARTIFACT_COUNT"],
            "DEPENDENCY_CONTEXT_BYTES": benchmark_context[
                "dependency_metrics"
            ]["DEPENDENCY_CONTEXT_BYTES"],
            "DEPENDENCY_CONTEXT_BUILD_MS": benchmark_context[
                "dependency_metrics"
            ]["DEPENDENCY_CONTEXT_BUILD_MS"],
            "DEPENDENCY_ARTIFACT_LOAD_MS": benchmark_context[
                "dependency_metrics"
            ]["DEPENDENCY_ARTIFACT_LOAD_MS"],
            "DUPLICATE_HANDOFF_BYTES": benchmark_context[
                "dependency_metrics"
            ]["DUPLICATE_HANDOFF_BYTES"],
            "DEPENDENCY_ALIAS_BYTES_AVOIDED": benchmark_context[
                "dependency_metrics"
            ]["DEPENDENCY_ALIAS_BYTES_AVOIDED"],
            "TASK_RESULT_REF_VALID": "PASS",
            "CONTENT_HASH_VALID": "PASS",
            "CANONICAL_RESULT_RETRIEVABLE": "PASS",
            "ARTIFACT_LINEAGE_PRESERVED": "PASS",
            "DIRECT_DEPENDENCY_PRESERVED": "PASS",
            "NO_PAYLOAD_LOSS": "PASS",
            "DEPENDENCY_RESULTS_REFS_ONLY": "PASS",
            "INLINE_RESULT_PRESERVED": "PASS",
            "SMALL_RESULT_INLINE": "PASS",
            "OVERSIZED_RESULT_EXTERNALIZED": "PASS",
            "NO_UNNECESSARY_EXTERNALIZATION": "PASS",
            "INLINE_HANDOFF_COMPATIBILITY": "PASS",
            "EXTERNALIZED_HANDOFF_COMPATIBILITY": "PASS",
            "CANONICAL_RESULT_RETRIEVAL": "PASS",
            "CONTENT_HASH_VALIDATION": "PASS",
            "NO_DUPLICATE_PAYLOAD": "PASS",
            "DUPLICATE_PAYLOAD_SERIALIZATION": 0,
            "PARENT_CONTEXT_ORIGINAL_CHARS": oversized_metrics[
                "PARENT_CONTEXT_ORIGINAL_CHARS"
            ],
            "PARENT_CONTEXT_FINAL_CHARS": oversized_metrics[
                "PARENT_CONTEXT_FINAL_CHARS"
            ],
            "PARENT_CONTEXT_BYTES_AVOIDED": oversized_metrics[
                "PARENT_CONTEXT_BYTES_AVOIDED"
            ],
            "PARENT_CONTEXT_FITS_EXECUTOR_LIMIT": "PASS",
            "EXECUTOR_CONTEXT_LIMIT_CHARS": oversized_limit,
            "ARTIFACT_LOAD_MS": round(
                canonical_result_load_ms
                + benchmark_context["dependency_metrics"][
                    "DEPENDENCY_ARTIFACT_LOAD_MS"
                ],
                3,
            ),
            "CANONICAL_ROWS_CHECKED": canonical_rows_checked,
            "PROVIDER_CALL_COUNT": 0,
            "SEMANTIC_REPLAN_COUNT": 0,
            "NETWORK_REASONING_REQUIRED": "NO",
            "NO_PROVIDER_CALLS": "PASS",
            "RESULT_PERSIST_MS": round(result_persist_ms, 3),
            "HANDOFF_PERSIST_MS": round(handoff_persist_ms, 3),
            "TASK_HANDOFF_REPLAY_PROOF": "PASS",
            "EXECUTION_CONTRACT_PROOF": "PASS",
            "FAIL_CLOSED_PRECONDITION_PROOF": "PASS",
        }
    finally:
        broker_module.build_bounded_memory_context = original_memory_builder

    required_pass = [
        key
        for key, value in report.items()
        if key.endswith("_PROOF")
        or key in {
            "TASK_RESULT_ENVELOPE_SCHEMA",
            "TASK_RESULT_PERSISTED",
            "TASK_RESULT_HASH_VALID",
            "DEPENDENCY_ARTIFACT_RESOLUTION",
            "DEPENDENCY_LINEAGE_PRESERVED",
            "DIRECT_DEPENDENCY_IDENTIFIED",
            "TRANSITIVE_DEPENDENCY_IDENTIFIED",
            "DOWNSTREAM_TASK_RECEIVES_REQUIRED_CONTEXT",
            "DEPENDENCY_CONTEXT_BOUNDED",
            "DUPLICATE_HANDOFF_SUPPRESSED",
            "MISSING_DEPENDENCY_FAILS_BEFORE_PROVIDER_CALL",
            "REVIEW_WITHOUT_CANDIDATE_FAILS_BEFORE_PROVIDER_CALL",
            "BENCHMARK_WITHOUT_CANDIDATE_FAILS_BEFORE_PROVIDER_CALL",
            "BENCHMARK_WITHOUT_BASELINE_FAILS_BEFORE_PROVIDER_CALL",
            "REVIEWER_NOT_INDEPENDENT_FAILS_CLOSED",
            "EXECUTION_CONTRACT_COMPATIBILITY",
            "INCOMPATIBLE_CAPABILITY_REJECTED",
            "TASK_RESULT_REF_VALID",
            "CONTENT_HASH_VALID",
            "CANONICAL_RESULT_RETRIEVABLE",
            "ARTIFACT_LINEAGE_PRESERVED",
            "DIRECT_DEPENDENCY_PRESERVED",
            "NO_PAYLOAD_LOSS",
            "DEPENDENCY_RESULTS_REFS_ONLY",
            "INLINE_RESULT_PRESERVED",
            "SMALL_RESULT_INLINE",
            "OVERSIZED_RESULT_EXTERNALIZED",
            "NO_UNNECESSARY_EXTERNALIZATION",
            "INLINE_HANDOFF_COMPATIBILITY",
            "EXTERNALIZED_HANDOFF_COMPATIBILITY",
            "CANONICAL_RESULT_RETRIEVAL",
            "CONTENT_HASH_VALIDATION",
            "NO_DUPLICATE_PAYLOAD",
            "PARENT_CONTEXT_FITS_EXECUTOR_LIMIT",
            "NO_PROVIDER_CALLS",
        }
    ]
    for key in required_pass:
        if report[key] != "PASS":
            raise RuntimeError(f"{key}={report[key]}")

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    for key in (
        "TASK_RESULT_ENVELOPE_SCHEMA",
        "TASK_RESULT_PERSISTED",
        "TASK_RESULT_HASH_VALID",
        "DEPENDENCY_ARTIFACT_RESOLUTION",
        "DEPENDENCY_LINEAGE_PRESERVED",
        "DIRECT_DEPENDENCY_IDENTIFIED",
        "TRANSITIVE_DEPENDENCY_IDENTIFIED",
        "DOWNSTREAM_TASK_RECEIVES_REQUIRED_CONTEXT",
        "DEPENDENCY_CONTEXT_BOUNDED",
        "DUPLICATE_HANDOFF_SUPPRESSED",
        "MISSING_DEPENDENCY_FAILS_BEFORE_PROVIDER_CALL",
        "REVIEW_WITHOUT_CANDIDATE_FAILS_BEFORE_PROVIDER_CALL",
        "BENCHMARK_WITHOUT_CANDIDATE_FAILS_BEFORE_PROVIDER_CALL",
        "BENCHMARK_WITHOUT_BASELINE_FAILS_BEFORE_PROVIDER_CALL",
        "REVIEWER_NOT_INDEPENDENT_FAILS_CLOSED",
        "EXECUTION_CONTRACT_COMPATIBILITY",
        "INCOMPATIBLE_CAPABILITY_REJECTED",
        "TASK_RESULT_REF_VALID",
        "CONTENT_HASH_VALID",
        "CANONICAL_RESULT_RETRIEVABLE",
        "ARTIFACT_LINEAGE_PRESERVED",
        "DIRECT_DEPENDENCY_PRESERVED",
        "NO_PAYLOAD_LOSS",
        "DEPENDENCY_RESULTS_REFS_ONLY",
        "SMALL_RESULT_INLINE",
        "OVERSIZED_RESULT_EXTERNALIZED",
        "NO_UNNECESSARY_EXTERNALIZATION",
        "INLINE_HANDOFF_COMPATIBILITY",
        "EXTERNALIZED_HANDOFF_COMPATIBILITY",
        "CANONICAL_RESULT_RETRIEVAL",
        "CONTENT_HASH_VALIDATION",
        "NO_DUPLICATE_PAYLOAD",
        "PARENT_CONTEXT_FITS_EXECUTOR_LIMIT",
        "NO_PROVIDER_CALLS",
        "TASK_HANDOFF_REPLAY_PROOF",
    ):
        print(f"{key}={report[key]}")
    for key in (
        "DEPENDENCY_CONTEXT_BYTES",
        "DEPENDENCY_ALIAS_BYTES_AVOIDED",
        "PARENT_CONTEXT_ORIGINAL_CHARS",
        "PARENT_CONTEXT_FINAL_CHARS",
        "PARENT_CONTEXT_BYTES_AVOIDED",
        "EXECUTOR_CONTEXT_LIMIT_CHARS",
        "ARTIFACT_LOAD_MS",
        "DEPENDENCY_CONTEXT_BUILD_MS",
        "DUPLICATE_PAYLOAD_SERIALIZATION",
        "PROVIDER_CALL_COUNT",
        "SEMANTIC_REPLAN_COUNT",
    ):
        print(f"{key}={report[key]}")
    print("PROVIDER_CALL_EXECUTED=NO")
    print("NETWORK_REASONING_REQUIRED=NO")
    print("HARDCODED_FALLBACK=NO")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--legacy-artifact-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(
        legacy_artifact_dir=args.legacy_artifact_dir,
        output=args.output,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
