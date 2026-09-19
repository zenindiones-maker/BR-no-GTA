import pytest

from app.services.media_selection_service import MediaSelectionError
from app.services.production_media_selection_service import (
    _preflight_continuous_source,
    preflight_production_segment_plan,
)


def test_preflight_accepts_full_continuous_coverage():
    _preflight_continuous_source(
        knowledge={
            "scenes": [
                {"start_seconds": 0.0, "end_seconds": 600.0},
                {"start_seconds": 600.0, "end_seconds": 1500.0},
            ]
        },
        required_duration_seconds=1500.0,
    )


def test_preflight_rejects_short_source_before_persistence():
    with pytest.raises(MediaSelectionError, match="nenhum ContentSegment foi criado"):
        _preflight_continuous_source(
            knowledge={"scenes": [{"start_seconds": 0.0, "end_seconds": 1499.0}]},
            required_duration_seconds=1500.0,
        )


def test_preflight_rejects_gap_in_source_coverage():
    with pytest.raises(MediaSelectionError, match="nenhum ContentSegment foi criado"):
        _preflight_continuous_source(
            knowledge={
                "scenes": [
                    {"start_seconds": 0.0, "end_seconds": 700.0},
                    {"start_seconds": 701.0, "end_seconds": 1600.0},
                ]
            },
            required_duration_seconds=1500.0,
        )


def test_segment_preflight_accepts_observed_floating_point_roundoff():
    start = 140.10876954452755
    requested = 26.614547926580556
    end = start + requested
    assert requested > end - start

    result = preflight_production_segment_plan(
        scene_durations=[requested],
        assignments=[
            {
                "scene_order": 1,
                "source_start_seconds": start,
                "source_end_seconds": end,
                "duration_seconds": end - start,
            }
        ],
    )

    assert result["status"] == "PASS"
    assert result["scene_count"] == 1
    assert result["DETERMINISTIC_FAILURE_DETECTION_MS"] >= 0
    assert abs(
        result["checks"][0]["timeline_duration_seconds"]
        - result["checks"][0]["source_duration_seconds"]
    ) < 0.001


def test_segment_preflight_rejects_real_source_overrun_before_persistence():
    with pytest.raises(MediaSelectionError, match="exceeds available source duration"):
        preflight_production_segment_plan(
            scene_durations=[30.0],
            assignments=[
                {
                    "scene_order": 1,
                    "source_start_seconds": 10.0,
                    "source_end_seconds": 39.5,
                    "duration_seconds": 30.0,
                }
            ],
        )
