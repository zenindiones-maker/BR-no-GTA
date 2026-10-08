"""Long-form scene-coverage planner and receipt-only merger.

No media decoding or autonomous task submission here: the DeepSeek Harness must
authorize and run each bounded window. Signed provenance is a separate gate;
hashes here show consistency, not that a measurement was genuinely executed.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any

from app.services.reverse_engineering_media_service import ObservationError

SCHEMA = "BRLongformShotCoverage/v1"
SHA = re.compile(r"^[0-9a-f]{64}$")


def _finite_number(value: Any) -> bool:
    return type(value) in (float, int) and math.isfinite(value)


def plan_shot_windows(
    duration_seconds: float, *, window_seconds: float = 60.0, overlap_seconds: float = 1.0
) -> dict[str, Any]:
    if not all(_finite_number(x) for x in (duration_seconds, window_seconds, overlap_seconds)):
        raise ObservationError("SHOT_PLAN_NONFINITE")
    if not (0 < duration_seconds <= 3600 and 1 <= window_seconds <= 90):
        raise ObservationError("SHOT_PLAN_TIME_BOUNDS")
    if not 0 <= overlap_seconds < window_seconds / 2:
        raise ObservationError("SHOT_PLAN_INVALID_OVERLAP")
    windows: list[dict[str, float | int]] = []
    cursor = 0.0
    while cursor < duration_seconds - 0.0005:
        stop = min(float(duration_seconds), cursor + float(window_seconds))
        windows.append({
            "ordinal": len(windows) + 1,
            "start_seconds": round(cursor, 3),
            "window_seconds": round(stop - cursor, 3),
        })
        if len(windows) > 100:
            raise ObservationError("SHOT_PLAN_TOO_MANY_WINDOWS")
        if stop >= duration_seconds:
            break
        cursor = stop - overlap_seconds
    return {
        "schema_version": "BRLongformShotWindowPlan/v1",
        "duration_seconds": round(duration_seconds, 3),
        "window_count": len(windows),
        "windows": windows,
        "status": "PLAN_ONLY_NO_MEDIA_DECODED",
        "requires_harness_authorization_per_window": True,
        "estimated_compute_cost": "UNKNOWN_MEASURE_ON_TARGET_WORKSTATION",
        "overlap_seconds": round(overlap_seconds, 3),
        "quality_approved": False,
    }


def merge_shot_receipts(receipts: list[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(receipts, list) or not 1 <= len(receipts) <= 100:
        raise ObservationError("SHOT_RECEIPTS_COUNT_INVALID")
    expected_source: str | None = None
    expected_algorithm: str | None = None
    expected_duration: float | None = None
    verified: list[dict[str, Any]] = []
    for item in receipts:
        if not isinstance(item, dict) or item.get("schema_version") != "BRAdaptiveShotObservation/v1":
            raise ObservationError("SHOT_RECEIPT_SCHEMA_INVALID")
        digest = item.get("evidence_sha256")
        without_digest = {k: v for k, v in item.items() if k != "evidence_sha256"}
        actual = hashlib.sha256(
            json.dumps(without_digest, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
        ).hexdigest()
        if not isinstance(digest, str) or not SHA.fullmatch(digest) or digest != actual:
            raise ObservationError("SHOT_RECEIPT_HASH_INVALID")
        source = item.get("source_sha256")
        algorithm = item.get("algorithm")
        duration = item.get("total_duration_seconds")
        start, stop = item.get("start_seconds"), item.get("stop_seconds")
        cuts = item.get("cut_candidates_seconds")
        if (not isinstance(source, str) or not SHA.fullmatch(source)
            or algorithm not in ("PySceneDetect_0.7.1_adaptive", "PySceneDetect_0.7.1_content")
            or not all(_finite_number(x) for x in (start, stop, duration))
            or not 0 <= start < stop <= duration + 0.005
            or stop - start > 90.005
            or item.get("status") != "MEASURED"
            or not isinstance(cuts, list) or len(cuts) > 1000
            or any(not _finite_number(c) or not start < c < stop for c in cuts)
        ):
            raise ObservationError("SHOT_RECEIPT_FIELDS_INVALID")
        if expected_source is not None and source != expected_source:
            raise ObservationError("SHOT_RECEIPT_SOURCE_DRIFT")
        if expected_algorithm is not None and algorithm != expected_algorithm:
            raise ObservationError("SHOT_RECEIPT_ALGORITHM_DRIFT")
        if expected_duration is not None and abs(duration - expected_duration) > 0.005:
            raise ObservationError("SHOT_RECEIPT_DURATION_DRIFT")
        expected_source, expected_algorithm, expected_duration = source, algorithm, duration
        verified.append(item)
    verified.sort(key=lambda x: (x["start_seconds"], x["stop_seconds"]))
    cursor = 0.0
    gaps = []
    for row in verified:
        start = row["start_seconds"]
        if start > cursor + 0.005:
            gaps.append([round(cursor, 3), round(start, 3)])
        cursor = max(cursor, row["stop_seconds"])
    if expected_duration is None:
        raise ObservationError("SHOT_RECEIPT_DURATION_MISSING")
    if cursor < expected_duration - 0.005:
        gaps.append([round(cursor, 3), round(expected_duration, 3)])
    uncovered = sum(end - start for start, end in gaps)
    cuts = sorted(set(round(t, 3) for item in verified for t in item["cut_candidates_seconds"]))
    full = not gaps and verified[0]["start_seconds"] <= 0.005
    result = {
        "schema_version": SCHEMA,
        "source_sha256": expected_source,
        "algorithm": expected_algorithm,
        "duration_seconds": round(expected_duration, 3),
        "coverage_seconds": round(max(0.0, expected_duration - uncovered), 3),
        "coverage_percent": round(100 * max(0.0, 1 - uncovered / expected_duration), 3),
        "window_count": len(verified),
        "full_duration_covered_by_receipts": full,
        "uncovered_windows_seconds": gaps,
        "merged_candidate_cuts_seconds": cuts,
        "quality_approved": False,
        "confidence": "CONSISTENT_RECEIPT_HASHES_NOT_INDEPENDENT_ATTESTATION",
        "boundary_warning": "Cuts exactly at window edges may be missed; overlap and hand-labelled QA remain necessary",
    }
    serialized = json.dumps(result, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    result["aggregate_sha256"] = hashlib.sha256(serialized.encode()).hexdigest()
    return result
