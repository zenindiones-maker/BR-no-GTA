from __future__ import annotations

import pytest

from scripts.promote_issue14_render_profile import _observed_bundle, _validate_benchmark


def _benchmark():
    checks = {
        "latency_reduction_ge_20pct": True,
        "ssim_ge_0_98": True,
        "resolution_1920x1080": True,
        "fps_30": True,
        "h264": True,
        "aac": True,
        "duration_expected": True,
        "full_decode": True,
        "qa": True,
        "same_quality_policy": True,
        "timestamp_placement_active": True,
        "compact_text_overlays_active": True,
    }
    return {
        "status": "PASS",
        "observed": True,
        "root_cause": {
            "stage": "ffmpeg_decode_filtergraph_encode_audio_mix",
            "complexity": {
                "video_clip_count": 87,
                "text_clip_count": 63,
            },
        },
        "benchmark": {
            "representative_duration_seconds": 180.0,
            "baseline": {
                "total_seconds": 320.0,
                "software_preset": "slow",
                "qa_status": "PASS",
            },
            "candidate": {
                "total_seconds": 220.0,
                "software_preset": "slow",
                "timeline_placement": "timestamp",
                "compact_text_overlays": True,
                "qa_status": "PASS",
                "full_decode": True,
                "width": 1920,
                "height": 1080,
                "fps": 30.0,
                "video_codec": "h264",
                "audio_codec": "aac",
            },
            "latency_reduction_fraction": 0.3125,
            "latency_reduction_percent": 31.25,
            "ssim": 0.995,
            "promotion_checks": checks,
            "promotion_eligible": True,
        },
    }


def test_issue14_benchmark_adapts_to_observed_learning_evidence():
    validated = _validate_benchmark(_benchmark())
    bundle = _observed_bundle(
        validated=validated,
        benchmark_run_id=123,
        benchmark_artifact_id=456,
    )
    assert bundle["baseline_observation"]["metrics"]["latency_seconds"] == 320.0
    assert bundle["candidate_observation"]["metrics"]["latency_seconds"] == 220.0
    assert bundle["baseline_observation"]["metrics"]["quality"] == 1.0
    assert bundle["candidate_observation"]["metrics"]["quality"] == 1.0
    assert bundle["regression_observation"]["status"] == "PASS"
    assert "87v-63t" in bundle["workload_fingerprint"]


def test_issue14_benchmark_rejects_missing_compact_text_execution():
    payload = _benchmark()
    payload["benchmark"]["candidate"]["compact_text_overlays"] = False
    with pytest.raises(ValueError, match="compact text"):
        _validate_benchmark(payload)


def test_issue14_benchmark_rejects_subthreshold_latency_gain():
    payload = _benchmark()
    payload["benchmark"]["latency_reduction_fraction"] = 0.19
    payload["benchmark"]["latency_reduction_percent"] = 19.0
    with pytest.raises(ValueError, match="below the governed 20%"):
        _validate_benchmark(payload)
