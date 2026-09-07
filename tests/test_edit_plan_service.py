from __future__ import annotations

import pytest

from app.services.edit_plan_service import (
    EditAudio,
    EditClip,
    EditEffect,
    EditPlan,
    EditPlanError,
    EditQA,
    EditText,
    EditTrack,
    EditTransition,
)


def make_plan() -> EditPlan:
    clip = EditClip(
        segment_id=10,
        media_path="/workspace/input/gta6.mp4",
        track="V1",
        start_seconds=0.0,
        source_start_seconds=12.5,
        duration_seconds=5.0,
    )

    return EditPlan(
        version="1",
        content_item_id=100,
        script_id=200,
        title="GTA 6 novidade",
        objective="Informar a novidade",
        format="youtube_short",
        duration_seconds=5.0,
        tracks=(
            EditTrack(
                name="V1",
                kind="video",
                clips=(clip,),
            ),
        ),
    )


def test_edit_plan_accepts_valid_plan() -> None:
    plan = make_plan()

    assert plan.version == "1"
    assert plan.content_item_id == 100
    assert plan.script_id == 200
    assert len(plan.tracks) == 1
    assert len(plan.tracks[0].clips) == 1


def test_edit_plan_round_trip_dict() -> None:
    plan = make_plan()

    restored = EditPlan.from_dict(plan.to_dict())

    assert restored == plan


def test_clip_rejects_negative_source_start() -> None:
    with pytest.raises(EditPlanError):
        EditClip(
            segment_id=1,
            media_path="/tmp/video.mp4",
            track="V1",
            start_seconds=0.0,
            source_start_seconds=-1.0,
            duration_seconds=2.0,
        )


def test_clip_rejects_empty_media_path() -> None:
    with pytest.raises(EditPlanError):
        EditClip(
            segment_id=1,
            media_path="",
            track="V1",
            start_seconds=0.0,
            source_start_seconds=0.0,
            duration_seconds=2.0,
        )


def test_plan_rejects_clip_outside_duration() -> None:
    clip = EditClip(
        segment_id=1,
        media_path="/tmp/video.mp4",
        track="V1",
        start_seconds=4.0,
        source_start_seconds=0.0,
        duration_seconds=3.0,
    )

    with pytest.raises(EditPlanError):
        EditPlan(
            version="1",
            content_item_id=1,
            script_id=1,
            title="Teste",
            objective="Teste",
            format="youtube",
            duration_seconds=5.0,
            tracks=(
                EditTrack(
                    name="V1",
                    kind="video",
                    clips=(clip,),
                ),
            ),
        )


def test_text_accepts_valid_configuration() -> None:
    text = EditText(
        text="GTA 6",
        start_seconds=1.0,
        duration_seconds=2.0,
    )

    assert text.text == "GTA 6"
    assert text.track == "T1"


def test_audio_accepts_valid_configuration() -> None:
    audio = EditAudio(
        media_path="/tmp/music.mp3",
        track="A1",
        duration_seconds=10.0,
        volume=0.8,
        fade_in_seconds=1.0,
        fade_out_seconds=1.0,
    )

    assert audio.volume == 0.8
    assert audio.fade_in_seconds == 1.0


def test_transition_accepts_valid_configuration() -> None:
    transition = EditTransition(
        from_segment_id=10,
        to_segment_id=20,
        type="dissolve",
        duration_seconds=0.25,
    )

    assert transition.type == "dissolve"


def test_effect_accepts_parameters() -> None:
    effect = EditEffect(
        segment_id=10,
        name="zoom",
        params={"amount": 1.15},
    )

    assert effect.name == "zoom"
    assert effect.params["amount"] == 1.15


def test_qa_rejects_invalid_duration_range() -> None:
    with pytest.raises(EditPlanError):
        EditQA(
            min_duration_seconds=30.0,
            max_duration_seconds=10.0,
        )


def test_plan_requires_clip() -> None:
    with pytest.raises(EditPlanError):
        EditPlan(
            version="1",
            content_item_id=1,
            script_id=1,
            title="Teste",
            objective="Teste",
            format="youtube",
            duration_seconds=5.0,
            tracks=(
                EditTrack(
                    name="V1",
                    kind="video",
                    clips=(),
                ),
            ),
        )
