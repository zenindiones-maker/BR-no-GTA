from app.database.content_repository import (
    get_content_item,
    insert_content_item,
    list_content_items,
    update_content_file_path,
    update_content_status,
)
from app.database.schema import initialize_schema


def test_insert_and_get_content():
    initialize_schema()

    content_id = insert_content_item(
        title="TESTE - conteúdo",
        content_type="video",
        status="draft",
        file_path="data/test.mp4",
    )

    assert isinstance(content_id, int)
    assert content_id > 0

    content = get_content_item(content_id)

    assert content is not None
    assert content["id"] == content_id
    assert content["title"] == "TESTE - conteúdo"
    assert content["content_type"] == "video"
    assert content["status"] == "draft"
    assert content["file_path"] == "data/test.mp4"


def test_list_content_items():
    initialize_schema()

    first_id = insert_content_item(
        title="TESTE - conteúdo 1",
        content_type="video",
    )

    second_id = insert_content_item(
        title="TESTE - conteúdo 2",
        content_type="short",
    )

    items = list_content_items()

    ids = {item["id"] for item in items}

    assert first_id in ids
    assert second_id in ids


def test_update_content_status():
    initialize_schema()

    content_id = insert_content_item(
        title="TESTE - status",
        content_type="video",
        status="draft",
    )

    assert update_content_status(
        content_id,
        "ready",
    ) is True

    content = get_content_item(content_id)

    assert content is not None
    assert content["status"] == "ready"


def test_update_content_file_path():
    initialize_schema()

    content_id = insert_content_item(
        title="TESTE - arquivo",
        content_type="video",
    )

    assert update_content_file_path(
        content_id,
        "data/content/video.mp4",
    ) is True

    content = get_content_item(content_id)

    assert content is not None
    assert content["file_path"] == "data/content/video.mp4"


def test_update_nonexistent_content():
    initialize_schema()

    assert update_content_status(
        999999,
        "ready",
    ) is False

    assert update_content_file_path(
        999999,
        "arquivo.mp4",
    ) is False

    assert get_content_item(999999) is None
