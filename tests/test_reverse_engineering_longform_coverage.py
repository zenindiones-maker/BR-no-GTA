from __future__ import annotations

import hashlib
import json

import pytest

from app.services.reverse_engineering_longform_coverage_service import (
    merge_shot_receipts, plan_shot_windows,
)
from app.services.reverse_engineering_media_service import ObservationError


def _receipt(start, stop, cuts, *, sha="a"*64, duration=12):
    data = {
        "schema_version": "BRAdaptiveShotObservation/v1",
        "status": "MEASURED",
        "source_sha256": sha,
        "algorithm": "PySceneDetect_0.7.1_adaptive",
        "total_duration_seconds": duration,
        "start_seconds": start,
        "stop_seconds": stop,
        "cut_candidates_seconds": cuts,
    }
    canonical = json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    data["evidence_sha256"] = hashlib.sha256(canonical.encode()).hexdigest()
    return data


def test_professional_25_minute_window_plan_is_complete_without_automatic_execution():
    plan = plan_shot_windows(1500, window_seconds=60, overlap_seconds=1)
    assert plan["duration_seconds"] == 1500
    assert 25 < plan["window_count"] <= 30
    assert plan["windows"][0]["start_seconds"] == 0
    last = plan["windows"][-1]
    assert abs(last["start_seconds"] + last["window_seconds"] - 1500) < 0.001
    assert all(0 < w["window_seconds"] <= 90 for w in plan["windows"])
    assert plan["status"] == "PLAN_ONLY_NO_MEDIA_DECODED"
    assert plan["requires_harness_authorization_per_window"] is True
    assert plan["quality_approved"] is False


def test_window_plan_rejects_bad_duration_and_overlap():
    for params in (
        {"duration_seconds": 0}, {"duration_seconds": 3601},
        {"duration_seconds": 100, "window_seconds": 91},
        {"duration_seconds": 100, "window_seconds": 5, "overlap_seconds": 3},
        {"duration_seconds": float("nan")},
    ):
        with pytest.raises(ObservationError):
            plan_shot_windows(**params)


def test_shot_receipt_merging_requires_provenance_and_covers_full_duration():
    result = merge_shot_receipts([
        _receipt(5, 12, [8.0]),
        _receipt(0, 6, [2.0, 4.0]),
    ])
    assert result["full_duration_covered_by_receipts"] is True
    assert result["coverage_percent"] == 100
    assert result["merged_candidate_cuts_seconds"] == [2.0, 4.0, 8.0]
    assert result["quality_approved"] is False
    assert result["confidence"] == "CONSISTENT_RECEIPT_HASHES_NOT_INDEPENDENT_ATTESTATION"


def test_missing_window_never_approves_longform_coverage():
    result = merge_shot_receipts([
        _receipt(0, 4, [2]),
        _receipt(6, 10, [8]),
    ])
    assert result["full_duration_covered_by_receipts"] is False
    assert result["coverage_percent"] < 100
    assert result["uncovered_windows_seconds"] == [[4, 6], [10, 12]]


def test_tampered_or_different_source_receipt_blocked():
    a = _receipt(0, 6, [2])
    b = _receipt(5, 12, [8])
    altered = dict(a, cut_candidates_seconds=[1])
    with pytest.raises(ObservationError, match="SHOT_RECEIPT_HASH_INVALID"):
        merge_shot_receipts([altered])
    with pytest.raises(ObservationError, match="SHOT_RECEIPT_SOURCE_DRIFT"):
        merge_shot_receipts([a, _receipt(5, 12, [8], sha="b"*64)])
