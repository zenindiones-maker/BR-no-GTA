import pytest

from app.services.media_artifact_locator_service import (
    build_github_media_artifact_locator,
    validate_media_artifact_locator,
)


def _job(**changes):
    value = {
        "id": 21,
        "render_job_id": 21,
        "video_id": 31,
        "execution_id": "run-001-video-a-render-21",
    }
    value.update(changes)
    return value


def _execution(**changes):
    value = {
        "run_id": 35050000001,
        "repository": "zenindiones-maker/BR-no-GTA",
        "workflow": "render-worker.yml",
        "artifact_name": "render-output",
        "artifact_id": 4401,
        "artifact_size_in_bytes": 987654321,
        "artifact_remote_uri": "github-actions://zenindiones-maker/BR-no-GTA/runs/35050000001/artifacts/4401/render-output",
        "artifact_expired": False,
    }
    value.update(changes)
    return value


def test_builds_exact_media_and_evidence_paths_inside_existing_artifact():
    locator = build_github_media_artifact_locator(_job(), _execution())

    assert locator["provider"] == "github-actions"
    assert locator["workflow_run_id"] == 35050000001
    assert locator["artifact_id"] == 4401
    assert locator["render_job_id"] == 21
    assert locator["video_id"] == 31
    assert locator["execution_id"] == "run-001-video-a-render-21"
    assert locator["media_relative_path"] == "run-001-video-a-render-21/21/31.mp4"
    assert locator["manifest_relative_path"] == "run-001-video-a-render-21/21/render-manifest.json"
    assert locator["probe_relative_path"] == "run-001-video-a-render-21/21/video-probe.json"
    assert locator["qa_relative_path"] == "run-001-video-a-render-21/21/render-qa.json"
    assert locator["render_job_relative_path"] == "run-001-video-a-render-21/21/render-job.json"
    assert locator["media_uri"].endswith("/run-001-video-a-render-21/21/31.mp4")

    assert validate_media_artifact_locator(
        locator,
        expected_render_job_id=21,
        expected_video_id=31,
        expected_execution_id="run-001-video-a-render-21",
    ) == locator


@pytest.mark.parametrize(
    "field,value",
    [
        ("artifact_id", 0),
        ("artifact_size_in_bytes", 0),
        ("artifact_expired", True),
        ("repository", "wrong-shape"),
        ("artifact_remote_uri", "https://example.invalid/render.zip"),
    ],
)
def test_build_fails_closed_on_unrecoverable_artifact_identity(field, value):
    execution = _execution(**{field: value})
    with pytest.raises(ValueError):
        build_github_media_artifact_locator(_job(), execution)


def test_validation_rejects_cross_video_or_cross_render_rebinding():
    locator = build_github_media_artifact_locator(_job(), _execution())

    with pytest.raises(ValueError, match="render_job_id mismatch"):
        validate_media_artifact_locator(locator, expected_render_job_id=22)
    with pytest.raises(ValueError, match="video_id mismatch"):
        validate_media_artifact_locator(locator, expected_video_id=32)
    with pytest.raises(ValueError, match="execution_id mismatch"):
        validate_media_artifact_locator(locator, expected_execution_id="other")


def test_validation_rejects_media_uri_or_relative_path_escape():
    locator = build_github_media_artifact_locator(_job(), _execution())
    tampered = dict(locator)
    tampered["media_relative_path"] = "other/21/31.mp4"
    with pytest.raises(ValueError, match="relative path lineage mismatch"):
        validate_media_artifact_locator(tampered)

    tampered = dict(locator)
    tampered["media_uri"] = "github-actions://other/repo/31.mp4"
    with pytest.raises(ValueError, match="escapes artifact"):
        validate_media_artifact_locator(tampered)
