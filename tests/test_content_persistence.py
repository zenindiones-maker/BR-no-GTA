import pytest

from app.database.connection import get_connection
from app.database.content_segment_repository import (
    get_content_segment,
    insert_content_segment,
    list_content_segments,
    update_content_segment_file_path,
    update_content_segment_status,
)
from app.database.content_unit_repository import (
    get_content_unit,
    insert_content_unit,
    list_content_units,
    update_content_unit_file_path,
    update_content_unit_status,
)
from app.database.schema import initialize_schema


@pytest.fixture
def production_context():
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
            "Texto do roteiro.",
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

    return {
        "idea_id": idea_id,
        "script_id": script_id,
        "content_item_id": content_item_id,
    }


def test_content_unit_persists_full_specification(
    production_context,
):
    unit_id = insert_content_unit(
        content_item_id=production_context["content_item_id"],
        title="Unidade GTA 6",
        unit_type="short",
        duration_seconds=60,
        media_format="9:16",
        script_id=production_context["script_id"],
        idea_id=production_context["idea_id"],
        objective="Informar",
        hook="Novo detalhe de GTA 6.",
        narration="Narração.",
        visual_requirements=[
            {
                "type": "gameplay",
                "description": "Gameplay GTA 6",
            }
        ],
    )

    unit = get_content_unit(unit_id)

    assert unit is not None
    assert unit["content_item_id"] == production_context["content_item_id"]
    assert unit["script_id"] == production_context["script_id"]
    assert unit["idea_id"] == production_context["idea_id"]
    assert unit["duration_seconds"] == 60.0
    assert unit["media_format"] == "9:16"
    assert unit["visual_requirements"][0]["type"] == "gameplay"
    assert unit["status"] == "ready"


def test_content_units_can_be_filtered_by_parent(
    production_context,
):
    unit_id = insert_content_unit(
        content_item_id=production_context["content_item_id"],
        title="Unidade",
        unit_type="short",
        duration_seconds=45,
        media_format="9:16",
        script_id=production_context["script_id"],
        idea_id=production_context["idea_id"],
        objective="Informar",
        hook="Hook",
        narration="Narração",
    )

    units = list_content_units(
        content_item_id=production_context["content_item_id"]
    )

    assert [unit["id"] for unit in units] == [unit_id]


def test_content_unit_status_and_file_path_can_be_updated(
    production_context,
):
    unit_id = insert_content_unit(
        content_item_id=production_context["content_item_id"],
        title="Unidade",
        unit_type="segment",
        duration_seconds=90,
        media_format="16:9",
        script_id=production_context["script_id"],
        idea_id=production_context["idea_id"],
        objective="Informar",
        hook="Hook",
        narration="Narração",
    )

    assert update_content_unit_status(
        unit_id,
        "rendered",
    )

    assert update_content_unit_file_path(
        unit_id,
        "output/unit.mp4",
    )

    unit = get_content_unit(unit_id)

    assert unit["status"] == "rendered"
    assert unit["file_path"] == "output/unit.mp4"


def test_segment_persists_and_belongs_to_content_unit(
    production_context,
):
    unit_id = insert_content_unit(
        content_item_id=production_context["content_item_id"],
        title="Unidade",
        unit_type="segment",
        duration_seconds=90,
        media_format="16:9",
        script_id=production_context["script_id"],
        idea_id=production_context["idea_id"],
        objective="Informar",
        hook="Hook",
        narration="Narração",
    )

    segment_id = insert_content_segment(
        content_unit_id=unit_id,
        segment_order=0,
        duration_seconds=30,
        media_format="9:16",
        source_start_seconds=0,
        source_end_seconds=30,
        role="short",
    )

    segment = get_content_segment(segment_id)

    assert segment is not None
    assert segment["content_unit_id"] == unit_id
    assert segment["segment_order"] == 0
    assert segment["duration_seconds"] == 30.0
    assert segment["media_format"] == "9:16"
    assert segment["role"] == "short"


def test_segments_are_returned_in_editorial_order(
    production_context,
):
    unit_id = insert_content_unit(
        content_item_id=production_context["content_item_id"],
        title="Unidade",
        unit_type="segment",
        duration_seconds=120,
        media_format="16:9",
        script_id=production_context["script_id"],
        idea_id=production_context["idea_id"],
        objective="Informar",
        hook="Hook",
        narration="Narração",
    )

    insert_content_segment(
        content_unit_id=unit_id,
        segment_order=2,
        duration_seconds=30,
        media_format="16:9",
        source_start_seconds=60,
        source_end_seconds=90,
    )

    insert_content_segment(
        content_unit_id=unit_id,
        segment_order=0,
        duration_seconds=30,
        media_format="16:9",
        source_start_seconds=0,
        source_end_seconds=30,
    )

    insert_content_segment(
        content_unit_id=unit_id,
        segment_order=1,
        duration_seconds=30,
        media_format="16:9",
        source_start_seconds=30,
        source_end_seconds=60,
    )

    segments = list_content_segments(unit_id)

    assert [segment["segment_order"] for segment in segments] == [
        0,
        1,
        2,
    ]


def test_duplicate_segment_order_is_rejected(
    production_context,
):
    unit_id = insert_content_unit(
        content_item_id=production_context["content_item_id"],
        title="Unidade",
        unit_type="segment",
        duration_seconds=60,
        media_format="16:9",
        script_id=production_context["script_id"],
        idea_id=production_context["idea_id"],
        objective="Informar",
        hook="Hook",
        narration="Narração",
    )

    insert_content_segment(
        content_unit_id=unit_id,
        segment_order=0,
        duration_seconds=30,
        media_format="16:9",
        source_start_seconds=0,
        source_end_seconds=30,
    )

    with pytest.raises(Exception):
        insert_content_segment(
            content_unit_id=unit_id,
            segment_order=0,
            duration_seconds=30,
            media_format="16:9",
            source_start_seconds=30,
            source_end_seconds=60,
        )


def test_segment_status_and_file_path_can_be_updated(
    production_context,
):
    unit_id = insert_content_unit(
        content_item_id=production_context["content_item_id"],
        title="Unidade",
        unit_type="segment",
        duration_seconds=60,
        media_format="16:9",
        script_id=production_context["script_id"],
        idea_id=production_context["idea_id"],
        objective="Informar",
        hook="Hook",
        narration="Narração",
    )

    segment_id = insert_content_segment(
        content_unit_id=unit_id,
        segment_order=0,
        duration_seconds=30,
        media_format="9:16",
        source_start_seconds=0,
        source_end_seconds=30,
    )

    assert update_content_segment_status(
        segment_id,
        "rendered",
    )

    assert update_content_segment_file_path(
        segment_id,
        "output/segment.mp4",
    )

    segment = get_content_segment(segment_id)

    assert segment["status"] == "rendered"
    assert segment["file_path"] == "output/segment.mp4"


def test_deleting_content_unit_cascades_segments(
    production_context,
):
    unit_id = insert_content_unit(
        content_item_id=production_context["content_item_id"],
        title="Unidade",
        unit_type="segment",
        duration_seconds=60,
        media_format="16:9",
        script_id=production_context["script_id"],
        idea_id=production_context["idea_id"],
        objective="Informar",
        hook="Hook",
        narration="Narração",
    )

    insert_content_segment(
        content_unit_id=unit_id,
        segment_order=0,
        duration_seconds=30,
        media_format="9:16",
        source_start_seconds=0,
        source_end_seconds=30,
    )

    connection = get_connection()
    connection.execute(
        "PRAGMA foreign_keys = ON"
    )
    connection.execute(
        "DELETE FROM content_units WHERE id = ?",
        (unit_id,),
    )
    connection.commit()

    assert list_content_segments(unit_id) == []
