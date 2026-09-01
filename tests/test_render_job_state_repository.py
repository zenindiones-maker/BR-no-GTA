import pytest

from app.database.schema import initialize_schema
from app.database.render_queue_repository import (
    claim_next_render_job,
    claim_render_job,
    enqueue_render_job,
    get_render_job,
    transition_render_job,
)


def _create_render_job():
    return {
        "content_item_id": 1,
        "script_id": 2,
        "idea_id": 3,
        "objective": "Gerar vídeo editorial",
        "format": "short",
        "estimated_duration_seconds": 60,
        "status": "queued",
        "scenes": [
            {
                "order": 1,
                "narrative_block": "Abertura",
                "narration": "Texto inicial",
                "visual_type": "b-roll",
                "visual_description": "Cena de abertura",
                "duration_seconds": 10,
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
        "attempt": 0,
    }


def _enqueue_job():
    initialize_schema()
    return enqueue_render_job(_create_render_job())


def test_queued_to_running_is_valid():
    job_id = _enqueue_job()

    job = transition_render_job(
        job_id,
        "running",
    )

    assert job["status"] == "running"
    assert job["attempt"] == 1


def test_running_to_completed_requires_output_path():
    job_id = _enqueue_job()

    transition_render_job(job_id, "running")

    with pytest.raises(ValueError, match="output_path"):
        transition_render_job(job_id, "completed")


def test_running_to_completed_records_output_path():
    job_id = _enqueue_job()

    transition_render_job(job_id, "running")

    job = transition_render_job(
        job_id,
        "completed",
        output_path="/renders/video.mp4",
    )

    assert job["status"] == "completed"
    assert job["output_path"] == "/renders/video.mp4"
    assert job["error"] is None
    assert job["attempt"] == 1


def test_running_to_failed_requires_error():
    job_id = _enqueue_job()

    transition_render_job(job_id, "running")

    with pytest.raises(ValueError, match="error"):
        transition_render_job(job_id, "failed")


def test_running_to_failed_records_error():
    job_id = _enqueue_job()

    transition_render_job(job_id, "running")

    job = transition_render_job(
        job_id,
        "failed",
        error="Falha de renderização.",
    )

    assert job["status"] == "failed"
    assert job["error"] == "Falha de renderização."
    assert job["output_path"] is None
    assert job["attempt"] == 1


@pytest.mark.parametrize(
    "target_status",
    [
        "completed",
        "failed",
    ],
)
def test_queued_cannot_finish_directly(target_status):
    job_id = _enqueue_job()

    kwargs = {}

    if target_status == "completed":
        kwargs["output_path"] = "/renders/video.mp4"
    else:
        kwargs["error"] = "Falha simulada."

    with pytest.raises(ValueError, match="Transição inválida"):
        transition_render_job(
            job_id,
            target_status,
            **kwargs,
        )


@pytest.mark.parametrize(
    "target_status",
    [
        "running",
        "queued",
    ],
)
def test_completed_cannot_transition(target_status):
    job_id = _enqueue_job()

    transition_render_job(
        job_id,
        "running",
    )

    transition_render_job(
        job_id,
        "completed",
        output_path="/renders/video.mp4",
    )

    with pytest.raises(ValueError, match="Transição inválida"):
        transition_render_job(
            job_id,
            target_status,
        )


@pytest.mark.parametrize(
    "target_status",
    [
        "running",
        "queued",
    ],
)
def test_failed_cannot_transition(target_status):
    job_id = _enqueue_job()

    transition_render_job(
        job_id,
        "running",
    )

    transition_render_job(
        job_id,
        "failed",
        error="Falha simulada.",
    )

    with pytest.raises(ValueError, match="Transição inválida"):
        transition_render_job(
            job_id,
            target_status,
        )


def test_attempt_increments_only_when_execution_starts():
    job_id = _enqueue_job()

    job = get_render_job(job_id)

    assert job["attempt"] == 0

    transition_render_job(
        job_id,
        "running",
    )

    job = get_render_job(job_id)

    assert job["attempt"] == 1

    transition_render_job(
        job_id,
        "completed",
        output_path="/renders/video.mp4",
    )

    job = get_render_job(job_id)

    assert job["attempt"] == 1



def test_claim_render_job_moves_specific_job_to_running():
    job_id = _enqueue_job()
    other_job_id = _enqueue_job()

    claimed = claim_render_job(job_id)

    assert claimed["id"] == job_id
    assert claimed["status"] == "running"
    assert claimed["attempt"] == 1

    job = get_render_job(job_id)
    other_job = get_render_job(other_job_id)

    assert job["status"] == "running"
    assert job["attempt"] == 1
    assert other_job["status"] == "queued"
    assert other_job["attempt"] == 0


def test_claim_render_job_rejects_non_queued_job():
    job_id = _enqueue_job()

    transition_render_job(job_id, "running")

    with pytest.raises(
        ValueError,
        match="não está em estado queued",
    ):
        claim_render_job(job_id)


def test_claim_render_job_rejects_unknown_job():
    initialize_schema()

    with pytest.raises(
        ValueError,
        match="não encontrado",
    ):
        claim_render_job(999999)


def test_claim_render_job_increments_attempt_exactly_once():
    job_id = _enqueue_job()

    claimed = claim_render_job(job_id)

    assert claimed["attempt"] == 1

    job = get_render_job(job_id)

    assert job["status"] == "running"
    assert job["attempt"] == 1

def test_claim_next_render_job_moves_oldest_queued_job_to_running():
    first_id = _enqueue_job()
    second_id = _enqueue_job()

    claimed = claim_next_render_job()

    assert claimed is not None
    assert claimed["id"] == first_id
    assert claimed["status"] == "running"
    assert claimed["attempt"] == 1

    first = get_render_job(first_id)
    second = get_render_job(second_id)

    assert first["status"] == "running"
    assert first["attempt"] == 1

    assert second["status"] == "queued"
    assert second["attempt"] == 0


def test_claim_next_render_job_returns_none_when_queue_is_empty():
    initialize_schema()

    assert claim_next_render_job() is None


def test_claim_next_render_job_increments_attempt_exactly_once():
    job_id = _enqueue_job()

    first_claim = claim_next_render_job()

    assert first_claim is not None
    assert first_claim["id"] == job_id
    assert first_claim["attempt"] == 1

    second_claim = claim_next_render_job()

    assert second_claim is None

    job = get_render_job(job_id)

    assert job["status"] == "running"
    assert job["attempt"] == 1
