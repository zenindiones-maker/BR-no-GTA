import pytest

from app.database.ideas_repository import insert_idea
from app.database.schema import initialize_schema
from app.services.script_generator_service import generate_and_save_script
from app.services.script_spec_service import generate_script_spec
from app.services.content_item_service import create_content_item
from app.services.production_plan_service import create_production_plan
from app.services.video_service import create_video_spec
from app.services.video_execution_service import create_video_execution_spec
from app.services.render_job_service import create_render_job


def _create_video_execution_spec():
    video = {
        "content_item_id": 1,
        "script_id": 2,
        "idea_id": 3,
        "objective": "Testar a criação de um Render Job.",
        "format": "youtube_short",
        "estimated_duration_seconds": 30.0,
        "scenes": [
            {
                "order": 1,
                "narrative_block": "Introdução",
                "narration": "Introdução do teste.",
                "visual_type": "gameplay",
                "visual_description": "Gameplay de teste.",
                "duration_seconds": 10.0,
                "requirements": ["media_real"],
                "file_path": "/tmp/test-media.mp4",
                "segment_id": 101,
                "content_unit_id": 201,
                "source_start_seconds": 0.0,
                "source_end_seconds": 10.0,
                "role": "primary",
            },
            {
                "order": 2,
                "narrative_block": "Desenvolvimento",
                "narration": "Desenvolvimento do teste.",
                "visual_type": "gameplay",
                "visual_description": "Gameplay complementar de teste.",
                "duration_seconds": 10.0,
                "requirements": ["media_real"],
                "file_path": "/tmp/test-media.mp4",
                "segment_id": 102,
                "content_unit_id": 202,
                "source_start_seconds": 10.0,
                "source_end_seconds": 20.0,
                "role": "secondary",
            },
            {
                "order": 3,
                "narrative_block": "Conclusão",
                "narration": "Conclusão do teste.",
                "visual_type": "title_card",
                "visual_description": "Encerramento de teste.",
                "duration_seconds": 10.0,
                "requirements": ["media_real"],
                "file_path": "/tmp/test-media.mp4",
                "segment_id": 103,
                "content_unit_id": 203,
                "source_start_seconds": 20.0,
                "source_end_seconds": 30.0,
                "role": "secondary",
            },
        ],
        "audio_requirements": ["voiceover"],
        "visual_requirements": ["real_media"],
        "edit_plan": {
            "duration_seconds": 30.0,
            "scenes": [],
            "cuts": [],
        },
    }

    return create_video_execution_spec(video)


def test_create_render_job_from_video_execution_spec():
    execution = _create_video_execution_spec()

    job = create_render_job(execution, video_id=123)

    assert job["content_item_id"] == execution["content_item_id"]
    assert job["script_id"] == execution["script_id"]
    assert job["idea_id"] == execution["idea_id"]
    assert job["objective"] == execution["objective"]
    assert job["format"] == execution["format"]
    assert job["estimated_duration_seconds"] > 0
    assert job["status"] == "queued"


def test_render_job_preserves_authorization_context():
    execution = _create_video_execution_spec()
    execution.update(
        {
            "brain_decision_id": "brain-test-001",
            "execution_id": "execution-test-001",
            "authorized_action": "EXECUTION",
        }
    )

    job = create_render_job(execution, video_id=123)

    assert job["brain_decision_id"] == "brain-test-001"
    assert job["execution_id"] == "execution-test-001"
    assert job["authorized_action"] == "EXECUTION"


def test_render_job_contains_scenes():
    execution = _create_video_execution_spec()

    job = create_render_job(execution, video_id=123)

    assert isinstance(job["scenes"], list)
    assert len(job["scenes"]) >= 3

    for scene in job["scenes"]:
        assert "order" in scene
        assert "narrative_block" in scene
        assert "narration" in scene
        assert "visual_type" in scene
        assert "visual_description" in scene
        assert "duration_seconds" in scene
        assert "execution_requirements" in scene

        assert scene["order"] > 0
        assert scene["narrative_block"]
        assert scene["narration"]
        assert scene["visual_type"]
        assert scene["visual_description"]
        assert scene["duration_seconds"] > 0
        assert isinstance(scene["execution_requirements"], list)


def test_render_job_preserves_audio_requirements():
    execution = _create_video_execution_spec()

    job = create_render_job(execution, video_id=123)

    assert job["audio_requirements"] == execution["audio_requirements"]


def test_render_job_preserves_visual_requirements():
    execution = _create_video_execution_spec()

    job = create_render_job(execution, video_id=123)

    assert job["visual_requirements"] == execution["visual_requirements"]


def test_render_job_contains_render_configuration():
    execution = _create_video_execution_spec()

    job = create_render_job(execution, video_id=123)

    assert job["render"]["resolution"]
    assert job["render"]["fps"] > 0
    assert job["render"]["aspect_ratio"]
    assert job["render"]["container"]
    assert job["render"]["video_codec"]
    assert job["render"]["audio_codec"]


def test_render_job_contains_execution_metadata():
    execution = _create_video_execution_spec()

    job = create_render_job(execution, video_id=123)

    assert job["job_type"] == "video_render"
    assert job["queue"] == "render"
    assert job["attempt"] == 0


def test_render_job_rejects_invalid_video_execution_spec():
    initialize_schema()

    with pytest.raises(ValueError, match="video execution spec"):
        create_render_job({}, video_id=123)


def test_render_job_rejects_missing_scenes():
    execution = _create_video_execution_spec()
    execution["scenes"] = []

    with pytest.raises(ValueError, match="cenas"):
        create_render_job(execution, video_id=123)


def test_render_job_contains_video_id():
    execution = _create_video_execution_spec()

    job = create_render_job(
        execution,
        video_id=123,
    )

    assert job["video_id"] == 123


@pytest.mark.parametrize("invalid_video_id", [0, -1, "123"])
def test_render_job_rejects_invalid_video_id(invalid_video_id):
    execution = _create_video_execution_spec()

    with pytest.raises(
        ValueError,
        match="video_id",
    ):
        create_render_job(
            execution,
            video_id=invalid_video_id,
        )
