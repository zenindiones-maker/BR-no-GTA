from __future__ import annotations

import sqlite3

import pytest

from app.database import gta6_monitor_event_repository as repository


@pytest.fixture
def database_path(tmp_path, monkeypatch):
    database_path = tmp_path / "gta6_monitor_events.db"

    connection = sqlite3.connect(database_path)
    connection.execute(
        """
        CREATE TABLE gta6_monitor_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT NOT NULL,
            previous_hash TEXT,
            current_hash TEXT NOT NULL,
            detected_at TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    connection.commit()
    connection.close()

    def get_connection():
        connection = sqlite3.connect(database_path)
        connection.row_factory = sqlite3.Row
        return connection

    monkeypatch.setattr(
        repository,
        "get_connection",
        get_connection,
    )

    return database_path


def test_create_event(database_path) -> None:
    result = repository.create_gta6_monitor_event(
        " https://example.com ",
        " old-hash ",
        " new-hash ",
        " 2026-09-02T00:00:00 ",
    )

    assert result["id"] == 1
    assert result["url"] == "https://example.com"
    assert result["previous_hash"] == "old-hash"
    assert result["current_hash"] == "new-hash"
    assert result["detected_at"] == "2026-09-02T00:00:00"


def test_create_event_without_detected_at_uses_database_timestamp(
    database_path,
) -> None:
    result = repository.create_gta6_monitor_event(
        "https://example.com",
        None,
        "hash",
    )

    assert result["detected_at"]
    assert result["current_hash"] == "hash"


def test_get_event(database_path) -> None:
    created = repository.create_gta6_monitor_event(
        "https://example.com",
        "old",
        "new",
        "2026-09-02T00:00:00",
    )

    result = repository.get_gta6_monitor_event(
        created["id"]
    )

    assert result == created


def test_get_missing_event_returns_none(database_path) -> None:
    assert repository.get_gta6_monitor_event(999) is None


def test_list_all_events(database_path) -> None:
    repository.create_gta6_monitor_event(
        "https://one.example",
        None,
        "hash-1",
    )
    repository.create_gta6_monitor_event(
        "https://two.example",
        "hash-1",
        "hash-2",
    )

    result = repository.list_gta6_monitor_events()

    assert len(result) == 2
    assert result[0]["url"] == "https://one.example"
    assert result[1]["url"] == "https://two.example"


def test_list_events_by_url(database_path) -> None:
    repository.create_gta6_monitor_event(
        "https://one.example",
        None,
        "hash-1",
    )
    repository.create_gta6_monitor_event(
        "https://two.example",
        None,
        "hash-2",
    )
    repository.create_gta6_monitor_event(
        "https://one.example",
        "hash-1",
        "hash-3",
    )

    result = repository.list_gta6_monitor_events(
        " https://one.example "
    )

    assert len(result) == 2
    assert result[0]["current_hash"] == "hash-1"
    assert result[1]["current_hash"] == "hash-3"


@pytest.mark.parametrize(
    "url",
    ["", " ", None],
)
def test_create_rejects_invalid_url(database_path, url) -> None:
    with pytest.raises(
        ValueError,
        match="url must be a non-empty string",
    ):
        repository.create_gta6_monitor_event(
            url,
            None,
            "hash",
        )


def test_create_rejects_invalid_previous_hash(database_path) -> None:
    with pytest.raises(
        ValueError,
        match="previous_hash must be a non-empty string or None",
    ):
        repository.create_gta6_monitor_event(
            "https://example.com",
            " ",
            "hash",
        )


def test_create_rejects_invalid_current_hash(database_path) -> None:
    with pytest.raises(
        ValueError,
        match="current_hash must be a non-empty string",
    ):
        repository.create_gta6_monitor_event(
            "https://example.com",
            None,
            " ",
        )


def test_create_rejects_invalid_detected_at(database_path) -> None:
    with pytest.raises(
        ValueError,
        match="detected_at must be a non-empty string or None",
    ):
        repository.create_gta6_monitor_event(
            "https://example.com",
            None,
            "hash",
            " ",
        )


@pytest.mark.parametrize(
    "event_id",
    [0, -1, True, False, "1"],
)
def test_get_rejects_invalid_event_id(
    database_path,
    event_id,
) -> None:
    with pytest.raises(
        ValueError,
        match="event_id",
    ):
        repository.get_gta6_monitor_event(event_id)


@pytest.mark.parametrize(
    "url",
    ["", " "],
)
def test_list_rejects_invalid_url(database_path, url) -> None:
    with pytest.raises(
        ValueError,
        match="url must be a non-empty string or None",
    ):
        repository.list_gta6_monitor_events(url)
