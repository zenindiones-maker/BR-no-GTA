import os

import pytest


@pytest.fixture(autouse=True)
def test_database(tmp_path, monkeypatch):
    database_path = tmp_path / "test.db"

    monkeypatch.setenv(
        "BR_TEST_DATABASE",
        str(database_path),
    )

    yield
