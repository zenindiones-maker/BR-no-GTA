from __future__ import annotations

from dataclasses import asdict, dataclass, replace
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
MEMORY_STATUSES = {"CANDIDATE", "ACTIVE", "STALE", "CONTRADICTED", "RETIRED"}
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
        data["promoted_at"] = None
        return data


def persist_episode(episode: HarnessEpisode) -> dict[str, Any]:
    persisted, _ = repository.insert_episode(episode.to_record())
    _update_competence_from_episode(persisted)
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
                  support_count: int = 1, contradiction_count: int = 0,
                  confidence: float = 0.5, status: str = "CANDIDATE") -> dict[str, Any]:
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
    }
    fingerprint = sha256(json.dumps(payload, ensure_ascii=True, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    record = {
        **payload,
        "memory_id": _stable_id("memory", payload),
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
                              contradiction_check: dict[str, Any] | None = None) -> dict[str, Any]:
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


def register_skill_version(*, skill_id: str, version: str, content_ref: str, checksum: str,
                           status: str, evidence_refs: Iterable[str],
                           parent_version: str | None = None) -> dict[str, Any]:
    return repository.insert_version(
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


def register_policy_version(*, policy_id: str, version: str, content_ref: str, checksum: str,
                            status: str, evidence_refs: Iterable[str],
                            parent_version: str | None = None) -> dict[str, Any]:
    return repository.insert_version(
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


def promote_candidate(*, candidate_id: str, evaluation: dict[str, Any],
                      authorization: HarnessAuthorization | dict[str, Any] | str,
                      memory_claim: str, memory_type: str,
                      source_versions: dict[str, str] | None = None) -> dict[str, Any]:
    candidate = repository.get_learning_candidate(candidate_id)
    if candidate is None:
        raise ValueError("learning candidate not found")
    if evaluation.get("candidate_id") != candidate_id or evaluation.get("decision") != "PROMOTE":
        raise PermissionError("candidate cannot be promoted without a passing evaluation")
    authorization = validate_harness_authorization(
        authorization,
        expected_action="EXECUTION",
        expected_subject=f"learning:candidate:{candidate_id}",
    )
    promoted_at = _utcnow()
    repository.update_learning_candidate_status(candidate_id, "PROMOTED", promoted_at=promoted_at)

    if candidate.get("target_skill_id") and candidate.get("candidate_version") and candidate["candidate_type"] == "SKILL_UPDATE":
        repository.update_version_status(
            table="harness_skill_versions",
            identity_field="skill_id",
            identity=candidate["target_skill_id"],
            version=candidate["candidate_version"],
            status="ACTIVE",
            promoted_at=promoted_at,
        )
    if candidate.get("candidate_version") and candidate["candidate_type"] == "ROUTING_POLICY_CHANGE":
        policy_id = candidate.get("target_skill_id") or "harness-routing-policy"
        repository.update_version_status(
            table="harness_policy_versions",
            identity_field="policy_id",
            identity=policy_id,
            version=candidate["candidate_version"],
            status="ACTIVE",
            promoted_at=promoted_at,
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


def route_harness_request_with_learning(request: HarnessRoutingRequest, *, goal: str,
                                        registry=None) -> tuple[HarnessRoutingDecision, dict[str, Any]]:
    if not request.domain or not request.task_class:
        raise ValueError("learning-aware routing requires domain and task_class")
    competence = retrieve_agent_competence(
        domain=request.domain,
        task_class=request.task_class,
        limit=50,
    )
    active = tuple(
        {
            "agent_id": item["agent_id"],
            "capability_id": item["capability_id"],
            "task_class": item["task_class"],
            "domain": item["domain"],
            "version": item["version"],
            "tested_cases": item["tested_cases"],
            "success_rate": item["success_rate"],
            "failure_rate": item["failure_rate"],
            "human_correction_rate": item["human_correction_rate"],
            "retry_rate": item["retry_rate"],
            "mean_latency_seconds": item["mean_latency_seconds"],
            "mean_cost": item["mean_cost"],
            "confidence": item["confidence"],
            "evidence_refs": item["evidence_refs"],
            "last_verified_at": item["last_verified_at"],
            "status": item["status"],
            "evidence_sufficient": item["evidence_sufficient"],
        }
        for item in competence
        if item["evidence_sufficient"]
    )
    memories = retrieve_relevant_memory(
        goal=goal,
        domain=request.domain,
        task_class=request.task_class,
        capability=request.required_capability_id,
        limit=8,
    )
    enriched = replace(request, competence_records=active)
    kwargs = {} if registry is None else {"registry": registry}
    decision = route_harness_request(enriched, **kwargs)
    proof = {
        "goal": goal,
        "task_class": request.task_class,
        "competence_records_considered": list(active),
        "memory_ids_retrieved": [item["memory_id"] for item in memories],
        "selected_capability_id": decision.selected_capability_id,
        "routing_id": decision.routing_id,
        "learning_participated": bool(active or memories),
    }
    return decision, proof


def create_improvement_mission(*, trigger_type: str, trigger_refs: Iterable[str],
                               diagnosis: str, hypothesis: str,
                               authorization: HarnessAuthorization | dict[str, Any] | str,
                               candidate_id: str | None = None) -> dict[str, Any]:
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
