"""Convert two *real, same-reference* V5 receipts to one V4 paired numeric trial.

This is only an evidence adapter. It never produces an image, clones a voice,
approves rights or quality, modifies agent policy or creates memory entries.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any

from app.services.reverse_engineering_experiment_intelligence_v4 import _hash
from app.services.reverse_engineering_media_service import ObservationError

SHA = re.compile(r"^[0-9a-f]{64}$")
METRICS = {
    "audio_difference_rmse_linear": ("audio", "unadjusted_difference_rmse_linear",
                                    "BR_v5_PCM_RMSE_FFMPEG_16K_MONO_v1"),
    "frame_mean_ssim": ("video", "mean_frame_ssim",
                        "BR_v5_FFMPEG_SSIM_YUV420P_v1"),
}


def _checked(receipt: Any) -> dict[str, Any]:
    if not isinstance(receipt, dict) or receipt.get("schema_version") != "BRReconstructionFidelity/v1":
        raise ObservationError("FIDELITY_BRIDGE_SCHEMA_UNSUPPORTED")
    evidence = receipt.get("evidence_sha256")
    if not isinstance(evidence, str) or not SHA.fullmatch(evidence):
        raise ObservationError("FIDELITY_BRIDGE_EVIDENCE_HASH_INVALID")
    comparison = {k: v for k, v in receipt.items() if k != "evidence_sha256"}
    try:
        actual = hashlib.sha256(json.dumps(
            comparison, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode()).hexdigest()
    except (TypeError, ValueError) as exc:
        raise ObservationError("FIDELITY_BRIDGE_RECEIPT_UNREADABLE") from exc
    if evidence != actual:
        raise ObservationError("FIDELITY_BRIDGE_RECEIPT_TAMPERED")
    if (receipt.get("status") != "TECHNICAL_MEASUREMENT_ONLY" or
        receipt.get("quality_approved") is not False or
        receipt.get("identity_verified") is not False or
        receipt.get("publication_authorized") is not False):
        raise ObservationError("FIDELITY_BRIDGE_UNSAFE_RECEIPT")
    for field in ("source", "candidate"):
        source = receipt.get(field, {})
        if (not isinstance(source, dict) or source.get("rights") not in {"owned", "licensed"}
            or not isinstance(source.get("sha256"), str)
            or not SHA.fullmatch(source["sha256"])):
            raise ObservationError("FIDELITY_BRIDGE_RIGHTS_OR_SHA_INVALID")
    return receipt


def build_paired_fidelity_trial(
    *, baseline_receipt: dict[str, Any],
    candidate_receipt: dict[str, Any],
    technique_id: str, case_id: str, metric: str,
    safety_review_evidence_sha256: str | None,
    declared_cost_usd: float | None,
) -> dict[str, Any]:
    before = _checked(baseline_receipt)
    after = _checked(candidate_receipt)
    if metric not in METRICS:
        raise ObservationError("FIDELITY_BRIDGE_METRIC_UNSUPPORTED")
    domain, key, method = METRICS[metric]
    if (before["source"]["sha256"] != after["source"]["sha256"] or
        before["window_seconds"] != after["window_seconds"]):
        raise ObservationError("FIDELITY_BRIDGE_DIFFERENT_REFERENCE_OR_WINDOW")
    if before["candidate"]["sha256"] == after["candidate"]["sha256"]:
        raise ObservationError("FIDELITY_BRIDGE_SAME_CANDIDATE")
    if not isinstance(technique_id, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,95}", technique_id):
        raise ObservationError("FIDELITY_BRIDGE_TECHNIQUE_INVALID")
    if not isinstance(case_id, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,95}", case_id):
        raise ObservationError("FIDELITY_BRIDGE_CASE_INVALID")
    if not isinstance(safety_review_evidence_sha256, str) or not SHA.fullmatch(safety_review_evidence_sha256):
        raise ObservationError("FIDELITY_BRIDGE_SAFETY_REVIEW_REQUIRED")
    if type(declared_cost_usd) not in (int, float) or not math.isfinite(declared_cost_usd) or declared_cost_usd != 0:
        raise ObservationError("FIDELITY_BRIDGE_ZERO_COST_ATTESTATION_REQUIRED")
    a, b = before.get(domain, {}), after.get(domain, {})
    if (not isinstance(a, dict) or not isinstance(b, dict)
        or a.get("status") != "MEASURED" or b.get("status") != "MEASURED"):
        raise ObservationError("FIDELITY_BRIDGE_STREAM_NOT_MEASURED")
    left, right = a.get(key), b.get(key)
    if type(left) not in (int, float) or type(right) not in (int, float):
        raise ObservationError("FIDELITY_BRIDGE_METRIC_NOT_FINITE")
    if not math.isfinite(left) or not math.isfinite(right):
        raise ObservationError("FIDELITY_BRIDGE_METRIC_NOT_FINITE")
    if metric == "frame_mean_ssim" and not 0 <= left <= 1 or metric == "frame_mean_ssim" and not 0 <= right <= 1:
        raise ObservationError("FIDELITY_BRIDGE_SSIM_BOUNDS")
    # The safety evidence is a declared reviewed external receipt hash, not proof
    # of independent reviewer identity. This must be verified at promotion.
    output = {
        "technique_id": technique_id, "case_id": case_id,
        "baseline_metric": float(left), "candidate_metric": float(right),
        "baseline_artifact_sha256": before["candidate"]["sha256"],
        "candidate_artifact_sha256": after["candidate"]["sha256"],
        "baseline_evidence_sha256": before["evidence_sha256"],
        "candidate_evidence_sha256": after["evidence_sha256"],
        "measurement_method": method,
        "execution_status": "MEASURED",
        "cost_usd": float(declared_cost_usd),
        "critical_regression": False,
    }
    output["observation_sha256"] = _hash(output)
    return output
