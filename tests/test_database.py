from app.database.connection import get_connection
from app.database.research_repository import (
    insert_research_item,
    list_research_items,
)
from app.database.schema import initialize_schema


def test_database_connection():
    connection = get_connection()

    try:
        row = connection.execute(
            "SELECT sqlite_version()"
        ).fetchone()

        assert row is not None
        assert row[0]
    finally:
        connection.close()


def test_schema_tables():
    initialize_schema()

    connection = get_connection()

    try:
        rows = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
            ORDER BY name
            """
        ).fetchall()

        tables = {row["name"] for row in rows}

        expected = {
            "projects",
            "sources",
            "research_items",
            "ideas",
            "content_items",
            "gta6_knowledge",
        }

        assert expected.issubset(tables)
    finally:
        connection.close()


def test_research_repository():
    initialize_schema()

    source_id = None

    item_id = insert_research_item(
        source_id=source_id,
        title="Test research item",
        content="Test content",
        url="https://example.com/research/item",
    )

    assert isinstance(item_id, int)
    assert item_id > 0

    items = list_research_items()

    assert any(
        item["id"] == item_id
        for item in items
    )
