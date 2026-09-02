from app.database.content_repository import insert_content_item
from app.database.video_repository import (
    get_video,
    insert_video,
    mark_video_ready,
    list_videos,
    update_video_file_path,
    update_video_status,
)


def test_insert_and_get_video():
    content_item_id = insert_content_item(
        title="Vídeo de teste",
        content_type="short",
        status="ready",
    )

    video_id = insert_video(
        content_item_id=content_item_id,
        title="Vídeo de teste",
        status="draft",
    )

    assert video_id > 0

    video = get_video(video_id)

    assert video is not None
    assert video["id"] == video_id
    assert video["content_item_id"] == content_item_id
    assert video["title"] == "Vídeo de teste"
    assert video["status"] == "draft"
    assert video["file_path"] is None


def test_list_videos():
    content_item_id = insert_content_item(
        title="Lista de vídeos",
        content_type="short",
        status="ready",
    )

    first_id = insert_video(
        content_item_id=content_item_id,
        title="Vídeo 1",
    )

    second_id = insert_video(
        content_item_id=content_item_id,
        title="Vídeo 2",
    )

    videos = list_videos()

    ids = [video["id"] for video in videos]

    assert first_id in ids
    assert second_id in ids


def test_update_video_status():
    content_item_id = insert_content_item(
        title="Status de vídeo",
        content_type="short",
        status="ready",
    )

    video_id = insert_video(
        content_item_id=content_item_id,
        title="Vídeo",
    )

    assert update_video_status(
        video_id,
        "ready",
    ) is True

    video = get_video(video_id)

    assert video is not None
    assert video["status"] == "ready"


def test_update_video_file_path():
    content_item_id = insert_content_item(
        title="Arquivo de vídeo",
        content_type="short",
        status="ready",
    )

    video_id = insert_video(
        content_item_id=content_item_id,
        title="Vídeo",
    )

    assert update_video_file_path(
        video_id,
        "output/video.mp4",
    ) is True

    video = get_video(video_id)

    assert video is not None
    assert video["file_path"] == "output/video.mp4"


def test_mark_video_ready_persists_file_path_and_status_atomically():
    content_item_id = insert_content_item(
        title="Content Item para Video Ready",
        content_type="short",
        status="ready",
    )

    video_id = insert_video(
        content_item_id=content_item_id,
        title="Vídeo pronto",
        status="draft",
    )

    assert mark_video_ready(
        video_id,
        "renders/final.mp4",
    )

    video = get_video(video_id)

    assert video is not None
    assert video["file_path"] == "renders/final.mp4"
    assert video["status"] == "ready"


def test_mark_video_ready_returns_false_for_missing_video():
    assert not mark_video_ready(
        999999,
        "renders/missing.mp4",
    )
