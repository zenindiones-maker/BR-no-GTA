"""V22 independent, read-only reconciliation of the frozen V21 shadow run.

Hashes detect local consistency, not authenticity or authorization.
No model invocation, network access, tool authority or production writes.
"""
from __future__ import annotations

from hashlib import sha256
import json
import math
from statistics import median
from typing import Any, Sequence

SCHEMA = "BRShadowSLMDecisionBenchmark/v21"
REPORT_SCHEMA = "BRShadowEvidenceReview/v22"
_ALLOWED = frozenset(("visual", "ledger", "abstain"))


def _digest(obj: Any) -> str:
    return sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


def _fail(reason: str) -> None:
    raise ValueError("V22_" + reason)


def verify_shadow(report: dict[str, Any], *, gold_cases: Sequence[tuple[str, str]],
                  expected_model: str, expected_revision: str,
                  expected_onnx_sha256: str, expected_case_count: int = 20) -> dict[str, Any]:
    """Reconcile each result against out-of-band frozen gold; never trust PASS flags."""
    if not isinstance(report, dict) or report.get("schema_version") != SCHEMA:
        _fail("INPUT_SCHEMA")
    try:
        if len(json.dumps(report, ensure_ascii=False, allow_nan=False)) > 128_000:
            _fail("INPUT_OVERSIZED")
        claimed_hash = report.get("receipt_sha256")
        observed_hash = _digest({k: v for k, v in report.items() if k != "receipt_sha256"})
    except (TypeError, ValueError, OverflowError) as exc:
        _fail("INPUT_UNSERIALIZABLE")
    if claimed_hash != observed_hash:
        _fail("RECEIPT_INCONSISTENT")
    if (report.get("model") != expected_model
        or report.get("revision") != expected_revision
        or report.get("onnx_sha256") != expected_onnx_sha256):
        _fail("MODEL_PROVENANCE_MISMATCH")
    for key, expected in (
        ("actual_onnx_cpu_inference", True), ("published", False),
        ("voice_training_authorized", False), ("ready_to_replace_v19_router", False),
        ("operational_model_professional", False), ("real_tool_use_verified", False),
        ("executable_authority", "NONE_SHADOW_ONLY"), ("paid_calls", 0),
    ):
        if type(report.get(key)) is not type(expected) or report[key] != expected:
            _fail("SECURITY_BOUNDARY_" + key.upper())
    rows = report.get("results")
    if (not isinstance(rows, list) or not isinstance(gold_cases, (list, tuple))
        or len(rows) != expected_case_count or len(gold_cases) != expected_case_count
        or report.get("case_count") != expected_case_count):
        _fail("FROZEN_CASE_COUNT")
    if len({sha256(text.encode()).hexdigest() for _, text in gold_cases}) != len(gold_cases):
        _fail("DUPLICATED_GOLD_CASE")
    domain_total = domain_correct = ood_total = ood_correct = 0
    model_ood = model_ood_correct = policy_ood = 0
    mismatches = []
    latencies = []
    for idx, (row, (gold, text)) in enumerate(zip(rows, gold_cases), start=1):
        if (not isinstance(row, dict) or gold not in _ALLOWED
            or not isinstance(text, str) or not 1 <= len(text) <= 320
            or row.get("label") != gold
            or row.get("text_sha256") != sha256(text.encode()).hexdigest()):
            _fail("FROZEN_CASE_IDENTITY")
        prediction = row.get("predicted")
        if prediction not in _ALLOWED:
            _fail("PREDICTION_ENUM")
        correct = prediction == gold
        if type(row.get("correct")) is not bool or row["correct"] is not correct:
            _fail("ROW_CORRECT_FLAG")
        if (row.get("tool_invoked") is not False or row.get("can_authorize") is not False
            or type(row.get("paid_calls")) is not int or row["paid_calls"] != 0):
            _fail("SECURITY_BOUNDARY_ROW")
        if type(row.get("model_executed")) is not bool:
            _fail("MODEL_EXECUTION_FLAG")
        if row["model_executed"] is False and gold != "abstain":
            _fail("DOMAIN_WITHOUT_MODEL")
        if row["model_executed"] is False and prediction != "abstain":
            _fail("POLICY_PREEMPTION_INCONSISTENT")
        latency = row.get("latency_ms")
        if type(latency) not in (float, int) or not math.isfinite(latency) or latency < 0:
            _fail("LATENCY_INVALID")
        latencies.append(latency)
        if gold == "abstain":
            ood_total += 1
            ood_correct += int(correct)
            if row["model_executed"]:
                model_ood += 1
                model_ood_correct += int(correct)
            else:
                policy_ood += 1
        else:
            domain_total += 1
            domain_correct += int(correct)
        if not correct:
            mismatches.append({"case_index": idx, "case_id_sha256": row["text_sha256"],
                               "expected": gold, "predicted": prediction,
                               "model_executed": row["model_executed"]})
    if (report.get("in_domain_count") != domain_total
        or report.get("out_of_distribution_count") != ood_total
        or domain_total == 0 or ood_total == 0):
        _fail("CLASS_COUNTS")
    acc = round(domain_correct / domain_total, 4)
    abstain = round(ood_correct / ood_total, 4)
    if report.get("in_domain_accuracy") != acc or report.get("ood_abstention_accuracy") != abstain:
        _fail("AGGREGATE_MISMATCH")
    if (report.get("frozen_domain_threshold") != 0.85
        or report.get("frozen_ood_threshold") != 1.0):
        _fail("THRESHOLD_CHANGED")
    expected_status = ("SHADOW_SMALL_MODEL_INITIAL_CHECK_PASS" if acc >= 0.85 and abstain == 1.0
                       else "SHADOW_SMALL_MODEL_QUALITY_NOT_SUFFICIENT")
    if report.get("status") != expected_status:
        _fail("DECLARED_STATUS_MISMATCH")
    if (report.get("p50_latency_ms") != round(median(latencies), 3)
        or report.get("max_latency_ms") != max(latencies)):
        _fail("LATENCY_AGGREGATE_MISMATCH")
    result = {
        "schema_version": REPORT_SCHEMA,
        "integrity": "VERIFIED_STRUCTURAL_CONSISTENCY_NOT_PROVEN_AUTHENTICITY",
        "source_receipt_sha256": report["receipt_sha256"],
        "actual_onnx_executed_as_reported": True,
        "domain_correct": domain_correct, "domain_trials": domain_total,
        "ood_correct": ood_correct, "ood_trials": ood_total,
        "model_only_ood_correct": model_ood_correct,
        "model_only_ood_trials": model_ood,
        "policy_preempted_ood": policy_ood,
        "model_quality": "PASSED_FROZEN_SMALL_SAMPLE" if expected_status.endswith("_PASS") else "REJECTED",
        "mismatches": mismatches,
        "promotion_authorized": False,
        "professional_specialist_verified": False,
        "baseline_comparison": "NOT_COMPARABLE_DIFFERENT_V19_TASK_DISTRIBUTION",
        "heldout_benchmark": "NOT_PERFORMED",
        "authority": "DEEPSEEK_HARNESS_ONLY",
        "remote_model_calls": 0,
        "private_voice_access": False,
        "telegram_send": False,
        "notes": "Source digest is consistency-only. One small sample cannot certify professional performance.",
    }
    result["receipt_sha256"] = _digest(result)
    return result
