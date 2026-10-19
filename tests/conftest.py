import os
import shutil

import pytest

from app.database.schema import initialize_schema


@pytest.fixture(scope="session")
def initialized_database_template(tmp_path_factory):
    """Build the empty canonical SQLite schema once; tests still get isolated DB files."""
    template_root = tmp_path_factory.mktemp("database-template")
    template_path = template_root / "template.db"
    previous = os.environ.get("BR_TEST_DATABASE")
    os.environ["BR_TEST_DATABASE"] = str(template_path)
    try:
        initialize_schema()
    finally:
        if previous is None:
            os.environ.pop("BR_TEST_DATABASE", None)
        else:
            os.environ["BR_TEST_DATABASE"] = previous
    if not template_path.is_file():
        raise RuntimeError("test database template was not created")
    return template_path


@pytest.fixture(autouse=True)
def test_database(tmp_path, monkeypatch, initialized_database_template):
    database_path = tmp_path / "test.db"
    shutil.copyfile(initialized_database_template, database_path)

    monkeypatch.setenv(
        "BR_TEST_DATABASE",
        str(database_path),
    )

    yield


@pytest.fixture(autouse=True)
def _legacy_script_first_gate_off(monkeypatch, tmp_path):
    """Legacy unit fixtures predate the script-first gate (11/10/2026).

    Production code is fail-closed; gate behaviour is covered explicitly in
    tests/test_script_first_single_video.py which re-enables enforcement.
    """
    monkeypatch.setenv("BR_SCRIPT_FIRST_GATE_ENFORCE", "0")
    # Nunca gravar roteiros de teste em content/roteiros do repositório.
    monkeypatch.setenv("BR_ROTEIROS_ROOT", str(tmp_path / "roteiros-test"))
