import pytest

from app.database.ideas_repository import insert_idea
from app.database.render_queue_repository import (
    enqueue_render_job,
    get_render_job,
)
from app.database.video_repository import (
    insert_video,
    list_videos,
)
from app.services.content_item_service import create_content_item
from app.services.script_generator_service import generate_and_save_script
from app.services.script_spec_service import generate_script_spec
from app.services.render_recovery_service import (
    recover_failed_render_job,
)


GOAL_ID = "goal-recovery-test"


def _create_lineage():
    idea_id = insert_idea(
        title="Render recovery test",
        description="Lineage mínima para testar recovery.",
        status="approved",
        score=9.0,
    )

    script_id = generate_and_save_script(
        idea_id,
    )

    script_spec = generate_script_spec(
        script_id,
    )

    content_item = create_content_item(
        script_spec,
    )

    return {
        "idea_id": idea_id,
        "script_id": script_id,
        "content_item_id": content_item["id"],
    }


def _production_plan(
    *,
    content_item_id,
    script_id,
    idea_id,
):
    return {
        "content_item_id": content_item_id,
        "script_id": script_id,
        "idea_id": idea_id,
        "objective": "Validar recovery de render.",
        "format": "YouTube canary",
        "estimated_duration_seconds": 45.0,
        "status": "ready",
        "scenes": [
            {
                "order": 1,
                "narrative_block": "Introdução",
                "narration": "Cena um.",
                "visual_type": "title_card",
                "visual_description": "Introdução.",
                "duration_seconds": 15.0,
                "requirements": [],
                "segment_id": 1,
                "content_unit_id": 11,
                "asset_ref": "remote://test/media",
                "source_url": "https://example.invalid/video",
                "source_start_seconds": 0.0,
                "source_end_seconds": 15.0,
            },
            {
                "order": 2,
                "narrative_block": "Contexto",
                "narration": "Cena dois.",
                "visual_type": "gameplay",
                "visual_description": "Contexto.",
                "duration_seconds": 15.0,
                "requirements": [],
                "segment_id": 2,
                "content_unit_id": 12,
                "asset_ref": "remote://test/media",
                "source_url": "https://example.invalid/video",
                "source_start_seconds": 15.0,
                "source_end_seconds": 30.0,
            },
            {
                "order": 3,
                "narrative_block": "Conclusão",
                "narration": "Cena três.",
                "visual_type": "summary_graphics",
                "visual_description": "Conclusão.",
                "duration_seconds": 15.0,
                "requirements": [],
                "segment_id": 3,
                "content_unit_id": 13,
                "asset_ref": "remote://test/media",
                "source_url": "https://example.invalid/video",
                "source_start_seconds": 30.0,
                "source_end_seconds": 45.0,
            },
        ],
        "audio_requirements": [],
        "visual_requirements": [],
        "edit_plan": {
            "effects": [
                {
                    "name": "vedit_graphic:title",
                    "params": {
                        "text": "LEGACY",
                    },
                }
            ]
        },
    }


def _failed_render_job(
    *,
    video_id,
    content_item_id,
    script_id,
    idea_id,
    status="failed",
):
    return {
        "content_item_id": content_item_id,
        "script_id": script_id,
        "idea_id": idea_id,
        "objective": "Validar recovery de render.",
        "format": "YouTube canary",
        "estimated_duration_seconds": 45.0,
        "status": status,
        "scenes": [
            {
                "order": 1,
                "narrative_block": "Introdução",
                "narration": "Cena antiga.",
                "visual_type": "title_card",
                "visual_description": "Cena antiga.",
                "duration_seconds": 45.0,
                "execution_requirements": [],
            }
        ],
        "audio_requirements": [],
        "visual_requirements": [],
        "render": {
            "resolution": "1920x1080",
            "fps": 30,
            "aspect_ratio": "16:9",
            "container": "mp4",
            "video_codec": "h264",
            "audio_codec": "aac",
        },
        "job_type": "video_render",
        "queue": "render",
        "attempt": 1,
        "video_id": video_id,
        "brain_decision_id": "old-decision",
        "execution_id": "old-execution",
        "authorized_action": "EXECUTION",
        "edit_plan": {
            "effects": [
                {
                    "name": "vedit_graphic:title",
                    "params": {
                        "text": "LEGACY",
                    },
                }
            ]
        },
    }


def _authorization():
    return {
        "brain_decision_id": "new-decision",
        "execution_id": "new-execution",
        "authorized_action": "EXECUTION",
    }


def _prepare(
    monkeypatch,
    *,
    status="failed",
):
    lineage = _create_lineage()

    content_item_id = lineage["content_item_id"]
    script_id = lineage["script_id"]
    idea_id = lineage["idea_id"]

    video_id = insert_video(
        content_item_id=content_item_id,
        title="Recovery test",
        status="draft",
    )

    old_job_id = enqueue_render_job(
        _failed_render_job(
            video_id=video_id,
            content_item_id=content_item_id,
            script_id=script_id,
            idea_id=idea_id,
            status=status,
        )
    )

    artifacts = {
        "goal_id": GOAL_ID,
        "idea_id": idea_id,
        "script_id": script_id,
        "content_item_id": content_item_id,
        "video_id": video_id,
        "render_job_id": old_job_id,
        "youtube_publication_id": None,
    }

    plan = _production_plan(
        content_item_id=content_item_id,
        script_id=script_id,
        idea_id=idea_id,
    )

    updates = []

    monkeypatch.setattr(
        "app.services.render_recovery_service.get_gta6_goal_artifacts",
        lambda goal_id: (
            dict(artifacts)
            if goal_id == GOAL_ID
            else None
        ),
    )

    monkeypatch.setattr(
        "app.services.render_recovery_service.get_production_plan_by_content_item_id",
        lambda requested_content_item_id: (
            {
                "id": 1,
                "content_item_id": content_item_id,
                "status": "ready",
                "production_plan": plan,
            }
            if requested_content_item_id == content_item_id
            else None
        ),
    )

    def fake_bind_selected_segments(
        production_plan,
        segment_ids,
    ):
        assert segment_ids == [1, 2, 3]
        return dict(production_plan)

    monkeypatch.setattr(
        "app.services.render_recovery_service.bind_selected_segments",
        fake_bind_selected_segments,
    )

    def fake_update_artifacts(**kwargs):
        updates.append(dict(kwargs))
        return {
            **artifacts,
            **kwargs,
        }

    monkeypatch.setattr(
        "app.services.render_recovery_service.update_artifacts",
        fake_update_artifacts,
    )

    return {
        "video_id": video_id,
        "old_job_id": old_job_id,
        "updates": updates,
        "content_item_id": content_item_id,
        "script_id": script_id,
        "idea_id": idea_id,
    }


def test_recover_failed_render_job_creates_new_queued_job_for_same_video(
    monkeypatch,
):
    prepared = _prepare(
        monkeypatch,
    )

    video_id = prepared["video_id"]
    old_job_id = prepared["old_job_id"]

    videos_before = list_videos()

    result = recover_failed_render_job(
        goal_id=GOAL_ID,
        failed_render_job_id=old_job_id,
        execution_context=_authorization(),
    )

    videos_after = list_videos()

    assert len(videos_after) == len(videos_before)

    assert result["authority"] == "deepseek_harness"
    assert result["failed_render_job_id"] == old_job_id
    assert result["new_render_job_id"] != old_job_id
    assert result["video_id"] == video_id
    assert result["status"] == "queued"

    old_job = get_render_job(
        old_job_id,
    )

    new_job = get_render_job(
        result["new_render_job_id"],
    )

    assert old_job is not None
    assert old_job["status"] == "failed"

    assert new_job is not None
    assert new_job["status"] == "queued"
    assert new_job["attempt"] == 0
    assert new_job["video_id"] == video_id

    assert (
        new_job["content_item_id"]
        == prepared["content_item_id"]
    )
    assert (
        new_job["script_id"]
        == prepared["script_id"]
    )
    assert (
        new_job["idea_id"]
        == prepared["idea_id"]
    )

    assert (
        new_job["brain_decision_id"]
        == "new-decision"
    )
    assert (
        new_job["execution_id"]
        == "new-execution"
    )
    assert (
        new_job["authorized_action"]
        == "EXECUTION"
    )

    assert "edit_plan" not in new_job

    assert [
        scene["segment_id"]
        for scene in new_job["scenes"]
    ] == [1, 2, 3]

    assert [
        scene["source_start_seconds"]
        for scene in new_job["scenes"]
    ] == [0.0, 15.0, 30.0]

    assert [
        scene["source_end_seconds"]
        for scene in new_job["scenes"]
    ] == [15.0, 30.0, 45.0]

    updates = prepared["updates"]

    assert len(updates) == 1
    assert updates[0]["goal_id"] == GOAL_ID
    assert updates[0]["video_id"] == video_id
    assert (
        updates[0]["render_job_id"]
        == result["new_render_job_id"]
    )


def test_recovery_rejects_non_failed_render_job(
    monkeypatch,
):
    prepared = _prepare(
        monkeypatch,
        status="queued",
    )

    with pytest.raises(
        ValueError,
        match="estado failed",
    ):
        recover_failed_render_job(
            goal_id=GOAL_ID,
            failed_render_job_id=prepared["old_job_id"],
            execution_context=_authorization(),
        )


def test_recovery_requires_new_execution_identity(
    monkeypatch,
):
    prepared = _prepare(
        monkeypatch,
    )

    with pytest.raises(
        ValueError,
        match="novo execution_id",
    ):
        recover_failed_render_job(
            goal_id=GOAL_ID,
            failed_render_job_id=prepared["old_job_id"],
            execution_context={
                "brain_decision_id": "new-decision",
                "execution_id": "old-execution",
                "authorized_action": "EXECUTION",
            },
        )


def test_recovery_requires_execution_authorization(
    monkeypatch,
):
    prepared = _prepare(
        monkeypatch,
    )

    with pytest.raises(
        ValueError,
        match="authorized_action=EXECUTION",
    ):
        recover_failed_render_job(
            goal_id=GOAL_ID,
            failed_render_job_id=prepared["old_job_id"],
            execution_context={
                "brain_decision_id": "new-decision",
                "execution_id": "new-execution",
                "authorized_action": "RESEARCH",
            },
        )
