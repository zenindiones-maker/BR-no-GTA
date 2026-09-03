import pytest

from app.database.connection import get_connection
from app.database.schema import initialize_schema
from app.database.content_unit_repository import insert_content_unit
from app.services.content_segment_service import (
    ContentSegmentError,
    create_and_persist_content_segment,
)


@pytest.fixture
def content_unit_id():
    initialize_schema()

    connection = get_connection()

    idea_cursor = connection.execute(
        """
        INSERT INTO ideas (
            title,
            description,
            status
        )
        VALUES (?, ?, ?)
        """,
        (
            "Ideia GTA 6",
            "Ideia para produção.",
            "approved",
        ),
    )
    idea_id = int(idea_cursor.lastrowid)

    script_cursor = connection.execute(
        """
        INSERT INTO scripts (
            idea_id,
            title,
            content,
            status
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            idea_id,
            "Roteiro GTA 6",
            "Roteiro de teste.",
            "ready",
        ),
    )
    script_id = int(script_cursor.lastrowid)

    content_cursor = connection.execute(
        """
        INSERT INTO content_items (
            title,
            content_type,
            status
        )
        VALUES (?, ?, ?)
        """,
        (
            "Content Item GTA 6",
            "video",
            "ready",
        ),
    )
    content_item_id = int(content_cursor.lastrowid)

    connection.commit()

    return insert_content_unit(
        content_item_id=content_item_id,
        title="Unidade GTA 6",
        unit_type="short",
        duration_seconds=60,
        media_format="9:16",
        script_id=script_id,
        idea_id=idea_id,
        objective="Informar",
        hook="Novo detalhe de GTA 6.",
        narration="Narração da unidade.",
        visual_requirements=[],
        status="ready",
    )


def test_create_and_persist_content_segment(
    content_unit_id,
):
    segment = create_and_persist_content_segment(
        content_unit_id=content_unit_id,
        order=0,
        duration_seconds=30,
        media_format="9:16",
        source_start_seconds=0,
        source_end_seconds=30,
    )

    assert segment["id"] > 0
    assert segment["content_unit_id"] == content_unit_id
    assert segment["segment_order"] == 0
    assert segment["duration_seconds"] == 30.0
    assert segment["media_format"] == "9:16"
    assert segment["source_start_seconds"] == 0.0
    assert segment["source_end_seconds"] == 30.0
    assert segment["role"] == "content"
    assert segment["status"] == "ready"


def test_segment_is_persisted_with_content_unit_lineage(
    content_unit_id,
):
    segment = create_and_persist_content_segment(
        content_unit_id=content_unit_id,
        order=1,
        duration_seconds=20,
        media_format="16:9",
        source_start_seconds=10,
        source_end_seconds=30,
    )

    connection = get_connection()

    row = connection.execute(
        """
        SELECT *
        FROM content_segments
        WHERE id = ?
        """,
        (segment["id"],),
    ).fetchone()

    assert row is not None
    assert row["content_unit_id"] == content_unit_id
    assert row["segment_order"] == 1
    assert row["media_format"] == "16:9"


def test_same_content_unit_can_have_multiple_segments(
    content_unit_id,
):
    first = create_and_persist_content_segment(
        content_unit_id=content_unit_id,
        order=0,
        duration_seconds=20,
        media_format="9:16",
        source_start_seconds=0,
        source_end_seconds=20,
    )

    second = create_and_persist_content_segment(
        content_unit_id=content_unit_id,
        order=1,
        duration_seconds=25,
        media_format="16:9",
        source_start_seconds=20,
        source_end_seconds=45,
    )

    assert first["id"] != second["id"]
    assert first["content_unit_id"] == second["content_unit_id"]


def test_duplicate_segment_order_is_rejected(
    content_unit_id,
):
    create_and_persist_content_segment(
        content_unit_id=content_unit_id,
        order=0,
        duration_seconds=20,
        media_format="9:16",
        source_start_seconds=0,
        source_end_seconds=20,
    )

    with pytest.raises(Exception):
        create_and_persist_content_segment(
            content_unit_id=content_unit_id,
            order=0,
            duration_seconds=20,
            media_format="9:16",
            source_start_seconds=20,
            source_end_seconds=40,
        )


def test_invalid_content_unit_id_is_rejected():
    with pytest.raises(ContentSegmentError):
        create_and_persist_content_segment(
            content_unit_id=0,
            order=0,
            duration_seconds=20,
            media_format="9:16",
            source_start_seconds=0,
            source_end_seconds=20,
        )


def test_segment_remains_declarative(
    content_unit_id,
):
    segment = create_and_persist_content_segment(
        content_unit_id=content_unit_id,
        order=0,
        duration_seconds=20,
        media_format="9:16",
        source_start_seconds=0,
        source_end_seconds=20,
    )

    assert segment["file_path"] is None
    assert "render_job_id" not in segment
    assert "youtube_video_id" not in segment
