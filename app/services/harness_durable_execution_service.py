from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Iterable


MATERIALIZATION_STATUSES = frozenset({
    "READY",
    "MISSING_DURABLE_DEPENDENCY",
    "CORRUPT_DEPENDENCY",
    "SCHEMA_MISMATCH",
    "STALE_DEPENDENCY",
    "CONTRADICTORY_LINEAGE",
    "RESEARCH_REQUIRED",
})


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return sha256(_canonical(value)).hexdigest()


@dataclass(frozen=True)
class ExecutionDependencyManifest:
    task_id: str
    capability: str
    logical_output_role: str
    result_schema: str
    result_ref: str
    artifact_refs: tuple[str, ...]
    producer_state_version: int
    content_digest: str
    consumers: tuple[str, ...]

    schema: str = "ExecutionDependencyManifest/v1"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MaterializedExecutionContext:
    mission_id: str
    consumer_task_id: str
    status: str
    dependencies: tuple[dict[str, Any], ...]
    manifests: tuple[dict[str, Any], ...]
    reused_task_ids: tuple[str, ...]
    context_digest: str
    reason: str = ""

    schema: str = "MaterializedExecutionContext/v1"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class HarnessDurableExecutionService:
    """Harness-owned semantic durability over disposable execution workers.

    GitHub artifacts are backing storage. TaskResult envelopes plus immutable
    lineage are the semantic source of truth. The service never selects agents
    or creates a second control plane.
    """

    def __init__(
        self,
        *,
        mission_id: str,
        state_version: int,
        artifact_dir: str | Path,
    ) -> None:
        self.mission_id = str(mission_id).strip()
        self.state_version = int(state_version)
        self.artifact_dir = Path(artifact_dir)
        if not self.mission_id:
            raise ValueError("mission_id is required")
        if self.state_version < 0:
            raise ValueError("state_version must be non-negative")

    def _manifest(
        self,
        row: dict[str, Any],
        *,
        consumers: Iterable[str],
    ) -> ExecutionDependencyManifest:
        if str(row.get("mission_id") or "") != self.mission_id:
            raise PermissionError("CONTRADICTORY_LINEAGE:mission_id")
        if str(row.get("status") or "") != "COMPLETED":
            raise ValueError("STALE_DEPENDENCY:not_completed")
        task_id = str(row.get("task_id") or "").strip()
        capability = str(row.get("capability_id") or "").strip()
        result_ref = str(row.get("task_result_ref") or row.get("evidence_ref") or "").strip()
        if not task_id or not capability or not result_ref:
            raise ValueError("SCHEMA_MISMATCH:task_result_identity")
        result = row.get("result")
        content_digest = str(row.get("task_result_sha256") or row.get("sha256") or "").strip()
        if not content_digest:
            content_digest = _digest(result)
        refs = tuple(dict.fromkeys(
            str(value).strip()
            for value in (row.get("task_result_ref"), row.get("evidence_ref"))
            if str(value or "").strip()
        ))
        return ExecutionDependencyManifest(
            task_id=task_id,
            capability=capability,
            logical_output_role=str(row.get("logical_output_role") or capability),
            result_schema=str(row.get("result_schema") or "TaskResultEnvelope/v1"),
            result_ref=result_ref,
            artifact_refs=refs,
            producer_state_version=int(row.get("producer_state_version") or self.state_version),
            content_digest=content_digest,
            consumers=tuple(sorted(set(str(x) for x in consumers if str(x).strip()))),
        )

    def materialize(
        self,
        *,
        consumer_task_id: str,
        required_task_ids: Iterable[str],
        task_results: dict[str, Iterable[dict[str, Any]]],
    ) -> MaterializedExecutionContext:
        consumer = str(consumer_task_id).strip()
        required = tuple(dict.fromkeys(str(x).strip() for x in required_task_ids if str(x).strip()))
        manifests: list[dict[str, Any]] = []
        dependencies: list[dict[str, Any]] = []
        reused: list[str] = []
        try:
            for task_id in required:
                candidates = [
                    dict(row)
                    for row in task_results.get(task_id, ())
                    if str(row.get("status") or "") == "COMPLETED"
                ]
                if not candidates:
                    return self._context(
                        consumer, "MISSING_DURABLE_DEPENDENCY", dependencies,
                        manifests, reused, f"missing completed TaskResult for {task_id}"
                    )
                row = candidates[-1]
                manifest = self._manifest(row, consumers=(consumer,))
                if manifest.producer_state_version > self.state_version:
                    return self._context(
                        consumer, "STALE_DEPENDENCY", dependencies, manifests,
                        reused, f"producer state {manifest.producer_state_version} exceeds {self.state_version}"
                    )
                manifests.append(manifest.to_dict())
                dependencies.append({
                    "task_id": task_id,
                    "capability_id": row.get("capability_id"),
                    "result_ref": manifest.result_ref,
                    "artifact_refs": list(manifest.artifact_refs),
                    "result": row.get("result"),
                    "content_digest": manifest.content_digest,
                })
                reused.append(task_id)
        except PermissionError as exc:
            return self._context(
                consumer, "CONTRADICTORY_LINEAGE", dependencies, manifests, reused, str(exc)
            )
        except (TypeError, ValueError) as exc:
            status = str(exc).split(":", 1)[0]
            if status not in MATERIALIZATION_STATUSES:
                status = "SCHEMA_MISMATCH"
            return self._context(
                consumer, status, dependencies, manifests, reused, str(exc)
            )
        return self._context(
            consumer, "READY", dependencies, manifests, reused, ""
        )

    def _context(
        self,
        consumer: str,
        status: str,
        dependencies: list[dict[str, Any]],
        manifests: list[dict[str, Any]],
        reused: list[str],
        reason: str,
    ) -> MaterializedExecutionContext:
        logical = {
            "mission_id": self.mission_id,
            "consumer_task_id": consumer,
            "status": status,
            "dependencies": dependencies,
            "manifests": manifests,
            "reused_task_ids": reused,
            "reason": reason,
        }
        return MaterializedExecutionContext(
            mission_id=self.mission_id,
            consumer_task_id=consumer,
            status=status,
            dependencies=tuple(dependencies),
            manifests=tuple(manifests),
            reused_task_ids=tuple(reused),
            context_digest=_digest(logical),
            reason=reason,
        )

    def persist_context(self, context: MaterializedExecutionContext) -> Path:
        target = self.artifact_dir / "durable-execution" / (
            f"{context.consumer_task_id}-{context.context_digest[:16]}.json"
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        raw = _canonical(context.to_dict())
        if target.exists() and target.read_bytes() != raw:
            raise RuntimeError("CAS_CONFLICT:materialized_execution_context")
        target.write_bytes(raw)
        return target

    @staticmethod
    def classify_progress_quantum(
        *,
        state_version_before: int,
        state_version_after: int,
        executed_task_ids: Iterable[str] = (),
        reused_task_ids: Iterable[str] = (),
        new_artifacts: Iterable[str] = (),
        failure_signature: str = "",
        strategy_signature: str = "",
        transport_failure: bool = False,
        dependency_materialization_failure: bool = False,
    ) -> dict[str, Any]:
        executed = tuple(executed_task_ids)
        reused = tuple(reused_task_ids)
        artifacts = tuple(new_artifacts)
        useful = bool(
            int(state_version_after) > int(state_version_before)
            or executed
            or artifacts
        )
        return {
            "schema": "HarnessProgressQuantum/v1",
            "state_version_before": int(state_version_before),
            "state_version_after": int(state_version_after),
            "executed_task_ids": list(executed),
            "reused_task_ids": list(reused),
            "new_artifacts": list(artifacts),
            "failure_signature": str(failure_signature),
            "strategy_signature": str(strategy_signature),
            "transport_failure": bool(transport_failure),
            "dependency_materialization_failure": bool(dependency_materialization_failure),
            "useful_progress": useful,
            "duplicate_work": bool(executed and set(executed).issubset(set(reused))),
            "no_progress": not useful,
            "consumes_task_retry": bool(executed and not transport_failure),
            "consumes_strategy_attempt": bool(executed and strategy_signature and not transport_failure),
        }

    @staticmethod
    def continuation_eligibility(
        *,
        objective_satisfied: bool,
        human_gate: bool = False,
        external_gate: bool = False,
        runnable_work: bool = False,
        recoverable_work: bool = False,
        replan_available: bool = False,
        same_strategy_no_progress: bool = False,
        strategy_budget_exhausted: bool = False,
    ) -> str:
        if objective_satisfied:
            return "CONTINUATION_NOT_REQUIRED_OBJECTIVE_SATISFIED"
        if human_gate:
            return "WAITING_HUMAN"
        if external_gate:
            return "WAITING_EXTERNAL"
        if same_strategy_no_progress or (strategy_budget_exhausted and replan_available):
            return "REPLAN_REQUIRED"
        if runnable_work or recoverable_work or replan_available:
            return "CONTINUATION_REQUIRED"
        if strategy_budget_exhausted:
            return "STRATEGY_BUDGET_EXHAUSTED"
        return "FAILED_TERMINAL"
