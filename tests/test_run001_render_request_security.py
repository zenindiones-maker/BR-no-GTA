import json

import pytest

from app.services.audiovisual_render_request_service import (
    build_audiovisual_render_request,
)


def _job():
    return {
        "id": 19,
        "render_job_id": 19,
        "video_id": 4,
        "content_item_id": 3,
        "script_id": 7,
        "idea_id": 43,
        "brain_decision_id": "decision-1",
        "execution_id": "execution-1",
        "authorized_action": "EXECUTION",
        "authorization_id": "authorization-record-id",
        "authorization_subject": "action:EXECUTION",
        "issued_by": "deepseek_harness",
        "lineage": {
            "parent_authorization_id": "parent-authorization-record-id",
            "goal_id": "goal-1",
            "zero_cost_operation": True,
        },
        "estimated_duration_seconds": 45.0,
        "status": "running",
        "job_type": "video_render",
        "queue": "render",
        "attempt": 1,
        "scenes": [
            {
                "order": 1,
                "duration_seconds": 45.0,
                "segment_id": 1,
                "content_unit_id": 1,
                "source_start_seconds": 0.0,
                "source_end_seconds": 45.0,
            }
        ],
        "audio_requirements": [{"duration_seconds": 45.0}],
        "visual_requirements": [],
        "render": {
            "resolution": "1920x1080",
            "fps": 30,
            "aspect_ratio": "16:9",
            "container": "mp4",
            "video_codec": "h264",
            "audio_codec": "aac",
        },
    }


def test_dispatch_redacts_governance_authorization_identifiers_but_preserves_execution_envelope():
    request = build_audiovisual_render_request(_job())
    worker_job = json.loads(request["render_job"])

    assert worker_job["render_job_id"] == 19
    assert worker_job["brain_decision_id"] == "decision-1"
    assert worker_job["execution_id"] == "execution-1"
    assert worker_job["authorized_action"] == "EXECUTION"
    assert worker_job["issued_by"] == "deepseek_harness"
    assert worker_job["lineage"]["goal_id"] == "goal-1"
    assert worker_job["lineage"]["zero_cost_operation"] is True

    assert "authorization_id" not in worker_job
    assert "authorization_subject" not in worker_job
    assert "parent_authorization_id" not in worker_job["lineage"]

    assert request["brain_decision_id"] == "decision-1"
    assert request["execution_id"] == "execution-1"
    assert request["authorized_action"] == "EXECUTION"


@pytest.mark.parametrize("field", ["access_token", "password", "client_secret", "api_key", "authorization"])
def test_dispatch_rejects_actual_credential_fields(field):
    job = _job()
    job[field] = "must-not-leave-runtime"

    with pytest.raises(ValueError, match="Credential-bearing fields"):
        build_audiovisual_render_request(job)
