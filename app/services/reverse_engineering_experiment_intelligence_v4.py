"""A conservative, offline technique experiment assessor for the DeepSeek Harness.

This deliberately does NOT execute candidates, grant authority, write competence
or canonical memory, train an agent, approve BR_OWNER_V1, or promote to production.

Uses strictly paired, pre-registered metric rubrics and an exact one-sided sign
test on a disjoint holdout. Hashes are consistency checks, NOT trusted signatures.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from typing import Any

SCHEMA = "BRTechniqueExperimentDataset/v1"
HEX = re.compile(r"^[0-9a-f]{64}$")
ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,95}$")
DOMAINS = frozenset({"audio", "video", "script", "animation", "web", "software"})
MIN_DEV = 6
MIN_HOLDOUT = 6
MAX_CASES = 128
MAX_TECHNIQUES = 8
SIGNIFICANCE_ALPHA = 0.05


class ExperimentEvidenceError(ValueError):
    pass


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True,
                   separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def _identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise ExperimentEvidenceError(f"EXPERIMENT_{field.upper()}_INVALID")
    return value


def _sha(value: Any, field: str) -> str:
    if not isinstance(value, str) or not HEX.fullmatch(value):
        raise ExperimentEvidenceError(f"EXPERIMENT_{field.upper()}_INVALID")
    return value


def _real(value: Any, field: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ExperimentEvidenceError(f"EXPERIMENT_{field.upper()}_INVALID")
    return float(value)


def _guard_keys(value: Any, keys: set[str], field: str) -> dict:
    if not isinstance(value, dict) or set(value) != keys:
        raise ExperimentEvidenceError(f"EXPERIMENT_{field.upper()}_SCHEMA_INVALID")
    return value


def _score(value: float, rubric: dict) -> float:
    if rubric["direction"] == "lower":
        return -value
    if rubric["direction"] == "higher":
        return value
    return -abs(value - rubric["target"])


def _p_value(wins: int, losses: int) -> float | None:
    """Exact one-sided binomial sign test; ties excluded. No SciPy dependency."""
    total = wins + losses
    if total == 0:
        return None
    # Probability under equal chances of wins/losses. The fixed pre-registered
    # 0.05 threshold is never an invitation to re-sample until significant.
    return min(1.0, sum(math.comb(total, k) for k in range(wins, total + 1)) / (2 ** total))


def _validate_dataset(dataset: Any) -> tuple[dict, dict[str, str]]:
    _guard_keys(dataset, {"schema_version", "dataset_id", "domain", "task_class",
                          "rubric", "cases", "dataset_sha256"}, "DATASET")
    if dataset["schema_version"] != SCHEMA:
        raise ExperimentEvidenceError("EXPERIMENT_DATASET_VERSION_MISMATCH")
    _identifier(dataset["dataset_id"], "dataset_id")
    _identifier(dataset["task_class"], "task_class")
    if dataset["domain"] not in DOMAINS:
        raise ExperimentEvidenceError("EXPERIMENT_DOMAIN_UNSUPPORTED")
    rubric = _guard_keys(
        dataset["rubric"],
        {"metric", "direction", "target", "tolerance", "measurement_method", "zero_cost"},
        "RUBRIC",
    )
    _identifier(rubric["metric"], "metric")
    _identifier(rubric["measurement_method"], "measurement_method")
    if rubric["direction"] not in {"lower", "higher", "target"}:
        raise ExperimentEvidenceError("EXPERIMENT_DIRECTION_INVALID")
    if rubric["direction"] == "target":
        _real(rubric["target"], "target")
    elif rubric["target"] is not None:
        raise ExperimentEvidenceError("EXPERIMENT_TARGET_UNEXPECTED")
    if not 0 <= _real(rubric["tolerance"], "tolerance") <= 100:
        raise ExperimentEvidenceError("EXPERIMENT_TOLERANCE_INVALID")
    if rubric["zero_cost"] is not True:
        raise ExperimentEvidenceError("EXPERIMENT_ZERO_COST_REQUIRED")
    cases = dataset["cases"]
    if not isinstance(cases, list) or not 1 <= len(cases) <= MAX_CASES:
        raise ExperimentEvidenceError("EXPERIMENT_CASES_BOUNDS_INVALID")
    case_ids: dict[str, str] = {}
    for row in cases:
        _guard_keys(row, {"case_id", "split", "reference_sha256"}, "CASE")
        case_id = _identifier(row["case_id"], "case_id")
        _sha(row["reference_sha256"], "reference_sha256")
        if case_id in case_ids or row["split"] not in {"development", "holdout"}:
            raise ExperimentEvidenceError("EXPERIMENT_CASE_SPLIT_OR_DUPLICATE")
        case_ids[case_id] = row["split"]
    actual_digest = _hash({k: v for k, v in dataset.items() if k != "dataset_sha256"})
    if _sha(dataset["dataset_sha256"], "dataset_sha256") != actual_digest:
        raise ExperimentEvidenceError("EXPERIMENT_DATASET_HASH_MISMATCH")
    return rubric, case_ids


def assess_technique_experiments(*, dataset: dict, observations: list[dict],
                                 allowed_technique_ids: list[str]) -> dict:
    """Assess matched trials and propose technique selection, never auto-promote.

    Observations are numeric-only model data from an already executed, scoped,
    independently reviewed experiment. An observation hash cannot attest its
    source authenticity. All observations must cover the full fixed case set.
    """
    rubric, case_ids = _validate_dataset(dataset)
    if (not isinstance(allowed_technique_ids, list) or
        not 1 <= len(allowed_technique_ids) <= MAX_TECHNIQUES):
        raise ExperimentEvidenceError("EXPERIMENT_ALLOWED_TECHNIQUES_INVALID")
    approved_ids = [_identifier(x, "technique_id") for x in allowed_technique_ids]
    if len(set(approved_ids)) != len(approved_ids):
        raise ExperimentEvidenceError("EXPERIMENT_DUPLICATE_TECHNIQUES")
    if (not isinstance(observations, list) or
        not 1 <= len(observations) <= MAX_CASES * MAX_TECHNIQUES):
        raise ExperimentEvidenceError("EXPERIMENT_OBSERVATIONS_BOUNDS_INVALID")
    groups: dict[str, dict[str, dict]] = {}
    fixed_baselines: dict[str, tuple] = {}
    case_sha_by_id = {row["case_id"]: row["reference_sha256"] for row in dataset["cases"]}
    for row in observations:
        keys = {"technique_id", "case_id", "baseline_metric", "candidate_metric",
                "baseline_artifact_sha256", "candidate_artifact_sha256",
                "baseline_evidence_sha256", "candidate_evidence_sha256",
                "measurement_method", "execution_status", "cost_usd",
                "critical_regression", "observation_sha256"}
        _guard_keys(row, keys, "OBSERVATION")
        technique_id = _identifier(row["technique_id"], "technique_id")
        case_id = _identifier(row["case_id"], "case_id")
        if technique_id not in approved_ids or case_id not in case_ids:
            raise ExperimentEvidenceError("EXPERIMENT_UNAUTHORIZED_TECHNIQUE_OR_CASE")
        if row["measurement_method"] != rubric["measurement_method"]:
            raise ExperimentEvidenceError("EXPERIMENT_MEASUREMENT_METHOD_DRIFT")
        for key in ("baseline_artifact_sha256", "candidate_artifact_sha256",
                    "baseline_evidence_sha256", "candidate_evidence_sha256"):
            _sha(row[key], key)
        if row["execution_status"] not in {"MEASURED", "FAILED", "SKIPPED"}:
            raise ExperimentEvidenceError("EXPERIMENT_EXECUTION_STATUS_INVALID")
        if type(row["critical_regression"]) is not bool:
            raise ExperimentEvidenceError("EXPERIMENT_REGRESSION_FLAG_INVALID")
        if not 0 <= _real(row["cost_usd"], "cost_usd") <= 1000:
            raise ExperimentEvidenceError("EXPERIMENT_COST_INVALID")
        if row["baseline_artifact_sha256"] != case_sha_by_id[case_id]:
            raise ExperimentEvidenceError("EXPERIMENT_BASELINE_REFERENCE_MISMATCH")
        if row["baseline_artifact_sha256"] == row["candidate_artifact_sha256"] and row["baseline_metric"] != row["candidate_metric"]:
            raise ExperimentEvidenceError("EXPERIMENT_ARTIFACT_METRIC_CONTRADICTION")
        if row["baseline_evidence_sha256"] == row["candidate_evidence_sha256"] and row["baseline_metric"] != row["candidate_metric"]:
            raise ExperimentEvidenceError("EXPERIMENT_EVIDENCE_METRIC_CONTRADICTION")
        if row["execution_status"] == "MEASURED":
            _real(row["baseline_metric"], "baseline_metric")
            _real(row["candidate_metric"], "candidate_metric")
        elif row["baseline_metric"] is not None or row["candidate_metric"] is not None:
            raise ExperimentEvidenceError("EXPERIMENT_FAILED_TRIAL_HAS_METRICS")
        if _sha(row["observation_sha256"], "observation_sha256") != _hash(
                {k: v for k, v in row.items() if k != "observation_sha256"}):
            raise ExperimentEvidenceError("EXPERIMENT_OBSERVATION_HASH_MISMATCH")
        baseline = (row["baseline_metric"], row["baseline_artifact_sha256"], row["baseline_evidence_sha256"])
        if case_id in fixed_baselines and fixed_baselines[case_id] != baseline:
            raise ExperimentEvidenceError("EXPERIMENT_INCONSISTENT_BASELINE_ACROSS_TECHNIQUES")
        fixed_baselines[case_id] = baseline
        prior = groups.setdefault(technique_id, {})
        if case_id in prior:
            raise ExperimentEvidenceError("EXPERIMENT_DUPLICATE_TRIAL")
        prior[case_id] = row
    if set(groups) != set(approved_ids):
        raise ExperimentEvidenceError("EXPERIMENT_MISSING_TECHNIQUE")
    comparison = []
    for technique_id in sorted(groups):
        trials = groups[technique_id]
        if set(trials) != set(case_ids):
            raise ExperimentEvidenceError("EXPERIMENT_INCOMPLETE_PAIRED_CASES")
        counts = {"development": Counter(), "holdout": Counter()}
        diagnoses: Counter[str] = Counter()
        for case_id, row in trials.items():
            split = case_ids[case_id]
            # Safety/cost violations override apparent metric gains.
            if row["critical_regression"]:
                counts[split]["blocked"] += 1
                diagnoses["CRITICAL_REGRESSION"] += 1
                continue
            if rubric["zero_cost"] and row["cost_usd"] != 0:
                counts[split]["blocked"] += 1
                diagnoses["PAID_OR_UNKNOWN_COST"] += 1
                continue
            if row["execution_status"] != "MEASURED":
                counts[split]["blocked"] += 1
                diagnoses[f"TRIAL_{row['execution_status']}"] += 1
                continue
            delta = _score(row["candidate_metric"], rubric) - _score(
                row["baseline_metric"], rubric)
            tolerance = rubric["tolerance"]
            label = "win" if delta > tolerance else "loss" if delta < -tolerance else "tie"
            counts[split][label] += 1
            if label == "loss":
                diagnoses["MEASURABLE_QUALITY_REGRESSION"] += 1
        development, held = counts["development"], counts["holdout"]
        data_sufficient = (
            sum(development.values()) >= MIN_DEV and sum(held.values()) >= MIN_HOLDOUT
        )
        p = _p_value(held["win"], held["loss"]) if data_sufficient else None
        safe = not diagnoses["CRITICAL_REGRESSION"] and not diagnoses["PAID_OR_UNKNOWN_COST"] and (
            not diagnoses["TRIAL_FAILED"] and not diagnoses["TRIAL_SKIPPED"])
        # A held-out result is only a recommendation to human reviewers.
        positive = (
            data_sufficient and safe and held["win"] > held["loss"] and
            p is not None and p <= SIGNIFICANCE_ALPHA and
            development["win"] > development["loss"]
        )
        status = ("BLOCKED" if not safe else
                  "INSUFFICIENT_EVIDENCE" if not data_sufficient else
                  "REVIEW_CANDIDATE" if positive else "NO_DEMONSTRATED_IMPROVEMENT")
        comparison.append({
            "technique_id": technique_id, "status": status,
            "development": dict(development), "holdout": dict(held),
            "holdout_one_sided_sign_p": round(p, 8) if p is not None else None,
            "diagnoses": dict(sorted(diagnoses.items())),
            "human_review_required": True,
            "production_authorized": False,
        })
    eligible = sorted(
        (x for x in comparison if x["status"] == "REVIEW_CANDIDATE"),
        key=lambda x: (x["holdout_one_sided_sign_p"], -x["holdout"].get("win", 0),
                       x["technique_id"])
    )
    result = {
        "schema_version": "BRTechniqueExperimentAssessment/v1",
        "dataset_id": dataset["dataset_id"], "dataset_sha256": dataset["dataset_sha256"],
        "domain": dataset["domain"], "task_class": dataset["task_class"],
        "rubric": rubric.copy(), "results": comparison,
        "recommended_for_independent_review": [x["technique_id"] for x in eligible],
        "decision": "PROPOSE_ONLY_NO_AUTOMATIC_ROUTING_OR_LEARNING",
        "confidence": "PAIRED_SELF_REPORTED_HASHES_NOT_INDEPENDENT_ATTESTATION",
        "holdout_policy": "PRE_REGISTERED_DISJOINT_HOLDOUT_SIGN_TEST",
        "memory_write": "NOT_ATTEMPTED",
        "production_promotion": "FORBIDDEN",
        "owner_voice_identity": "BR_OWNER_V1_UNTOUCHED",
        "human_approval_required": True,
    }
    result["assessment_sha256"] = _hash(result)
    return result


def choose_next_benchmark(*, assessment: dict, eligible_technique_ids: list[str]) -> dict:
    """Deterministic exploration proposal. No live capability selection or task execution."""
    ids = sorted({_identifier(x, "technique_id") for x in eligible_technique_ids})
    if not ids or len(ids) > MAX_TECHNIQUES:
        raise ExperimentEvidenceError("EXPERIMENT_ELIGIBLE_TECHNIQUES_INVALID")
    if assessment.get("schema_version") != "BRTechniqueExperimentAssessment/v1":
        raise ExperimentEvidenceError("EXPERIMENT_ASSESSMENT_REQUIRED")
    if assessment.get("assessment_sha256") != _hash(
            {k: v for k, v in assessment.items() if k != "assessment_sha256"}):
        raise ExperimentEvidenceError("EXPERIMENT_ASSESSMENT_HASH_INVALID")
    results = {x["technique_id"]: x for x in assessment["results"]}
    if not set(ids).issubset(results):
        raise ExperimentEvidenceError("EXPERIMENT_UNKNOWN_TECHNIQUE")
    # Investigate blocked results, never bypass a security gate to explore.
    valid = [x for x in ids if results[x]["status"] != "BLOCKED"]
    if not valid:
        return {"status": "BLOCKED", "proposal": None, "routing_changed": False}
    def amount(tid: str) -> int:
        x = results[tid]
        return sum(x[s].get(k, 0) for s in ("development", "holdout")
                   for k in ("win", "tie", "loss"))
    chosen = min(valid, key=lambda tid: (amount(tid), tid))
    return {
        "status": "BENCHMARK_PROPOSED", "proposal": {
            "technique_id": chosen,
            "purpose": "REPEAT_WITH_NEW_PRE_REGISTERED_CASES_AND_HUMAN_REVIEW",
            "not_an_execution_order": True,
        }, "routing_changed": False, "memory_written": False,
    }
