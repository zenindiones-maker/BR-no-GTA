import json

import pytest

from app.database.connection import get_connection
from app.database.content_repository import insert_content_item
from app.database.video_repository import insert_video
from app.database.youtube_repository import insert_youtube_publication
from app.database.youtube_cloud_execution_repository import (
    claim_youtube_cloud_execution,
    get_youtube_cloud_execution,
    mark_youtube_cloud_dispatch_uncertain,
    reset_recoverable_youtube_cloud_dispatch_uncertain,
)

WORKFLOW="youtube-private-upload-worker.yml"
MISSING_WORKFLOW_ERROR=(
    "GitHub Actions command failed with exit code 1: HTTP 404: "
    "workflow youtube-private-upload-worker.yml not found on the default branch "
    "(https://api.github.com/repos/zenindiones-maker/BR-no-GTA/actions/workflows/youtube-private-upload-worker.yml)"
)


def _publication(*, privacy="private"):
    content_id=insert_content_item(title="Video A",content_type="video",status="ready")
    video_id=insert_video(content_item_id=content_id,title="Video A",status="ready",file_path="cloud://qa.mp4")
    return insert_youtube_publication(
        video_id=video_id,
        content_item_id=content_id,
        title="Video A",
        privacy_status=privacy,
        file_path="cloud://qa.mp4",
    )


def _uncertain(publication_id: int, error: str=MISSING_WORKFLOW_ERROR):
    claim_youtube_cloud_execution(
        publication_id,
        execution_id="yt-exec-1",
        routing_id="route-1",
        authorization_id="auth-1",
    )
    return mark_youtube_cloud_dispatch_uncertain(
        publication_id,
        expected_execution_id="yt-exec-1",
        error=error,
    )


def test_missing_default_branch_workflow_uncertain_dispatch_can_be_reset():
    publication_id=_publication()
    _uncertain(publication_id)
    result=reset_recoverable_youtube_cloud_dispatch_uncertain(
        publication_id,
        expected_workflow=WORKFLOW,
    )
    assert result["status"]=="RESET"
    assert result["run_id"] is None
    assert get_youtube_cloud_execution(publication_id) is None


def test_uncertain_dispatch_with_run_id_is_never_reset():
    publication_id=_publication()
    _uncertain(publication_id)
    connection=get_connection()
    try:
        current=get_youtube_cloud_execution(publication_id)
        current["run_id"]=12345
        connection.execute(
            "UPDATE youtube_publications SET cloud_execution=? WHERE id=?",
            (json.dumps(current),publication_id),
        )
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(ValueError,match="run_id cannot be reset"):
        reset_recoverable_youtube_cloud_dispatch_uncertain(publication_id,expected_workflow=WORKFLOW)
    assert get_youtube_cloud_execution(publication_id)["run_id"]==12345


def test_other_uncertain_dispatch_error_remains_fail_closed():
    publication_id=_publication()
    _uncertain(publication_id,"network timeout after dispatch request")
    with pytest.raises(ValueError,match="not the deterministic missing-workflow failure"):
        reset_recoverable_youtube_cloud_dispatch_uncertain(publication_id,expected_workflow=WORKFLOW)
    assert get_youtube_cloud_execution(publication_id)["status"]=="DISPATCH_UNCERTAIN"


def test_non_private_publication_uncertain_dispatch_is_never_reset():
    publication_id=_publication(privacy="public")
    _uncertain(publication_id)
    with pytest.raises(ValueError,match="pending/private"):
        reset_recoverable_youtube_cloud_dispatch_uncertain(publication_id,expected_workflow=WORKFLOW)
    assert get_youtube_cloud_execution(publication_id)["status"]=="DISPATCH_UNCERTAIN"
