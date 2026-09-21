from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
from typing import Any, Iterable
from uuid import uuid4

from app.database import harness_learning_repository as repository
from app.services.harness_authorization_service import (
    HarnessAuthorization,
    validate_harness_authorization,
)
from app.services.harness_routing_policy_service import (
    HarnessRoutingDecision,
    HarnessRoutingRequest,
    route_harness_request,
)


MEMORY_TYPES = {
    "EPISODIC",
    "SEMANTIC",
    "PROCEDURAL",
    "FAILURE",
    "HUMAN_FEEDBACK",
    "COMPETENCE",
}
MEMORY_STATUSES = {"CANDIDATE", "ACTIVE", "STALE", "CONTRADICTED", "SUPERSEDED", "RETIRED"}
CANDIDATE_TYPES = {
    "SEMANTIC_LESSON",
    "PROCEDURAL_CHANGE",
    "SKILL_UPDATE",
    "ROUTING_POLICY_CHANGE",
    "FAILURE_RULE",
    "AGENT_COMPETENCE_UPDATE",
    "SOURCE_RELIABILITY_UPDATE",
    "HUMAN_PREFERENCE_RULE",
    "SYSTEM_IMPROVEMENT",
}
TERMINAL_EPISODE_STATUSES = {"COMPLETED", "FAILED", "BLOCKED", "CANCELLED"}
SUCCESS_EPISODE_STATUSES = {"COMPLETED"}
MIN_COMPETENCE_CASES = 2


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    return text


def _refs(values: Iterable[str]) -> tuple[str, ...]:
    normalized = tuple(str(value).strip() for value in values if str(value).strip())
    if len(set(normalized)) != len(normalized):
        raise ValueError("reference values must be unique")
    return normalized


def _stable_id(prefix: str, payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)
    return f"{prefix}-{sha256(raw.encode('utf-8')).hexdigest()[:24]}"


@dataclass
class HarnessWorkingMemory:
    """Ephemeral execution state. It is intentionally not persisted as semantic truth."""

    execution_id: str
    goal_id: str
    state: dict[str, Any] = field(default_factory=dict)
    refs: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.execution_id = _require_text(self.execution_id, "execution_id")
        self.goal_id = _require_text(self.goal_id, "goal_id")

    def put(self, key: str, value: Any, *, evidence_ref: str | None = None) -> None:
        key = _require_text(key, "working memory key")
        self.state[key] = value
        if evidence_ref:
            ref = _require_text(evidence_ref, "evidence_ref")
            if ref not in self.refs:
                self.refs.append(ref)

    def snapshot(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "goal_id": self.goal_id,
            "state": dict(self.state),
            "refs": list(self.refs),
            "persistent": False,
        }


@dataclass(frozen=True)
class HarnessEpisode:
    episode_id: str
    goal_id: str
    decision_id: str
    execution_id: str
    task_id: str
    agent_id: str
    capability_id: str
    domain: str
    task_class: str
    started_at: str
    finished_at: str
    duration_seconds: float
    status: str
    actual_outcome: dict[str, Any]
    outcome_evidence: tuple[str, ...]
    parent_task_id: str | None = None
    skill_id: str | None = None
    skill_version: str | None = None
    provider: str | None = None
    input_refs: tuple[str, ...] = ()
    output_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    tool_calls: tuple[dict[str, Any], ...] = ()
    routing_decision: dict[str, Any] | None = None
    error: str | None = None
    retry_count: int = 0
    human_intervention: bool = False
    qa_results: dict[str, Any] | None = None
    cost: float | None = None
    latency_seconds: float | None = None
    commit_ref: str | None = None
    run_ref: str | None = None
    artifact_refs: tuple[str, ...] = ()
    source_versions: dict[str, str] | None = None
    lineage: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        for field in (
            "episode_id", "goal_id", "decision_id", "execution_id", "task_id",
            "agent_id", "capability_id", "domain", "task_class", "started_at", "finished_at", "status",
        ):
            object.__setattr__(self, field, _require_text(getattr(self, field), field))
        for field in ("input_refs", "output_refs", "evidence_refs", "outcome_evidence", "artifact_refs"):
            object.__setattr__(self, field, _refs(getattr(self, field)))
        if not math.isfinite(float(self.duration_seconds)) or self.duration_seconds < 0:
            raise ValueError("duration_seconds must be finite and non-negative")
        if self.retry_count < 0:
            raise ValueError("retry_count cannot be negative")
        if self.status not in TERMINAL_EPISODE_STATUSES | {"RUNNING", "PENDING"}:
            raise ValueError(f"invalid episode status: {self.status}")
        if self.status in SUCCESS_EPISODE_STATUSES:
            if self.actual_outcome.get("observed") is not True:
                raise ValueError("completed episode requires an observed outcome; agent self-report is insufficient")
            if not self.outcome_evidence:
                raise ValueError("completed episode requires observed outcome evidence")
            if not self.output_refs:
                raise ValueError("completed episode requires output refs")
        if self.actual_outcome.get("agent_report") and self.actual_outcome.get("observed") is not True:
            raise ValueError("agent report cannot substitute for observed outcome")

    def to_record(self) -> dict[str, Any]:
        data = asdict(self)
        data["routing_decision"] = dict(self.routing_decision or {})
        data["qa_results"] = dict(self.qa_results or {})
        data["source_versions"] = dict(self.source_versions or {})
        data["lineage"] = dict(self.lineage or {})
        return data


@dataclass(frozen=True)
class LearningCandidate:
    candidate_id: str
    candidate_type: str
    hypothesis: str
    domain: str
    task_class: str
    source_episode_ids: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    target_agent_id: str | None = None
    target_capability_id: str | None = None
    target_skill_id: str | None = None
    baseline_version: str | None = None
    candidate_version: str | None = None
    contradiction_check: dict[str, Any] | None = None
    implementation_ref: str | None = None
    acceptance_criteria: dict[str, Any] | None = None
    status: str = "CANDIDATE"
    created_at: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidate_id", _require_text(self.candidate_id, "candidate_id"))
        object.__setattr__(self, "hypothesis", _require_text(self.hypothesis, "hypothesis"))
        object.__setattr__(self, "domain", _require_text(self.domain, "domain"))
        object.__setattr__(self, "task_class", _require_text(self.task_class, "task_class"))
        object.__setattr__(self, "source_episode_ids", _refs(self.source_episode_ids))
        object.__setattr__(self, "evidence_refs", _refs(self.evidence_refs))
        if self.candidate_type not in CANDIDATE_TYPES:
            raise ValueError(f"invalid learning candidate type: {self.candidate_type}")
        if not self.source_episode_ids:
            raise ValueError("learning candidate requires source episodes")
        if not self.evidence_refs:
            raise ValueError("learning candidate requires evidence refs")
        if not self.created_at:
            object.__setattr__(self, "created_at", _utcnow())

    def to_record(self) -> dict[str, Any]:
        data = asdict(self)
        data["contradiction_check"] = dict(self.contradiction_check or {})
        data["acceptance_criteria"] = dict(self.acceptance_criteria or {})
        data["promoted_at"] = None
        return data


def persist_episode(episode: HarnessEpisode) -> dict[str, Any]:
    persisted, inserted = repository.insert_episode(episode.to_record())
    if inserted:
        _update_competence_from_episode(persisted)
        # Every terminal observed episode may produce a candidate, but never an
        # ACTIVE canonical memory directly. Promotion remains a separate Harness gate.
        from app.services.memory_plane_service import capture_episode_memory_candidate
        capture_episode_memory_candidate(persisted)
    return persisted


def _update_competence_from_episode(episode: dict[str, Any]) -> dict[str, Any] | None:
    if episode["status"] not in TERMINAL_EPISODE_STATUSES:
        return None
    existing = repository.list_competence(
        domain=episode["domain"],
        task_class=episode["task_class"],
        capability_id=episode["capability_id"],
        agent_id=episode["agent_id"],
        limit=10,
    )
    version = episode.get("skill_version") or "unversioned"
    current = next((item for item in existing if item["version"] == version), None)
    tested_after = (current["tested_cases"] if current else 0) + 1
    success = int(
        episode["status"] == "COMPLETED"
        and isinstance(episode["actual_outcome"], dict)
        and episode["actual_outcome"].get("observed") is True
    )
    failure = 0 if success else 1
    failures = []
    if failure and episode.get("error"):
        failures.append(str(episode["error"])[:300])
    confidence = min(1.0, tested_after / 5.0)
    status = "ACTIVE" if tested_after >= MIN_COMPETENCE_CASES else "UNVERIFIED"
    record = {
        "competence_id": _stable_id("competence", {
            "agent": episode["agent_id"],
            "capability": episode["capability_id"],
            "task_class": episode["task_class"],
            "version": version,
        }),
        "agent_id": episode["agent_id"],
        "skill_id": episode.get("skill_id"),
        "capability_id": episode["capability_id"],
        "domain": episode["domain"],
        "task_class": episode["task_class"],
        "version": version,
        "tested_cases": 1,
        "success_count": success,
        "failure_count": failure,
        "human_correction_count": int(bool(episode.get("human_intervention"))),
        "retry_count": int(episode.get("retry_count") or 0),
        "total_latency_seconds": float(episode.get("latency_seconds") or episode.get("duration_seconds") or 0.0),
        "total_cost": float(episode.get("cost") or 0.0),
        "known_failure_modes": failures,
        "evidence_refs": list(dict.fromkeys([*episode.get("evidence_refs", []), *episode.get("outcome_evidence", [])])),
        "last_verified_at": episode["finished_at"],
        "confidence": confidence,
        "status": status,
    }
    return repository.upsert_competence(record)


def competence_metrics(record: dict[str, Any]) -> dict[str, Any]:
    tested = int(record.get("tested_cases") or 0)
    if tested <= 0:
        return {
            **record,
            "success_rate": None,
            "failure_rate": None,
            "human_correction_rate": None,
            "retry_rate": None,
            "mean_latency_seconds": None,
            "mean_cost": None,
            "evidence_sufficient": False,
        }
    return {
        **record,
        "success_rate": record["success_count"] / tested,
        "failure_rate": record["failure_count"] / tested,
        "human_correction_rate": record["human_correction_count"] / tested,
        "retry_rate": record["retry_count"] / tested,
        "mean_latency_seconds": record["total_latency_seconds"] / tested,
        "mean_cost": record["total_cost"] / tested,
        "evidence_sufficient": bool(record.get("status") == "ACTIVE" and tested >= MIN_COMPETENCE_CASES),
    }


def retrieve_agent_competence(*, domain: str, task_class: str,
                              capability_id: str | None = None,
                              agent_id: str | None = None,
                              limit: int = 20) -> list[dict[str, Any]]:
    return [
        competence_metrics(item)
        for item in repository.list_competence(
            domain=domain,
            task_class=task_class,
            capability_id=capability_id,
            agent_id=agent_id,
            limit=limit,
        )
    ]


def record_memory(*, memory_type: str, claim: str, domain: str,
                  source_episode_ids: Iterable[str], evidence_refs: Iterable[str],
                  task_class: str | None = None, failure_pattern: str | None = None,
                  agent_id: str | None = None, capability_id: str | None = None,
                  skill_id: str | None = None, skill_version: str | None = None,
                  source_versions: dict[str, str] | None = None,
                  metadata: dict[str, Any] | None = None,
                  support_count: int = 1, contradiction_count: int = 0,
                  confidence: float = 0.5, status: str = "CANDIDATE",
                  identity_payload: dict[str, Any] | None = None) -> dict[str, Any]:
    if memory_type not in MEMORY_TYPES:
        raise ValueError(f"invalid memory_type: {memory_type}")
    if status not in MEMORY_STATUSES:
        raise ValueError(f"invalid memory status: {status}")
    if not 0.0 <= float(confidence) <= 1.0:
        raise ValueError("memory confidence must be between 0 and 1")
    source_episode_ids = _refs(source_episode_ids)
    evidence_refs = _refs(evidence_refs)
    if not source_episode_ids or not evidence_refs:
        raise ValueError("persistent memory requires episode and evidence provenance")
    created_at = _utcnow()
    payload = {
        "memory_type": memory_type,
        "claim": _require_text(claim, "claim"),
        "domain": _require_text(domain, "domain"),
        "task_class": task_class,
        "failure_pattern": failure_pattern,
        "source_episode_ids": source_episode_ids,
        "evidence_refs": evidence_refs,
        "agent_id": agent_id,
        "capability_id": capability_id,
        "skill_id": skill_id,
        "skill_version": skill_version,
        "source_versions": dict(source_versions or {}),
        "metadata": dict(metadata or {}),
    }
    fingerprint = sha256(json.dumps(payload, ensure_ascii=True, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    record = {
        **payload,
        "memory_id": _stable_id("memory", identity_payload or payload),
        "support_count": support_count,
        "contradiction_count": contradiction_count,
        "confidence": float(confidence),
        "status": status,
        "fingerprint": fingerprint,
        "created_at": created_at,
        "last_verified_at": created_at if status == "ACTIVE" else None,
    }
    persisted, _ = repository.insert_memory(record)
    return persisted


def retrieve_relevant_memory(*, goal: str, domain: str, task_class: str | None = None,
                             capability: str | None = None, failure_pattern: str | None = None,
                             limit: int = 8) -> list[dict[str, Any]]:
    _require_text(goal, "goal")
    if limit < 1 or limit > 50:
        raise ValueError("memory retrieval limit must be between 1 and 50")
    return repository.list_memories(
        status="ACTIVE",
        domain=domain,
        task_class=task_class,
        capability_id=capability,
        failure_pattern=failure_pattern,
        limit=limit,
    )


def retrieve_known_failure_patterns(*, domain: str, task_class: str | None = None,
                                    capability: str | None = None, limit: int = 8) -> list[dict[str, Any]]:
    return repository.list_memories(
        status="ACTIVE",
        memory_type="FAILURE",
        domain=domain,
        task_class=task_class,
        capability_id=capability,
        limit=limit,
    )


def record_or_reuse_failure_memory(
    *,
    claim: str,
    domain: str,
    task_class: str,
    failure_pattern: str,
    source_episode_id: str,
    evidence_refs: Iterable[str],
    capability_id: str,
    agent_id: str | None = None,
    skill_id: str | None = None,
    skill_version: str | None = None,
    source_versions: dict[str, str] | None = None,
    metadata: dict[str, Any] | None = None,
    confidence: float = 0.8,
) -> dict[str, Any]:
    """Persist one canonical failure pattern and accumulate real recurrences."""
    evidence = _refs(evidence_refs)
    if not evidence:
        raise ValueError("failure memory requires evidence refs")
    existing = repository.find_failure_memory(
        domain=domain,
        task_class=task_class,
        capability_id=capability_id,
        failure_pattern=failure_pattern,
        skill_id=skill_id,
        skill_version=skill_version,
        status="ACTIVE",
    )
    observation = dict(metadata or {})
    observation["episode_id"] = source_episode_id
    observation["observed_at"] = _utcnow()
    if existing is not None:
        return repository.add_failure_memory_observation(
            existing["memory_id"],
            episode_id=source_episode_id,
            evidence_refs=evidence,
            metadata=observation,
            confidence=max(float(existing.get("confidence") or 0.0), confidence),
        )
    initial_metadata = dict(metadata or {})
    initial_metadata["occurrences"] = [observation]
    initial_metadata["recurrence_count"] = 1
    return record_memory(
        memory_type="FAILURE",
        claim=claim,
        domain=domain,
        task_class=task_class,
        failure_pattern=failure_pattern,
        source_episode_ids=(source_episode_id,),
        evidence_refs=evidence,
        agent_id=agent_id,
        capability_id=capability_id,
        skill_id=skill_id,
        skill_version=skill_version,
        source_versions=source_versions,
        metadata=initial_metadata,
        support_count=1,
        contradiction_count=0,
        confidence=confidence,
        status="ACTIVE",
        identity_payload={
            "memory_type": "FAILURE",
            "domain": domain,
            "task_class": task_class,
            "capability_id": capability_id,
            "failure_pattern": failure_pattern,
            "agent_id": agent_id,
            "skill_id": skill_id,
            "skill_version": skill_version,
        },
    )


def mark_stale_memories_for_version_change(*, current_versions: dict[str, str],
                                           domain: str | None = None) -> list[str]:
    stale: list[str] = []
    for memory in repository.list_memories(status="ACTIVE", domain=domain, limit=500):
        source_versions = memory.get("source_versions") or {}
        changed = any(
            key in current_versions and current_versions[key] != value
            for key, value in source_versions.items()
        )
        if changed:
            repository.update_memory_status(memory["memory_id"], "STALE")
            stale.append(memory["memory_id"])
    return stale


def contradict_memory(memory_id: str, *, evidence_ref: str) -> None:
    _require_text(evidence_ref, "evidence_ref")
    repository.update_memory_status(memory_id, "CONTRADICTED", last_verified_at=_utcnow())


def record_human_correction(*, context: str, undesired_behavior: str, desired_behavior: str,
                            evidence_refs: Iterable[str], goal_id: str | None = None,
                            task_id: str | None = None, affected_agent: str | None = None,
                            affected_capability: str | None = None, affected_skill: str | None = None,
                            metadata: dict[str, Any] | None = None,
                            scope: str = "LOCAL") -> dict[str, Any]:
    evidence_refs = _refs(evidence_refs)
    if not evidence_refs:
        raise ValueError("human correction requires evidence")
    if scope not in {"LOCAL", "TASK_CLASS", "GLOBAL_CANDIDATE"}:
        raise ValueError("invalid human correction scope")
    payload = {
        "goal_id": goal_id,
        "task_id": task_id,
        "context": _require_text(context, "context"),
        "undesired_behavior": _require_text(undesired_behavior, "undesired_behavior"),
        "desired_behavior": _require_text(desired_behavior, "desired_behavior"),
        "affected_agent": affected_agent,
        "affected_capability": affected_capability,
        "affected_skill": affected_skill,
        "evidence_refs": evidence_refs,
        "metadata": dict(metadata or {}),
        "scope": scope,
    }
    record = {
        **payload,
        "correction_id": _stable_id("correction", payload),
        "status": "CANDIDATE",
        "created_at": _utcnow(),
    }
    return repository.insert_human_correction(record)


def retrieve_relevant_human_feedback(*, capability: str | None = None,
                                     skill_id: str | None = None,
                                     limit: int = 8) -> list[dict[str, Any]]:
    return repository.list_human_corrections(
        affected_capability=capability,
        affected_skill=skill_id,
        status="CANDIDATE",
        limit=limit,
    )


def create_learning_candidate(*, candidate_type: str, hypothesis: str, domain: str,
                              task_class: str, source_episode_ids: Iterable[str],
                              evidence_refs: Iterable[str], target_agent_id: str | None = None,
                              target_capability_id: str | None = None,
                              target_skill_id: str | None = None,
                              baseline_version: str | None = None,
                              candidate_version: str | None = None,
                              contradiction_check: dict[str, Any] | None = None,
                              implementation_ref: str | None = None,
                              acceptance_criteria: dict[str, Any] | None = None) -> dict[str, Any]:
    source_episode_ids = _refs(source_episode_ids)
    evidence_refs = _refs(evidence_refs)
    payload = {
        "candidate_type": candidate_type,
        "hypothesis": hypothesis,
        "domain": domain,
        "task_class": task_class,
        "source_episode_ids": source_episode_ids,
        "evidence_refs": evidence_refs,
        "target_agent_id": target_agent_id,
        "target_capability_id": target_capability_id,
        "target_skill_id": target_skill_id,
        "baseline_version": baseline_version,
        "candidate_version": candidate_version,
        "implementation_ref": implementation_ref,
        "acceptance_criteria": dict(acceptance_criteria or {}),
    }
    candidate = LearningCandidate(
        candidate_id=_stable_id("candidate", payload),
        candidate_type=candidate_type,
        hypothesis=hypothesis,
        domain=domain,
        task_class=task_class,
        source_episode_ids=source_episode_ids,
        evidence_refs=evidence_refs,
        target_agent_id=target_agent_id,
        target_capability_id=target_capability_id,
        target_skill_id=target_skill_id,
        baseline_version=baseline_version,
        candidate_version=candidate_version,
        contradiction_check=contradiction_check or {"status": "NO_CONTRADICTION_FOUND"},
        implementation_ref=implementation_ref,
        acceptance_criteria=dict(acceptance_criteria or {}),
    )
    existing = repository.get_learning_candidate(candidate.candidate_id)
    if existing is not None:
        return existing
    return repository.insert_learning_candidate(candidate.to_record())


_REQUIRED_EVAL_METRICS = {
    "task_success_rate",
    "quality",
    "human_correction_rate",
    "retry_rate",
    "failure_recurrence",
    "latency_seconds",
    "cost",
    "policy_violations",
}


def _validate_eval_metrics(metrics: dict[str, Any], label: str) -> dict[str, float]:
    missing = _REQUIRED_EVAL_METRICS - set(metrics)
    if missing:
        raise ValueError(f"{label} metrics missing: {sorted(missing)}")
    result: dict[str, float] = {}
    for key in _REQUIRED_EVAL_METRICS:
        value = metrics[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            raise ValueError(f"{label} metric {key} must be finite")
        number = float(value)
        if key in {"task_success_rate", "quality", "human_correction_rate", "retry_rate", "failure_recurrence"} and not 0.0 <= number <= 1.0:
            raise ValueError(f"{label} metric {key} must be between 0 and 1")
        if key in {"latency_seconds", "cost", "policy_violations"} and number < 0:
            raise ValueError(f"{label} metric {key} cannot be negative")
        result[key] = number
    return result


def evaluate_candidate(*, candidate_id: str, baseline_metrics: dict[str, Any],
                       candidate_metrics: dict[str, Any], trials: int,
                       regression_pass: bool, adversarial_pass: bool,
                       critical_regression: bool, evidence_refs: Iterable[str]) -> dict[str, Any]:
    candidate = repository.get_learning_candidate(candidate_id)
    if candidate is None:
        raise ValueError("learning candidate not found")
    if candidate.get("implementation_ref"):
        raise PermissionError(
            "executable candidates require evaluation derived from observed results"
        )
    if trials < 1:
        raise ValueError("evaluation requires at least one trial")
    baseline = _validate_eval_metrics(baseline_metrics, "baseline")
    challenger = _validate_eval_metrics(candidate_metrics, "candidate")
    evidence_refs = _refs(evidence_refs)
    if not evidence_refs:
        raise ValueError("evaluation requires evidence refs")

    hard_gate = regression_pass and adversarial_pass and not critical_regression
    non_regression = (
        challenger["task_success_rate"] >= baseline["task_success_rate"]
        and challenger["quality"] >= baseline["quality"]
        and challenger["policy_violations"] <= baseline["policy_violations"]
    )
    measurable_improvement = any((
        challenger["task_success_rate"] > baseline["task_success_rate"],
        challenger["quality"] > baseline["quality"],
        challenger["human_correction_rate"] < baseline["human_correction_rate"],
        challenger["retry_rate"] < baseline["retry_rate"],
        challenger["failure_recurrence"] < baseline["failure_recurrence"],
        challenger["latency_seconds"] < baseline["latency_seconds"],
        challenger["cost"] < baseline["cost"],
    ))
    if hard_gate and non_regression and measurable_improvement:
        decision = "PROMOTE"
    elif not hard_gate or not non_regression:
        decision = "REJECT_REGRESSION"
    else:
        decision = "REJECT_NO_MEASURABLE_IMPROVEMENT"

    record = {
        "evaluation_id": _stable_id("eval", {
            "candidate_id": candidate_id,
            "baseline": baseline,
            "candidate": challenger,
            "trials": trials,
            "evidence_refs": evidence_refs,
        }),
        "candidate_id": candidate_id,
        "baseline_metrics": baseline,
        "candidate_metrics": challenger,
        "trials": trials,
        "regression_pass": regression_pass,
        "adversarial_pass": adversarial_pass,
        "critical_regression": critical_regression,
        "evaluation_mode": "LEGACY_CALLER_ASSERTED",
        "regression_evidence": {"source": "caller_assertion"},
        "adversarial_evidence": {"source": "caller_assertion"},
        "observed_evidence": {},
        "decision": decision,
        "evidence_refs": evidence_refs,
        "created_at": _utcnow(),
    }
    persisted = repository.insert_evaluation(record)
    repository.update_learning_candidate_status(
        candidate_id,
        "EVALUATED" if decision == "PROMOTE" else "REJECTED",
    )
    return persisted



def evaluate_candidate_from_observed_results(
    *,
    candidate_id: str,
    baseline_observation: dict[str, Any],
    candidate_observation: dict[str, Any],
    regression_observation: dict[str, Any],
    adversarial_observation: dict[str, Any] | None = None,
    evidence_refs: Iterable[str] = (),
) -> dict[str, Any]:
    """Derive all evaluation gates from persisted/observed execution evidence."""
    candidate = repository.get_learning_candidate(candidate_id)
    if candidate is None:
        raise ValueError("learning candidate not found")
    if not candidate.get("implementation_ref"):
        raise ValueError("observed evaluator requires an executable candidate")

    def observed_run(value: dict[str, Any], label: str) -> tuple[dict[str, float], tuple[str, ...], str]:
        if not isinstance(value, dict) or value.get("observed") is not True:
            raise ValueError(f"{label} must be an observed execution result")
        refs = _refs(value.get("evidence_refs") or ())
        if not refs:
            raise ValueError(f"{label} requires evidence refs")
        fingerprint = _require_text(value.get("workload_fingerprint"), f"{label}.workload_fingerprint")
        return _validate_eval_metrics(dict(value.get("metrics") or {}), label), refs, fingerprint

    baseline, baseline_refs, baseline_workload = observed_run(
        baseline_observation, "baseline"
    )
    challenger, candidate_refs, candidate_workload = observed_run(
        candidate_observation, "candidate"
    )
    if baseline_workload != candidate_workload:
        raise ValueError("baseline/candidate workload fingerprints differ")

    if not isinstance(regression_observation, dict) or regression_observation.get("observed") is not True:
        raise ValueError("regression result must be observed")
    regression_status = str(regression_observation.get("status") or "").upper()
    if regression_status not in {"PASS", "FAIL"}:
        raise ValueError("regression status must be PASS or FAIL")
    regression_refs = _refs(regression_observation.get("evidence_refs") or ())
    if not regression_refs:
        raise ValueError("regression observation requires evidence refs")
    critical_failures = tuple(
        str(item) for item in (regression_observation.get("critical_failures") or ())
        if str(item)
    )

    adversarial = dict(adversarial_observation or {
        "observed": True,
        "status": "N/A",
        "reason": "No adversarial surface is applicable to deterministic encoder-preset benchmarking.",
        "evidence_refs": (),
    })
    if adversarial.get("observed") is not True:
        raise ValueError("adversarial result must be observed or explicit N/A")
    adversarial_status = str(adversarial.get("status") or "").upper()
    if adversarial_status not in {"PASS", "FAIL", "N/A"}:
        raise ValueError("adversarial status must be PASS, FAIL, or N/A")
    if adversarial_status == "N/A" and not str(adversarial.get("reason") or "").strip():
        raise ValueError("adversarial N/A requires a justification")
    adversarial_refs = _refs(adversarial.get("evidence_refs") or ())

    regression_pass = regression_status == "PASS"
    adversarial_gate = adversarial_status in {"PASS", "N/A"}
    critical_regression = bool(critical_failures)
    non_regression = (
        challenger["task_success_rate"] >= baseline["task_success_rate"]
        and challenger["quality"] >= baseline["quality"]
        and challenger["policy_violations"] <= baseline["policy_violations"]
    )

    criteria = dict(candidate.get("acceptance_criteria") or {})
    latency_reduction = 0.0
    if baseline["latency_seconds"] > 0:
        latency_reduction = (
            baseline["latency_seconds"] - challenger["latency_seconds"]
        ) / baseline["latency_seconds"]
    task_success_increase = (
        challenger["task_success_rate"] - baseline["task_success_rate"]
    )
    quality_increase = challenger["quality"] - baseline["quality"]

    improvement_checks: list[bool] = []
    if "min_latency_reduction_fraction" in criteria:
        minimum_latency_reduction = float(
            criteria["min_latency_reduction_fraction"]
        )
        improvement_checks.append(
            challenger["latency_seconds"] < baseline["latency_seconds"]
            and latency_reduction >= minimum_latency_reduction
        )
    else:
        minimum_latency_reduction = None
    if "min_task_success_rate_increase" in criteria:
        improvement_checks.append(
            task_success_increase
            >= float(criteria["min_task_success_rate_increase"])
        )
    if "min_quality_increase" in criteria:
        improvement_checks.append(
            quality_increase >= float(criteria["min_quality_increase"])
        )
    if "max_candidate_latency_seconds" in criteria:
        improvement_checks.append(
            challenger["latency_seconds"]
            <= float(criteria["max_candidate_latency_seconds"])
        )
    if "max_policy_violations" in criteria:
        improvement_checks.append(
            challenger["policy_violations"]
            <= float(criteria["max_policy_violations"])
        )

    measurable_improvement = (
        all(improvement_checks)
        if improvement_checks
        else any((
            task_success_increase > 0,
            quality_increase > 0,
            challenger["human_correction_rate"] < baseline["human_correction_rate"],
            challenger["retry_rate"] < baseline["retry_rate"],
            challenger["failure_recurrence"] < baseline["failure_recurrence"],
            challenger["latency_seconds"] < baseline["latency_seconds"],
            challenger["cost"] < baseline["cost"],
        ))
    )
    hard_gate = regression_pass and adversarial_gate and not critical_regression

    if hard_gate and non_regression and measurable_improvement:
        decision = "PROMOTE"
    elif not hard_gate or not non_regression:
        decision = "REJECT_REGRESSION"
    else:
        decision = "REJECT_NO_MEASURABLE_IMPROVEMENT"

    combined_refs = _refs(dict.fromkeys([
        *baseline_refs,
        *candidate_refs,
        *regression_refs,
        *adversarial_refs,
        *_refs(evidence_refs),
    ]).keys())
    record = {
        "evaluation_id": _stable_id("eval", {
            "candidate_id": candidate_id,
            "baseline": baseline,
            "candidate": challenger,
            "workload_fingerprint": baseline_workload,
            "evidence_refs": combined_refs,
        }),
        "candidate_id": candidate_id,
        "baseline_metrics": baseline,
        "candidate_metrics": challenger,
        "trials": 2,
        "regression_pass": regression_pass,
        "adversarial_pass": adversarial_gate,
        "critical_regression": critical_regression,
        "evaluation_mode": "OBSERVED",
        "regression_evidence": dict(regression_observation),
        "adversarial_evidence": adversarial,
        "observed_evidence": {
            "baseline": dict(baseline_observation),
            "candidate": dict(candidate_observation),
            "workload_fingerprint": baseline_workload,
            "latency_reduction_fraction": latency_reduction,
            "minimum_latency_reduction_fraction": minimum_latency_reduction,
            "task_success_rate_increase": task_success_increase,
            "quality_increase": quality_increase,
            "acceptance_criteria": criteria,
            "measurable_improvement": measurable_improvement,
        },
        "decision": decision,
        "evidence_refs": combined_refs,
        "created_at": _utcnow(),
    }
    persisted = repository.insert_evaluation(record)
    repository.update_learning_candidate_status(
        candidate_id,
        "EVALUATED" if decision == "PROMOTE" else "REJECTED",
    )
    return persisted

def register_skill_version(*, skill_id: str, version: str, content_ref: str, checksum: str,
                           status: str, evidence_refs: Iterable[str],
                           parent_version: str | None = None) -> dict[str, Any]:
    persisted = repository.insert_version(
        table="harness_skill_versions",
        identity_field="skill_id",
        record={
            "skill_id": _require_text(skill_id, "skill_id"),
            "version": _require_text(version, "version"),
            "parent_version": parent_version,
            "content_ref": _require_text(content_ref, "content_ref"),
            "checksum": _require_text(checksum, "checksum"),
            "status": _require_text(status, "status"),
            "evidence_refs": _refs(evidence_refs),
            "created_at": _utcnow(),
            "promoted_at": None,
        },
    )
    return persisted

def register_policy_version(*, policy_id: str, version: str, content_ref: str, checksum: str,
                            status: str, evidence_refs: Iterable[str],
                            parent_version: str | None = None) -> dict[str, Any]:
    persisted = repository.insert_version(
        table="harness_policy_versions",
        identity_field="policy_id",
        record={
            "policy_id": _require_text(policy_id, "policy_id"),
            "version": _require_text(version, "version"),
            "parent_version": parent_version,
            "content_ref": _require_text(content_ref, "content_ref"),
            "checksum": _require_text(checksum, "checksum"),
            "status": _require_text(status, "status"),
            "evidence_refs": _refs(evidence_refs),
            "created_at": _utcnow(),
            "promoted_at": None,
        },
    )
    return persisted

def promote_candidate(*, candidate_id: str, evaluation: dict[str, Any],
                      authorization: HarnessAuthorization | dict[str, Any] | str,
                      memory_claim: str, memory_type: str,
                      source_versions: dict[str, str] | None = None) -> dict[str, Any]:
    candidate = repository.get_learning_candidate(candidate_id)
    if candidate is None:
        raise ValueError("learning candidate not found")
    if evaluation.get("candidate_id") != candidate_id or evaluation.get("decision") != "PROMOTE":
        raise PermissionError("candidate cannot be promoted without a passing evaluation")
    if candidate.get("implementation_ref") and evaluation.get("evaluation_mode") != "OBSERVED":
        raise PermissionError("executable candidate promotion requires observed evaluation")
    authorization = validate_harness_authorization(
        authorization,
        expected_action="EXECUTION",
        expected_subject=f"learning:candidate:{candidate_id}",
    )
    promoted_at = _utcnow()
    repository.update_learning_candidate_status(candidate_id, "PROMOTED", promoted_at=promoted_at)

    if candidate.get("target_skill_id") and candidate.get("candidate_version") and candidate["candidate_type"] == "SKILL_UPDATE":
        version_record = repository.get_version(
            table="harness_skill_versions",
            identity_field="skill_id",
            identity=candidate["target_skill_id"],
            version=candidate["candidate_version"],
        )
        if version_record is None:
            raise PermissionError("candidate executable skill version is not registered")
        if candidate.get("implementation_ref") and version_record.get("content_ref") != candidate["implementation_ref"]:
            raise PermissionError("candidate implementation_ref does not match registered executable version")
        repository.activate_version(
            table="harness_skill_versions",
            identity_field="skill_id",
            identity=candidate["target_skill_id"],
            version=candidate["candidate_version"],
            promoted_at=promoted_at,
        )
        mark_stale_memories_for_version_change(
            current_versions={
                "skill": candidate["candidate_version"],
                f"skill:{candidate['target_skill_id']}": candidate["candidate_version"],
            },
            domain=candidate["domain"],
        )
    if candidate.get("candidate_version") and candidate["candidate_type"] == "ROUTING_POLICY_CHANGE":
        policy_id = candidate.get("target_skill_id") or "harness-routing-policy"
        repository.activate_version(
            table="harness_policy_versions",
            identity_field="policy_id",
            identity=policy_id,
            version=candidate["candidate_version"],
            promoted_at=promoted_at,
        )
        mark_stale_memories_for_version_change(
            current_versions={
                "policy": candidate["candidate_version"],
                f"policy:{policy_id}": candidate["candidate_version"],
            },
            domain=candidate["domain"],
        )

    memory = record_memory(
        memory_type=memory_type,
        claim=memory_claim,
        domain=candidate["domain"],
        task_class=candidate["task_class"],
        source_episode_ids=candidate["source_episode_ids"],
        evidence_refs=list(dict.fromkeys([*candidate["evidence_refs"], *evaluation.get("evidence_refs", [])])),
        agent_id=candidate.get("target_agent_id"),
        capability_id=candidate.get("target_capability_id"),
        skill_id=candidate.get("target_skill_id"),
        skill_version=candidate.get("candidate_version"),
        source_versions=source_versions,
        metadata={
            "promotion_authorization_id": authorization.authorization_id,
            "implementation_ref": candidate.get("implementation_ref"),
            "evaluation_id": evaluation.get("evaluation_id"),
            "evaluation_mode": evaluation.get("evaluation_mode"),
        },
        support_count=max(1, int(evaluation.get("trials") or 1)),
        contradiction_count=0,
        confidence=min(1.0, 0.5 + min(int(evaluation.get("trials") or 1), 5) * 0.1),
        status="ACTIVE",
    )
    return {
        "status": "PROMOTED",
        "authority": authorization.authority,
        "authorization_id": authorization.authorization_id,
        "candidate": repository.get_learning_candidate(candidate_id),
        "evaluation": evaluation,
        "memory": memory,
    }


def route_harness_request_with_learning(
    request: HarnessRoutingRequest,
    *,
    goal: str,
    registry=None,
) -> tuple[HarnessRoutingDecision, dict[str, Any]]:
    """Compatibility facade over the normal learning-aware Harness boundary.

    Learning is no longer enabled by this helper. route_harness_request()
    performs the retrieval automatically whenever domain + task_class exist.
    This helper only exposes the persisted retrieval evidence to legacy callers.
    """
    if not request.domain or not request.task_class:
        raise ValueError("learning-aware routing requires domain and task_class")
    _require_text(goal, "goal")
    enriched = replace(
        request,
        goal_id=request.goal_id or goal,
        learning_required=True,
    )
    kwargs = {} if registry is None else {"registry": registry}
    decision = route_harness_request(enriched, **kwargs)
    context = dict(decision.policy_metadata.get("learning_context") or {})
    proof = {
        "goal": goal,
        "task_class": request.task_class,
        "competence_records_considered": list(
            context.get("competence_records") or ()
        ),
        "memory_ids_retrieved": list(
            context.get("retrieved_memory_ids") or ()
        ),
        "failure_memory_ids_retrieved": list(
            context.get("retrieved_failure_memory_ids") or ()
        ),
        "human_feedback_ids_retrieved": list(
            context.get("retrieved_human_feedback_ids") or ()
        ),
        "active_skill_versions": list(
            context.get("active_skill_versions") or ()
        ),
        "active_policy_versions": list(
            context.get("active_policy_versions") or ()
        ),
        "selected_capability_id": decision.selected_capability_id,
        "routing_id": decision.routing_id,
        "learning_participated": bool(context.get("learning_participated")),
    }
    return decision, proof

def create_improvement_mission(*, trigger_type: str, trigger_refs: Iterable[str],
                               diagnosis: str, hypothesis: str,
                               authorization: HarnessAuthorization | dict[str, Any] | str,
                               candidate_id: str | None = None,
                               evidence_considered: Iterable[str] = (),
                               affected_capability: str | None = None,
                               affected_config: str | None = None,
                               objective: str | None = None,
                               constraints: Iterable[str] = (),
                               acceptance_criteria: dict[str, Any] | None = None) -> dict[str, Any]:
    authorization = validate_harness_authorization(
        authorization,
        expected_action="EXECUTION",
        expected_subject="learning:improvement",
    )
    trigger_refs = _refs(trigger_refs)
    payload = {
        "trigger_type": _require_text(trigger_type, "trigger_type"),
        "trigger_refs": trigger_refs,
        "diagnosis": _require_text(diagnosis, "diagnosis"),
        "hypothesis": _require_text(hypothesis, "hypothesis"),
        "evidence_considered": _refs(evidence_considered),
        "affected_capability": affected_capability,
        "affected_config": affected_config,
        "objective": objective,
        "constraints": _refs(constraints),
        "acceptance_criteria": dict(acceptance_criteria or {}),
        "candidate_id": candidate_id,
        "harness_decision_id": authorization.harness_decision_id,
        "authorization_id": authorization.authorization_id,
    }
    return repository.insert_improvement_mission({
        **payload,
        "improvement_mission_id": _stable_id("improvement", payload),
        "status": "AUTHORIZED",
        "created_at": _utcnow(),
        "finished_at": None,
    })

def attach_candidate_to_improvement_mission(
    *,
    improvement_mission_id: str,
    candidate_id: str,
    authorization: HarnessAuthorization | dict[str, Any] | str,
) -> dict[str, Any]:
    authorization = validate_harness_authorization(
        authorization,
        expected_action="EXECUTION",
        expected_subject="learning:improvement",
    )
    mission = repository.get_improvement_mission(improvement_mission_id)
    if mission is None:
        raise ValueError("improvement mission not found")
    candidate = repository.get_learning_candidate(candidate_id)
    if candidate is None:
        raise ValueError("learning candidate not found")
    if mission.get("affected_capability") and candidate.get("target_capability_id"):
        if mission["affected_capability"] != candidate["target_capability_id"]:
            raise PermissionError("candidate capability does not match improvement mission")
    return repository.attach_candidate_to_improvement_mission(
        improvement_mission_id,
        candidate_id=candidate_id,
    )


def complete_improvement_mission(*, improvement_mission_id: str,
                                 authorization: HarnessAuthorization | dict[str, Any] | str) -> dict[str, Any]:
    authorization = validate_harness_authorization(
        authorization,
        expected_action="EXECUTION",
        expected_subject="learning:improvement",
    )
    mission = repository.get_improvement_mission(improvement_mission_id)
    if mission is None:
        raise ValueError("improvement mission not found")
    if (
        mission["authorization_id"] != authorization.authorization_id
        and authorization.lineage.get("improvement_mission_id") != improvement_mission_id
    ):
        raise PermissionError("improvement mission completion authorization lineage mismatch")
    candidate_id = mission.get("candidate_id")
    if not candidate_id:
        raise PermissionError("improvement mission has no evaluated candidate")
    candidate = repository.get_learning_candidate(candidate_id)
    if candidate is None or candidate.get("status") != "PROMOTED":
        raise PermissionError("improvement mission cannot complete before candidate promotion")
    return repository.update_improvement_mission_status(
        improvement_mission_id,
        "COMPLETED",
        finished_at=_utcnow(),
    )
