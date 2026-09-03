import pytest

from app.database.connection import get_connection
from app.database.schema import initialize_schema
from app.services.content_unit_service import (
    ContentUnitError,
    create_and_persist_content_unit,
)


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

    return {
        "idea_id": idea_id,
        "script_id": script_id,
        "content_item_id": content_item_id,
    }


def test_create_and_persist_content_unit(
    production_context,
):
    unit = create_and_persist_content_unit(
        content_item_id=production_context["content_item_id"],
        title="GTA 6 — Novo detalhe",
        unit_type="short",
        duration_seconds=60,
        media_format="9:16",
        script_id=production_context["script_id"],
        idea_id=production_context["idea_id"],
        objective="Informar",
        hook="Um novo detalhe de GTA 6 apareceu.",
        narration="Este é o texto da narração.",
        visual_requirements=[
            {
                "type": "gameplay",
                "description": "Gameplay de GTA 6",
            }
        ],
    )

    assert unit["id"] > 0
    assert unit["content_item_id"] == (
        production_context["content_item_id"]
    )
    assert unit["script_id"] == production_context["script_id"]
    assert unit["idea_id"] == production_context["idea_id"]
    assert unit["unit_type"] == "short"
    assert unit["media_format"] == "9:16"
    assert unit["duration_seconds"] == 60.0
    assert unit["status"] == "ready"

    connection = get_connection()

    row = connection.execute(
        """
        SELECT *
        FROM content_units
        WHERE id = ?
        """,
        (unit["id"],),
    ).fetchone()

    assert row is not None
    assert row["content_item_id"] == (
        production_context["content_item_id"]
    )


def test_create_and_persist_content_unit_requires_content_item_id():
    with pytest.raises(ContentUnitError):
        create_and_persist_content_unit(
            content_item_id=0,
            title="Unidade",
            unit_type="short",
            duration_seconds=60,
            media_format="9:16",
            script_id=1,
            idea_id=1,
            objective="Informar",
            hook="Hook",
            narration="Narração",
        )
