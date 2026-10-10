"""Regression: busy Telegram chat cannot hide verified owner voice behind 500 text inputs."""
from __future__ import annotations

import sqlite3

import pytest

from app.database import telegram_user_input_repository as repository


@pytest.fixture()
def database(tmp_path, monkeypatch):
    path = tmp_path / "inputs.db"

    def connect():
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(repository, "get_connection", connect)
    conn = connect()
    repository._ensure_schema(conn)
    conn.commit()
    conn.close()
    return connect


def _add(db, n, *, user=77, chat=-100123, kind="chat", verified=0):
    conn=db()
    conn.execute(
        """INSERT INTO telegram_user_inputs
           (telegram_user_id,telegram_chat_id,telegram_message_id,
            telegram_update_id,input_kind,telegram_file_id,
            telegram_file_unique_id,remote_verified,classification,learning_status)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (user,chat,n,n+5000,kind,f"file-{n}",f"unique-{n}",
         verified,"owner_voice_reference" if kind=="voice" else "chat","captured"),
    )
    conn.commit()
    conn.close()


def test_voice_older_than_500_general_messages_is_still_found(database):
    _add(database, 1, kind="voice", verified=1)
    _add(database, 2, kind="voice", verified=1, user=88)
    for n in range(3, 510):
        _add(database, n)
    matches = repository.list_verified_owner_voice_inputs(
        owner_user_id=77,
        allowed_chat_ids={-100123},
        limit=30,
    )
    assert [r["telegram_message_id"] for r in matches] == [1]
    assert all(r["remote_verified"] is True for r in matches)


def test_voice_query_rejects_truncated_results(database):
    for n in range(1, 5):
        _add(database, n, kind="voice", verified=1)
    with pytest.raises(RuntimeError, match="OWNER_VOICE_REFERENCE_INDEX_TRUNCATED"):
        repository.list_verified_owner_voice_inputs(
            owner_user_id=77, allowed_chat_ids={-100123}, limit=2
        )


def test_voice_query_is_owner_chat_and_remote_verification_bounded(database):
    _add(database, 1, kind="voice", verified=0)
    _add(database, 2, kind="voice", verified=1, chat=-100999)
    _add(database, 3, kind="voice", verified=1, user=88)
    _add(database, 4, kind="voice", verified=1)
    selected = repository.list_verified_owner_voice_inputs(
        owner_user_id=77, allowed_chat_ids={-100123}, limit=20
    )
    assert [r["telegram_message_id"] for r in selected] == [4]
