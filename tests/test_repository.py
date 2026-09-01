import pytest

from app.database.repository import (
    get_project,
    get_source,
    insert_project,
    insert_source,
    list_projects,
    list_sources,
)
from app.database.schema import initialize_schema


def test_insert_and_get_project():
    initialize_schema()

    project_id = insert_project("TEST PROJECT")

    assert isinstance(project_id, int)
    assert project_id > 0

    project = get_project(project_id)

    assert project is not None
    assert project["id"] == project_id
    assert project["name"] == "TEST PROJECT"


def test_list_projects():
    initialize_schema()

    first_id = insert_project("TEST PROJECT 1")
    second_id = insert_project("TEST PROJECT 2")

    projects = list_projects()

    ids = {project["id"] for project in projects}

    assert first_id in ids
    assert second_id in ids


def test_insert_and_get_source():
    initialize_schema()

    source_id = insert_source(
        name="TEST SOURCE",
        url="https://example.com",
        source_type="website",
    )

    assert isinstance(source_id, int)
    assert source_id > 0

    source = get_source(source_id)

    assert source is not None
    assert source["id"] == source_id
    assert source["name"] == "TEST SOURCE"
    assert source["url"] == "https://example.com"
    assert source["source_type"] == "website"


def test_list_sources():
    initialize_schema()

    first_id = insert_source(
        name="TEST SOURCE 1",
        url="https://example.com/1",
        source_type="website",
    )

    second_id = insert_source(
        name="TEST SOURCE 2",
        url="https://example.com/2",
        source_type="platform",
    )

    sources = list_sources()

    ids = {source["id"] for source in sources}

    assert first_id in ids
    assert second_id in ids


def test_get_nonexistent_project_and_source():
    initialize_schema()

    assert get_project(999999) is None
    assert get_source(999999) is None


def test_project_name_is_unique():
    initialize_schema()

    insert_project("UNIQUE TEST PROJECT")

    with pytest.raises(Exception):
        insert_project("UNIQUE TEST PROJECT")
