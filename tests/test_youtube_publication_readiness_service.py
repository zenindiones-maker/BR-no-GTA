import json

from app.database.connection import get_connection
from app.database.youtube_cloud_execution_repository import get_youtube_cloud_execution
from app.database.gta6_goal_repository import (
    create_gta6_goal,
    upsert_gta6_goal_artifacts,
)
from app.database.render_queue_repository import enqueue_render_job
from app.database.video_repository import update_video_file_path
from app.database.youtube_repository import (
    get_youtube_publication,
    insert_youtube_publication,
)
from app.services.media_artifact_locator_service import build_github_media_artifact_locator
from app.services.youtube_publication_readiness_service import build_youtube_publication_preview
from tests.test_render_queue_repository import _create_job
from tests.test_youtube_repository import _create_video


def _prepare_ready_publication():
    content_item_id, video_id = _create_video()
    execution_id = "preview-execution-1"
    job = _create_job()
    job["content_item_id"] = content_item_id
    job["video_id"] = video_id
    job["execution_id"] = execution_id
    render_job_id = enqueue_render_job(job)

    github_execution = {
        "run_id": 35050000001,
        "repository": "zenindiones-maker/BR-no-GTA",
        "workflow": "render-worker.yml",
        "ref": "work/gate6f-analytics-learning",
        "artifact_name": "render-output",
        "artifact_id": 987654,
        "artifact_size_in_bytes": 123456789,
        "artifact_remote_uri": (
            "github-actions://zenindiones-maker/BR-no-GTA/actions/runs/"
            "35050000001/artifacts/987654/render-output"
        ),
        "artifact_expired": False,
    }
    locator = build_github_media_artifact_locator(
        {"id": render_job_id, "video_id": video_id, "execution_id": execution_id},
        github_execution,
    )
    github_execution["artifact_locator"] = locator
    stored_job = dict(job)
    stored_job.update(
        {
            "id": render_job_id,
            "status": "completed",
            "video_id": video_id,
            "execution_id": execution_id,
            "output_path": locator["media_uri"],
            "github_execution": github_execution,
        }
    )
    connection = get_connection()
    try:
        connection.execute(
            "UPDATE render_jobs SET status = 'completed', payload = ? WHERE id = ?",
            (json.dumps(stored_job, sort_keys=True), render_job_id),
        )
        connection.commit()
    finally:
        connection.close()
    assert update_video_file_path(video_id, locator["media_uri"])

    publication_id = insert_youtube_publication(
        video_id=video_id,
        content_item_id=content_item_id,
        title="Preview GTA 6",
        description="Descrição",
        tags=["gta6"],
        category_id="20",
        file_path=locator["media_uri"],
        privacy_status="private",
    )
    artifact_evidence = {
        "render_job_id": render_job_id,
        "video_id": video_id,
        "execution_id": execution_id,
        "workflow_run_id": locator["workflow_run_id"],
        "artifact_id": locator["artifact_id"],
        "media_relative_path": locator["media_relative_path"],
        "size_bytes": 456789012,
        "sha256": "a" * 64,
        "duration_seconds": 1500.0,
        "qa_status": "PASS",
    }
    cloud_execution = {
        "status": "SUCCEEDED",
        "run_id": 35050000002,
        "execution_id": "upload-execution-1",
        "routing_id": "upload-routing-1",
        "authorization_id": "upload-auth-1",
        "capability_id": "youtube.upload-private",
        "result": {
            "status": "UPLOADED",
            "publication_id": publication_id,
            "video_id": video_id,
            "youtube_video_id": "youtube-preview-1",
            "youtube_url": "https://www.youtube.com/watch?v=youtube-preview-1",
            "artifact_evidence": artifact_evidence,
        },
    }
    connection = get_connection()
    try:
        connection.execute(
            """
            UPDATE youtube_publications
            SET status = 'uploaded', youtube_video_id = ?, youtube_url = ?,
                cloud_execution = ?
            WHERE id = ?
            """,
            (
                "youtube-preview-1",
                "https://www.youtube.com/watch?v=youtube-preview-1",
                json.dumps(cloud_execution, sort_keys=True),
                publication_id,
            ),
        )
        connection.commit()
    finally:
        connection.close()

    goal_id = "goal-preview-1"
    create_gta6_goal(
        goal_id=goal_id,
        goal_type="EVERGREEN",
        topic="Preview publication readiness",
        status="READY",
        priority="HIGH",
        opportunity_score=9.0,
        target_duration="25m",
        current_stage="YOUTUBE_PUBLISH",
    )
    upsert_gta6_goal_artifacts(
        goal_id=goal_id,
        content_item_id=content_item_id,
        video_id=video_id,
        render_job_id=render_job_id,
        youtube_publication_id=publication_id,
    )
    return publication_id, goal_id, video_id, render_job_id, cloud_execution


def test_preview_proves_exact_uploaded_private_lineage_without_mutation():
    publication_id, goal_id, video_id, render_job_id, cloud_execution = _prepare_ready_publication()
    before = get_youtube_publication(publication_id)
    preview = build_youtube_publication_preview(publication_id)
    after = get_youtube_publication(publication_id)

    assert preview["PUBLICATION_READY"] is True
    assert preview["approval_granted"] is False
    assert preview["boundary"] == "READ_ONLY_NO_PUBLICATION_AUTHORITY"
    assert preview["goal_id"] == goal_id
    assert preview["video_id"] == video_id
    assert preview["render_job_id"] == render_job_id
    assert preview["qa_status"] == "PASS"
    assert preview["artifact_identity"]["artifact_id"] == 987654
    assert preview["reasons"] == ["uploaded_private_and_lineage_verified"]
    assert before == after
    assert get_youtube_cloud_execution(publication_id) == cloud_execution


def test_preview_fails_closed_on_artifact_identity_mismatch():
    publication_id, _, _, _, _ = _prepare_ready_publication()
    connection = get_connection()
    try:
        row = connection.execute(
            "SELECT cloud_execution FROM youtube_publications WHERE id = ?",
            (publication_id,),
        ).fetchone()
        cloud = json.loads(row["cloud_execution"])
        cloud["result"]["artifact_evidence"]["artifact_id"] += 1
        connection.execute(
            "UPDATE youtube_publications SET cloud_execution = ? WHERE id = ?",
            (json.dumps(cloud, sort_keys=True), publication_id),
        )
        connection.commit()
    finally:
        connection.close()

    preview = build_youtube_publication_preview(publication_id)
    assert preview["PUBLICATION_READY"] is False
    assert any("artifact_id" in reason for reason in preview["reasons"])


def test_preview_blocks_uncertain_public_transition_until_reconciled():
    publication_id, _, _, _, _ = _prepare_ready_publication()
    connection = get_connection()
    try:
        row = connection.execute(
            "SELECT cloud_execution FROM youtube_publications WHERE id = ?",
            (publication_id,),
        ).fetchone()
        cloud = json.loads(row["cloud_execution"])
        cloud["public_transition"] = {
            "status": "REMOTE_STATE_UNCERTAIN",
            "publication_id": publication_id,
            "youtube_video_id": "youtube-preview-1",
            "authorization_id": "consumed-public-auth",
        }
        connection.execute(
            "UPDATE youtube_publications SET cloud_execution = ? WHERE id = ?",
            (json.dumps(cloud, sort_keys=True), publication_id),
        )
        connection.commit()
    finally:
        connection.close()

    preview = build_youtube_publication_preview(publication_id)
    assert preview["PUBLICATION_READY"] is False
    assert preview["public_transition_status"] == "REMOTE_STATE_UNCERTAIN"
    assert "public_transition_requires_remote_reconciliation" in preview["reasons"]
