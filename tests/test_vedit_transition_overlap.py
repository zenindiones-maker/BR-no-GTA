from __future__ import annotations

import pytest

import app.services.vedit_service as vedit_service
from app.services.edit_plan_service import EditClip
from app.services.vedit_service import (
    VEditPolicy,
    _resolve_transition_timing,
    create_edit_plan,
)


def _clip(
    *,
    segment_id: int,
    start_seconds: float,
    source_start_seconds: float,
    duration_seconds: float,
) -> EditClip:
    return EditClip(
        segment_id=segment_id,
        media_path=f"/tmp/segment-{segment_id}.mp4",
        track="V1",
        start_seconds=start_seconds,
        source_start_seconds=source_start_seconds,
        duration_seconds=duration_seconds,
        role="content",
        fit="cover",
    )


def test_transition_without_overlap_becomes_hard_cut() -> None:
    previous_clip = _clip(
        segment_id=1,
        start_seconds=0.0,
        source_start_seconds=0.0,
        duration_seconds=15.0,
    )
    current_clip = _clip(
        segment_id=2,
        start_seconds=15.0,
        source_start_seconds=15.0,
        duration_seconds=15.0,
    )

    transition_type, duration = _resolve_transition_timing(
        transition_type="dissolve",
        requested_duration_seconds=0.5,
        previous_clip=previous_clip,
        current_clip=current_clip,
    )

    assert transition_type == "cut"
    assert duration == 0.0


def test_transition_duration_is_capped_by_real_overlap() -> None:
    previous_clip = _clip(
        segment_id=1,
        start_seconds=0.0,
        source_start_seconds=0.0,
        duration_seconds=15.0,
    )
    current_clip = _clip(
        segment_id=2,
        start_seconds=14.8,
        source_start_seconds=15.0,
        duration_seconds=15.0,
    )

    transition_type, duration = _resolve_transition_timing(
        transition_type="dissolve",
        requested_duration_seconds=0.5,
        previous_clip=previous_clip,
        current_clip=current_clip,
    )

    assert transition_type == "dissolve"
    assert duration == pytest.approx(0.2)


def test_explicit_cut_remains_zero_duration_even_with_overlap() -> None:
    previous_clip = _clip(
        segment_id=1,
        start_seconds=0.0,
        source_start_seconds=0.0,
        duration_seconds=15.0,
    )
    current_clip = _clip(
        segment_id=2,
        start_seconds=14.8,
        source_start_seconds=15.0,
        duration_seconds=15.0,
    )

    transition_type, duration = _resolve_transition_timing(
        transition_type="cut",
        requested_duration_seconds=0.5,
        previous_clip=previous_clip,
        current_clip=current_clip,
    )

    assert transition_type == "cut"
    assert duration == 0.0


def test_create_edit_plan_preserves_contiguous_canary_timeline(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    media_path = tmp_path / "trailer.mp4"
    media_path.write_bytes(b"run-001-real-file-boundary")

    monkeypatch.setattr(
        vedit_service,
        "score_candidate",
        lambda **kwargs: {
            "total": 1.0,
            "score": 1.0,
        },
    )
    monkeypatch.setattr(
        vedit_service,
        "match_candidate",
        lambda **kwargs: {
            "score": 1.0,
        },
    )
    monkeypatch.setattr(
        vedit_service,
        "build_rhythm",
        lambda **kwargs: {
            "duration_seconds": kwargs[
                "requested_duration_seconds"
            ],
            "reason": "test-rhythm",
        },
    )
    monkeypatch.setattr(
        vedit_service,
        "build_cut",
        lambda **kwargs: {
            "source_start_seconds": kwargs[
                "candidate"
            ]["start_seconds"],
            "duration_seconds": kwargs[
                "target_duration_seconds"
            ],
        },
    )
    monkeypatch.setattr(
        vedit_service,
        "build_graphics_plan",
        lambda **kwargs: [],
    )
    monkeypatch.setattr(
        vedit_service,
        "choose_transition",
        lambda **kwargs: {
            "type": "dissolve",
            "duration_seconds": 0.5,
        },
    )
    monkeypatch.setattr(
        vedit_service,
        "build_timeline",
        lambda **kwargs: {},
    )
    monkeypatch.setattr(
        vedit_service,
        "build_audio_plan",
        lambda **kwargs: {},
    )
    monkeypatch.setattr(
        vedit_service,
        "run_qa",
        lambda **kwargs: {
            "ready_for_render": True,
            "issues": [],
        },
    )

    production_plan = {
        "content_item_id": 3,
        "script_id": 7,
        "idea_id": 43,
        "title": "RUN-001 CANARY — GTA6 Trailer 1",
        "objective": "Validate governed real-media canary.",
        "format": "youtube",
        "estimated_duration_seconds": 45.0,
        "scenes": [
            {
                "order": 1,
                "segment_id": 1,
                "role": "hook",
                "narrative_block": "hook",
                "narration": "",
                "visual_type": "gameplay",
                "visual_description": "Trailer scene 1",
                "duration_seconds": 15.0,
                "file_path": str(media_path),
                "source_start_seconds": 0.0,
                "source_end_seconds": 15.0,
            },
            {
                "order": 2,
                "segment_id": 2,
                "role": "development",
                "narrative_block": "development",
                "narration": "",
                "visual_type": "gameplay",
                "visual_description": "Trailer scene 2",
                "duration_seconds": 15.0,
                "file_path": str(media_path),
                "source_start_seconds": 15.0,
                "source_end_seconds": 30.0,
            },
            {
                "order": 3,
                "segment_id": 3,
                "role": "conclusion",
                "narrative_block": "conclusion",
                "narration": "",
                "visual_type": "gameplay",
                "visual_description": "Trailer scene 3",
                "duration_seconds": 15.0,
                "file_path": str(media_path),
                "source_start_seconds": 30.0,
                "source_end_seconds": 45.0,
            },
        ],
    }

    plan = create_edit_plan(
        production_plan=production_plan,
        brain_decision={
            "action": "EXECUTION",
            "reason": "RUN-001 regression",
            "priority": "HIGH",
            "confidence": 1.0,
        },
        policy=VEditPolicy(
            enable_transitions=True,
            enable_captions=False,
            enable_title_card=False,
            require_real_media=True,
        ),
    )

    clips = plan.tracks[0].clips

    assert len(clips) == 3
    assert plan.duration_seconds == 45.0

    assert [
        clip.start_seconds
        for clip in clips
    ] == [
        0.0,
        15.0,
        30.0,
    ]

    assert [
        clip.source_start_seconds
        for clip in clips
    ] == [
        0.0,
        15.0,
        30.0,
    ]

    assert [
        clip.duration_seconds
        for clip in clips
    ] == [
        15.0,
        15.0,
        15.0,
    ]

    assert [
        (
            transition.type,
            transition.duration_seconds,
        )
        for transition in plan.transitions
    ] == [
        ("cut", 0.0),
        ("cut", 0.0),
    ]
