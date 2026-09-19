from __future__ import annotations

from app.workers.audiovisual_worker import (
    RENDER_STALL_WARNING_SECONDS,
    render_progress_metrics,
)


def _state():
    return {
        "last_emit": 0.0,
        "last_media_seconds": 0.0,
        "last_progress_monotonic": None,
        "heartbeat_count": 0,
        "max_stall_seconds": 0.0,
        "last_eta_seconds": None,
    }


def test_render_progress_metrics_provides_eta_and_speed():
    state = _state()
    metrics = render_progress_metrics(
        {"elapsed": 10.0, "seconds": 2.0, "duration": 20.0, "percent": 10.0},
        state,
        now=100.0,
    )
    assert metrics["render_speed_x"] == 0.2
    assert metrics["eta_seconds"] == 90.0
    assert metrics["estimated_total_seconds"] == 100.0
    assert metrics["stall_seconds"] == 0.0
    assert metrics["stalled"] is False
    assert state["last_eta_seconds"] == 90.0


def test_render_progress_metrics_marks_stall_without_hiding_eta():
    state = _state()
    render_progress_metrics(
        {"elapsed": 10.0, "seconds": 2.0, "duration": 20.0, "percent": 10.0},
        state,
        now=100.0,
    )
    metrics = render_progress_metrics(
        {"elapsed": 160.0, "seconds": 2.0, "duration": 20.0, "percent": 10.0},
        state,
        now=100.0 + RENDER_STALL_WARNING_SECONDS + 1.0,
    )
    assert metrics["stalled"] is True
    assert metrics["stall_seconds"] == RENDER_STALL_WARNING_SECONDS + 1.0
    assert metrics["eta_seconds"] is not None
    assert state["max_stall_seconds"] == RENDER_STALL_WARNING_SECONDS + 1.0


def test_render_progress_resets_stall_when_media_time_advances():
    state = _state()
    render_progress_metrics(
        {"elapsed": 10.0, "seconds": 2.0, "duration": 20.0, "percent": 10.0},
        state,
        now=100.0,
    )
    render_progress_metrics(
        {"elapsed": 140.0, "seconds": 2.0, "duration": 20.0, "percent": 10.0},
        state,
        now=230.0,
    )
    metrics = render_progress_metrics(
        {"elapsed": 150.0, "seconds": 3.0, "duration": 20.0, "percent": 15.0},
        state,
        now=240.0,
    )
    assert metrics["stall_seconds"] == 0.0
    assert metrics["stalled"] is False
    assert state["max_stall_seconds"] == 130.0
