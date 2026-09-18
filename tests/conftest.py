import os
import shutil

import pytest

from app.database.schema import initialize_schema


@pytest.fixture(scope="session")
def database_template(tmp_path_factory):
    """Build the complete SQLite schema once, then clone it per test.

    Every test still receives its own database file. The template only removes
    repeated schema/migration work; no mutable database state is shared.
    """
    template_dir = tmp_path_factory.mktemp("database-template")
    template_path = template_dir / "template.db"
    previous = os.environ.get("BR_TEST_DATABASE")
    os.environ["BR_TEST_DATABASE"] = str(template_path)
    try:
        initialize_schema()
    finally:
        if previous is None:
            os.environ.pop("BR_TEST_DATABASE", None)
        else:
            os.environ["BR_TEST_DATABASE"] = previous
    return template_path


@pytest.fixture(autouse=True)
def test_database(tmp_path, monkeypatch, database_template):
    database_path = tmp_path / "test.db"
    shutil.copyfile(database_template, database_path)
    monkeypatch.setenv("BR_TEST_DATABASE", str(database_path))
    yield
