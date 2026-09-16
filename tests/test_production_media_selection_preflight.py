import pytest

from app.services.media_selection_service import MediaSelectionError
from app.services.production_media_selection_service import _preflight_continuous_source


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
