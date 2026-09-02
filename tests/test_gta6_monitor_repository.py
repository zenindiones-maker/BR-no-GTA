from __future__ import annotations

import sqlite3

import pytest

from app.database import gta6_monitor_repository


def _setup_database(monkeypatch, tmp_path):
    database_path = tmp_path / "test.db"

    def fake_get_connection():
        connection = sqlite3.connect(database_path)
        connection.row_factory = sqlite3.Row

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS gta6_monitor_state (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL UNIQUE,
                content_hash TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.commit()

        return connection

    monkeypatch.setattr(
        gta6_monitor_repository,
        "get_connection",
        fake_get_connection,
    )


def test_get_returns_none_when_state_does_not_exist(
    monkeypatch,
    tmp_path,
):
    _setup_database(monkeypatch, tmp_path)

    result = gta6_monitor_repository.get_gta6_monitor_state(
        "https://example.com"
    )

    assert result is None


def test_save_creates_state(
    monkeypatch,
    tmp_path,
):
    _setup_database(monkeypatch, tmp_path)

    result = gta6_monitor_repository.save_gta6_monitor_state(
        "https://example.com",
        "abc123",
    )

    assert result["url"] == "https://example.com"
    assert result["content_hash"] == "abc123"


def test_get_returns_saved_state(
    monkeypatch,
    tmp_path,
):
    _setup_database(monkeypatch, tmp_path)

    gta6_monitor_repository.save_gta6_monitor_state(
        "https://example.com",
        "abc123",
    )

    result = gta6_monitor_repository.get_gta6_monitor_state(
        "https://example.com"
    )

    assert result is not None
    assert result["url"] == "https://example.com"
    assert result["content_hash"] == "abc123"


def test_save_updates_existing_url(
    monkeypatch,
    tmp_path,
):
    _setup_database(monkeypatch, tmp_path)

    gta6_monitor_repository.save_gta6_monitor_state(
        "https://example.com",
        "abc123",
    )

    updated = gta6_monitor_repository.save_gta6_monitor_state(
        "https://example.com",
        "def456",
    )

    result = gta6_monitor_repository.get_gta6_monitor_state(
        "https://example.com"
    )

    assert updated["id"] == result["id"]
    assert result["content_hash"] == "def456"


@pytest.mark.parametrize(
    "url",
    ["", "   ", None],
)
def test_get_rejects_invalid_url(
    monkeypatch,
    tmp_path,
    url,
):
    _setup_database(monkeypatch, tmp_path)

    with pytest.raises(ValueError, match="url must be a non-empty string"):
        gta6_monitor_repository.get_gta6_monitor_state(url)


@pytest.mark.parametrize(
    "url",
    ["", "   ", None],
)
def test_save_rejects_invalid_url(
    monkeypatch,
    tmp_path,
    url,
):
    _setup_database(monkeypatch, tmp_path)

    with pytest.raises(ValueError, match="url must be a non-empty string"):
        gta6_monitor_repository.save_gta6_monitor_state(
            url,
            "abc123",
        )


@pytest.mark.parametrize(
    "content_hash",
    ["", "   ", None],
)
def test_save_rejects_invalid_hash(
    monkeypatch,
    tmp_path,
    content_hash,
):
    _setup_database(monkeypatch, tmp_path)

    with pytest.raises(
        ValueError,
        match="content_hash must be a non-empty string",
    ):
        gta6_monitor_repository.save_gta6_monitor_state(
            "https://example.com",
            content_hash,
        )


def test_save_strips_url_and_hash(
    monkeypatch,
    tmp_path,
):
    _setup_database(monkeypatch, tmp_path)

    result = gta6_monitor_repository.save_gta6_monitor_state(
        "  https://example.com  ",
        "  abc123  ",
    )

    assert result["url"] == "https://example.com"
    assert result["content_hash"] == "abc123"
