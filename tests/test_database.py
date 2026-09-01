import sqlite3

from app.database.connection import get_connection
from app.database.repository import (
    insert_project,
    insert_source,
    list_projects,
    list_sources,
)
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
        }

        assert expected.issubset(tables)
    finally:
        connection.close()


def test_project_repository():
    initialize_schema()

    project_id = insert_project("TEST PROJECT")

    assert isinstance(project_id, int)
    assert project_id > 0

    projects = list_projects()

    assert any(
        project["id"] == project_id
        for project in projects
    )


def test_source_repository():
    initialize_schema()

    source_id = insert_source(
        "TEST SOURCE",
        "https://example.com",
        "test",
    )

    assert isinstance(source_id, int)
    assert source_id > 0

    sources = list_sources()

    assert any(
        source["id"] == source_id
        for source in sources
    )


def test_research_repository():
    initialize_schema()

    source_id = insert_source(
        "TEST RESEARCH SOURCE",
        "https://example.com/research",
        "test",
    )

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
