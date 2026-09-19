from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import math
from typing import Any, Iterable, Mapping

POLICY_ID = "br-no-gta.operational-efficiency"
POLICY_VERSION = "v2"
POLICY_PRINCIPLE = (
    "MEASURE -> PROFILE -> REMOVE_REDUNDANT_WORK -> CACHE -> REUSE -> "
    "PARALLELIZE_ONLY_WHEN_SAFE -> CHECKPOINT -> QA -> COMPARE -> "
    "PROMOTE_ONLY_IF_NO_QUALITY_REGRESSION"
)

_REQUIRED_OBSERVABILITY_FIELDS = (
    "operation_id",
    "capability_id",
    "stage",
    "elapsed_seconds",
    "cache_hit",
    "cache_miss",
    "retry_count",
    "reused_artifacts",
    "external_calls",
    "output_artifact",
)

_PERFORMANCE_METRICS = (
    "wall_clock_seconds",
    "external_calls",
    "process_count",
    "encode_count",
    "decode_count",
    "download_count",
    "artifact_size_bytes",
    "cpu_seconds",
    "peak_rss_bytes",
    "disk_bytes_written",
)


class OperationalEfficiencyPolicyError(ValueError):
    pass


@dataclass(frozen=True)
class PromotionDecision:
    policy_id: str
    policy_version: str
    decision: str
    performance_improved: bool
    technical_qa_no_regression: bool
    human_quality_applicable: bool
    human_quality_no_regression: bool | None
    improved_metrics: tuple[str, ...]
    regressed_metrics: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    guardrail_pass: bool
    guardrail_violations: tuple[str, ...]
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def policy_metadata() -> dict[str, Any]:
    return {
        "policy_id": POLICY_ID,
        "version": POLICY_VERSION,
        "principle": POLICY_PRINCIPLE,
        "promotion_rule": (
            "PERFORMANCE_IMPROVED=OBSERVED AND TECHNICAL_QA_NO_REGRESSION=PASS "
            "AND, when perceptual/editorial quality can change, HUMAN_QUALITY_NO_REGRESSION=PASS"
        ),
        "quality_priority": "human quality outranks automatic performance scores",
        "benchmark_reuse": (
            "reuse prior benchmark when workload fingerprint and relevant provider/skill/policy versions match"
        ),
        "run_classes": ["COLD_RUN", "WARM_RETRY"],
        "baseline_statistics": ["p50", "p95"],
        "guardrail_rule": "candidate may not regress protected metrics beyond their explicit budget",
        "observability_required_fields": list(_REQUIRED_OBSERVABILITY_FIELDS),
    }


def canonical_fingerprint(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        dict(payload), ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def benchmark_reuse_key(
    *,
    capability_id: str,
    workload_fingerprint: str,
    provider_versions: Mapping[str, str] | None = None,
    skill_versions: Mapping[str, str] | None = None,
    policy_versions: Mapping[str, str] | None = None,
) -> str:
    if not capability_id or not workload_fingerprint:
        raise OperationalEfficiencyPolicyError("capability_id and workload_fingerprint are required")
    return canonical_fingerprint({
        "policy_id": POLICY_ID,
        "policy_version": POLICY_VERSION,
        "capability_id": capability_id,
        "workload_fingerprint": workload_fingerprint,
        "provider_versions": dict(provider_versions or {}),
        "skill_versions": dict(skill_versions or {}),
        "policy_versions": dict(policy_versions or {}),
    })


def benchmark_can_be_reused(
    previous: Mapping[str, Any] | None,
    *,
    capability_id: str,
    workload_fingerprint: str,
    provider_versions: Mapping[str, str] | None = None,
    skill_versions: Mapping[str, str] | None = None,
    policy_versions: Mapping[str, str] | None = None,
) -> bool:
    if not previous or previous.get("status") != "PASS":
        return False
    expected = benchmark_reuse_key(
        capability_id=capability_id,
        workload_fingerprint=workload_fingerprint,
        provider_versions=provider_versions,
        skill_versions=skill_versions,
        policy_versions=policy_versions,
    )
    return previous.get("benchmark_reuse_key") == expected


def _finite_nonnegative(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise OperationalEfficiencyPolicyError(f"{label} must be numeric")
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise OperationalEfficiencyPolicyError(f"{label} must be finite and non-negative")
    return number


def validate_observability_event(event: Mapping[str, Any]) -> dict[str, Any]:
    missing = [key for key in _REQUIRED_OBSERVABILITY_FIELDS if key not in event]
    if missing:
        raise OperationalEfficiencyPolicyError(
            f"observability event missing required fields: {sorted(missing)}"
        )
    result = dict(event)
    for key in ("elapsed_seconds", "cache_hit", "cache_miss", "retry_count", "external_calls"):
        result[key] = _finite_nonnegative(result[key], key)
    reused = result.get("reused_artifacts")
    if not isinstance(reused, (list, tuple)):
        raise OperationalEfficiencyPolicyError("reused_artifacts must be a list")
    if not str(result.get("operation_id") or "").strip():
        raise OperationalEfficiencyPolicyError("operation_id is required")
    if not str(result.get("capability_id") or "").strip():
        raise OperationalEfficiencyPolicyError("capability_id is required")
    if not str(result.get("stage") or "").strip():
        raise OperationalEfficiencyPolicyError("stage is required")
    if not str(result.get("output_artifact") or "").strip():
        raise OperationalEfficiencyPolicyError("output_artifact is required")
    return result


def compare_performance(
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    improved: list[str] = []
    regressed: list[str] = []
    for metric in _PERFORMANCE_METRICS:
        if metric not in baseline or metric not in candidate:
            continue
        old = _finite_nonnegative(baseline[metric], f"baseline.{metric}")
        new = _finite_nonnegative(candidate[metric], f"candidate.{metric}")
        if new < old:
            improved.append(metric)
        elif new > old:
            regressed.append(metric)

    if "cache_hit_rate" in baseline and "cache_hit_rate" in candidate:
        old = _finite_nonnegative(baseline["cache_hit_rate"], "baseline.cache_hit_rate")
        new = _finite_nonnegative(candidate["cache_hit_rate"], "candidate.cache_hit_rate")
        if old > 1 or new > 1:
            raise OperationalEfficiencyPolicyError("cache_hit_rate must be within [0,1]")
        if new > old:
            improved.append("cache_hit_rate")
        elif new < old:
            regressed.append("cache_hit_rate")

    return tuple(sorted(set(improved))), tuple(sorted(set(regressed)))


def evaluate_optimization_promotion(
    *,
    baseline_observation: Mapping[str, Any],
    candidate_observation: Mapping[str, Any],
    technical_qa_no_regression: bool,
    human_quality_applicable: bool,
    human_quality_no_regression: bool | None,
    evidence_refs: Iterable[str],
    guardrail_budgets: Mapping[str, float] | None = None,
) -> PromotionDecision:
    if baseline_observation.get("observed") is not True:
        raise OperationalEfficiencyPolicyError("baseline performance must be OBSERVED")
    if candidate_observation.get("observed") is not True:
        raise OperationalEfficiencyPolicyError("candidate performance must be OBSERVED")
    baseline_fp = str(baseline_observation.get("workload_fingerprint") or "")
    candidate_fp = str(candidate_observation.get("workload_fingerprint") or "")
    if not baseline_fp or baseline_fp != candidate_fp:
        raise OperationalEfficiencyPolicyError("baseline/candidate workload fingerprints must match")
    evidence = tuple(dict.fromkeys(str(item) for item in evidence_refs if str(item)))
    if not evidence:
        raise OperationalEfficiencyPolicyError("promotion decision requires evidence refs")

    baseline_metrics = dict(baseline_observation.get("metrics") or {})
    candidate_metrics = dict(candidate_observation.get("metrics") or {})
    improved, regressed = compare_performance(baseline_metrics, candidate_metrics)
    performance_improved = bool(improved)

    budgets = dict(guardrail_budgets or {})
    violations: list[str] = []
    for metric, budget_value in budgets.items():
        budget = _finite_nonnegative(budget_value, f"guardrail_budget.{metric}")
        if metric == "cache_hit_rate":
            if metric in baseline_metrics and metric in candidate_metrics:
                old = _finite_nonnegative(baseline_metrics[metric], f"baseline.{metric}")
                new = _finite_nonnegative(candidate_metrics[metric], f"candidate.{metric}")
                if old - new > budget:
                    violations.append(metric)
            continue
        if metric in baseline_metrics and metric in candidate_metrics:
            old = _finite_nonnegative(baseline_metrics[metric], f"baseline.{metric}")
            new = _finite_nonnegative(candidate_metrics[metric], f"candidate.{metric}")
            allowed = old * (1.0 + budget)
            if new > allowed:
                violations.append(metric)
    guardrail_pass = not violations

    if not guardrail_pass:
        decision = "REJECTED"
        reason = "guardrail regression exceeded allowed budget"
    elif not technical_qa_no_regression:
        decision = "REJECTED"
        reason = "technical QA regression"
    elif not performance_improved:
        decision = "REJECTED"
        reason = "no observed performance improvement"
    elif human_quality_applicable and human_quality_no_regression is not True:
        decision = "REJECTED"
        reason = "human quality non-regression is required for perceptual/editorial changes"
    else:
        decision = "PROMOTED"
        reason = "observed performance improvement with required quality gates"

    return PromotionDecision(
        policy_id=POLICY_ID,
        policy_version=POLICY_VERSION,
        decision=decision,
        performance_improved=performance_improved,
        technical_qa_no_regression=bool(technical_qa_no_regression),
        human_quality_applicable=bool(human_quality_applicable),
        human_quality_no_regression=human_quality_no_regression,
        improved_metrics=improved,
        regressed_metrics=regressed,
        evidence_refs=evidence,
        guardrail_pass=guardrail_pass,
        guardrail_violations=tuple(sorted(set(violations))),
        reason=reason,
    )


def conservative_baseline_when_human_quality_unresolved(
    *,
    baseline_profile: Mapping[str, Any],
    candidate_profile: Mapping[str, Any],
    candidate_changes_perceptual_quality: bool,
    human_quality_no_regression: bool | None,
) -> dict[str, Any]:
    if candidate_changes_perceptual_quality and human_quality_no_regression is not True:
        return {
            "selected": dict(baseline_profile),
            "candidate_status": "NOT_PROMOTED",
            "reason": "human quality non-regression unresolved; preserve canonical baseline",
        }
    return {
        "selected": dict(candidate_profile),
        "candidate_status": "ELIGIBLE_FOR_PERFORMANCE_EVALUATION",
        "reason": "human quality gate does not block candidate evaluation",
    }
