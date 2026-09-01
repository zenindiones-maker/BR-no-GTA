import pytest

from app.database.project_repository import (
    get_project,
    insert_project,
    list_projects,
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


def test_get_nonexistent_project():
    initialize_schema()

    assert get_project(999999) is None


def test_project_name_is_unique():
    initialize_schema()

    insert_project("UNIQUE TEST PROJECT")

    with pytest.raises(Exception):
        insert_project("UNIQUE TEST PROJECT")
