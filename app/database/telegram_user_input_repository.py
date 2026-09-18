from __future__ import annotations

import json
from typing import Any

from app.database.connection import get_connection


VALID_CLASSIFICATIONS = {
    "chat",
    "question",
    "idea",
    "theme",
    "news",
    "knowledge_note",
    "reference_media",
    "channel_standard",
    "brand_asset",
}

VALID_LEARNING_STATUSES = {
    "captured",
    "learned",
    "pending_cloud_analysis",
    "command_only",
}
VALID_EXECUTION_OUTCOME_STATUSES = {
    "NOT_OBSERVED",
    "COMPLETED",
    "FAILED",
    "BLOCKED",
    "CANCELLED",
}


def _ensure_schema(connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS telegram_user_inputs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_user_id INTEGER NOT NULL,
            telegram_chat_id INTEGER NOT NULL,
            telegram_message_id INTEGER NOT NULL,
            telegram_update_id INTEGER,
            input_kind TEXT NOT NULL,
            text_content TEXT NOT NULL DEFAULT '',
            telegram_file_id TEXT,
            telegram_file_unique_id TEXT,
            file_name TEXT,
            mime_type TEXT,
            file_size INTEGER,
            width INTEGER,
            height INTEGER,
            duration_seconds REAL,
            remote_verified INTEGER NOT NULL DEFAULT 0,
            classification TEXT NOT NULL,
            learning_status TEXT NOT NULL,
            source_url TEXT,
            source_state TEXT,
            memory_event_id INTEGER,
            claim_id INTEGER,
            memory_id INTEGER,
            provenance TEXT NOT NULL DEFAULT '{}',
            execution_outcome_status TEXT NOT NULL DEFAULT 'NOT_OBSERVED',
            execution_episode_id TEXT,
            execution_failure_memory_id TEXT,
            execution_outcome_updated_at TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(telegram_chat_id, telegram_message_id)
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_telegram_user_inputs_classification
        ON telegram_user_inputs(classification, id)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_telegram_user_inputs_file_unique
        ON telegram_user_inputs(telegram_file_unique_id)
        """
    )
    existing_columns = {
        row["name"]
        for row in connection.execute(
            "PRAGMA table_info(telegram_user_inputs)"
        ).fetchall()
    }
    additions = {
        "source_url": "TEXT",
        "source_state": "TEXT",
        "execution_outcome_status": "TEXT NOT NULL DEFAULT 'NOT_OBSERVED'",
        "execution_episode_id": "TEXT",
        "execution_failure_memory_id": "TEXT",
        "execution_outcome_updated_at": "TEXT",
    }
    for column, declaration in additions.items():
        if column not in existing_columns:
            connection.execute(
                f"ALTER TABLE telegram_user_inputs ADD COLUMN {column} {declaration}"
            )


def _row_to_record(row) -> dict[str, Any] | None:
    if row is None:
        return None
    record = dict(row)
    record["remote_verified"] = bool(record.get("remote_verified"))
    try:
        record["provenance"] = json.loads(record.get("provenance") or "{}")
    except (TypeError, json.JSONDecodeError):
        record["provenance"] = {}
    return record


def _validate_classification(value: str) -> str:
    classification = str(value or "").strip().lower()
    if classification not in VALID_CLASSIFICATIONS:
        raise ValueError(f"unsupported Telegram input classification: {classification!r}")
    return classification


def _validate_learning_status(value: str) -> str:
    status = str(value or "").strip().lower()
    if status not in VALID_LEARNING_STATUSES:
        raise ValueError(f"unsupported Telegram learning status: {status!r}")
    return status


def upsert_telegram_user_input(
    *,
    telegram_user_id: int,
    telegram_chat_id: int,
    telegram_message_id: int,
    input_kind: str,
    text_content: str,
    classification: str,
    learning_status: str = "captured",
    source_url: str | None = None,
    source_state: str | None = None,
    telegram_update_id: int | None = None,
    telegram_file_id: str | None = None,
    telegram_file_unique_id: str | None = None,
    file_name: str | None = None,
    mime_type: str | None = None,
    file_size: int | None = None,
    width: int | None = None,
    height: int | None = None,
    duration_seconds: float | None = None,
    remote_verified: bool = False,
    memory_event_id: int | None = None,
    claim_id: int | None = None,
    memory_id: int | None = None,
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if telegram_user_id <= 0 or telegram_chat_id == 0 or telegram_message_id <= 0:
        raise ValueError("Telegram provenance ids are invalid")
    kind = str(input_kind or "").strip().lower()
    if not kind:
        raise ValueError("Telegram input_kind is required")
    classification = _validate_classification(classification)
    learning_status = _validate_learning_status(learning_status)

    connection = get_connection()
    try:
        _ensure_schema(connection)
        connection.execute("BEGIN IMMEDIATE")
        existing = connection.execute(
            """
            SELECT id FROM telegram_user_inputs
            WHERE telegram_chat_id = ? AND telegram_message_id = ?
            """,
            (telegram_chat_id, telegram_message_id),
        ).fetchone()
        values = (
            telegram_update_id,
            kind,
            str(text_content or ""),
            telegram_file_id,
            telegram_file_unique_id,
            file_name,
            mime_type,
            file_size,
            width,
            height,
            duration_seconds,
            int(bool(remote_verified)),
            classification,
            learning_status,
            source_url,
            source_state,
            memory_event_id,
            claim_id,
            memory_id,
            json.dumps(provenance or {}, ensure_ascii=False, sort_keys=True),
        )
        if existing is None:
            cursor = connection.execute(
                """
                INSERT INTO telegram_user_inputs (
                    telegram_user_id,
                    telegram_chat_id,
                    telegram_message_id,
                    telegram_update_id,
                    input_kind,
                    text_content,
                    telegram_file_id,
                    telegram_file_unique_id,
                    file_name,
                    mime_type,
                    file_size,
                    width,
                    height,
                    duration_seconds,
                    remote_verified,
                    classification,
                    learning_status,
                    source_url,
                    source_state,
                    memory_event_id,
                    claim_id,
                    memory_id,
                    provenance
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    telegram_user_id,
                    telegram_chat_id,
                    telegram_message_id,
                    *values,
                ),
            )
            input_id = int(cursor.lastrowid)
        else:
            input_id = int(existing["id"])
            connection.execute(
                """
                UPDATE telegram_user_inputs
                SET telegram_update_id = ?,
                    input_kind = ?,
                    text_content = ?,
                    telegram_file_id = COALESCE(?, telegram_file_id),
                    telegram_file_unique_id = COALESCE(?, telegram_file_unique_id),
                    file_name = COALESCE(?, file_name),
                    mime_type = COALESCE(?, mime_type),
                    file_size = COALESCE(?, file_size),
                    width = COALESCE(?, width),
                    height = COALESCE(?, height),
                    duration_seconds = COALESCE(?, duration_seconds),
                    remote_verified = CASE WHEN ? = 1 THEN 1 ELSE remote_verified END,
                    classification = ?,
                    learning_status = ?,
                    source_url = COALESCE(?, source_url),
                    source_state = COALESCE(?, source_state),
                    memory_event_id = COALESCE(?, memory_event_id),
                    claim_id = COALESCE(?, claim_id),
                    memory_id = COALESCE(?, memory_id),
                    provenance = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (*values, input_id),
            )
        connection.commit()
        row = connection.execute(
            "SELECT * FROM telegram_user_inputs WHERE id = ?",
            (input_id,),
        ).fetchone()
        record = _row_to_record(row)
        if record is None:
            raise RuntimeError("Telegram user input disappeared after persistence")
        return record
    finally:
        connection.close()


def get_telegram_user_input(input_id: int) -> dict[str, Any] | None:
    if not isinstance(input_id, int) or isinstance(input_id, bool) or input_id <= 0:
        raise ValueError("Telegram input id must be positive")
    connection = get_connection()
    try:
        _ensure_schema(connection)
        row = connection.execute(
            "SELECT * FROM telegram_user_inputs WHERE id = ?",
            (input_id,),
        ).fetchone()
        return _row_to_record(row)
    finally:
        connection.close()


def get_telegram_user_input_by_message(
    *,
    telegram_chat_id: int,
    telegram_message_id: int,
) -> dict[str, Any] | None:
    connection = get_connection()
    try:
        _ensure_schema(connection)
        row = connection.execute(
            """
            SELECT * FROM telegram_user_inputs
            WHERE telegram_chat_id = ? AND telegram_message_id = ?
            LIMIT 1
            """,
            (telegram_chat_id, telegram_message_id),
        ).fetchone()
        return _row_to_record(row)
    finally:
        connection.close()


def update_telegram_source_state(
    input_id: int,
    *,
    source_state: str,
    source_url: str | None = None,
    learning_status: str | None = None,
) -> dict[str, Any]:
    if not isinstance(input_id, int) or isinstance(input_id, bool) or input_id <= 0:
        raise ValueError("Telegram input id must be positive")
    normalized_state = str(source_state or "").strip().upper()
    allowed_states = {
        "SOURCE_CANDIDATE", "FETCHED", "CLAIMS_EXTRACTED", "FACT_CHECKED",
        "VERIFIED", "CONTRADICTED", "INSUFFICIENT_EVIDENCE", "MEMORY_ELIGIBLE",
    }
    if normalized_state not in allowed_states:
        raise ValueError("invalid Telegram source state")
    normalized_learning = None
    if learning_status is not None:
        normalized_learning = _validate_learning_status(learning_status)
    connection = get_connection()
    try:
        _ensure_schema(connection)
        cursor = connection.execute(
            """UPDATE telegram_user_inputs
               SET source_state = ?,
                   source_url = COALESCE(?, source_url),
                   learning_status = COALESCE(?, learning_status),
                   updated_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (normalized_state, source_url, normalized_learning, input_id),
        )
        if cursor.rowcount != 1:
            raise ValueError("Telegram input not found")
        connection.commit()
        row = connection.execute(
            "SELECT * FROM telegram_user_inputs WHERE id = ?",
            (input_id,),
        ).fetchone()
        record = _row_to_record(row)
        if record is None:
            raise RuntimeError("Telegram input disappeared after source-state update")
        return record
    finally:
        connection.close()


def update_telegram_execution_outcome(
    input_id: int,
    *,
    status: str,
    episode_id: str,
    failure_memory_id: str | None = None,
) -> dict[str, Any]:
    normalized = str(status or "").strip().upper()
    allowed = VALID_EXECUTION_OUTCOME_STATUSES - {"NOT_OBSERVED"}
    if normalized not in allowed:
        raise ValueError("invalid Telegram execution outcome status")
    if not isinstance(input_id, int) or isinstance(input_id, bool) or input_id <= 0:
        raise ValueError("Telegram input id must be positive")
    episode_id = str(episode_id or "").strip()
    if not episode_id:
        raise ValueError("execution episode id is required")
    connection = get_connection()
    try:
        _ensure_schema(connection)
        cursor = connection.execute(
            """UPDATE telegram_user_inputs
               SET execution_outcome_status = ?,
                   execution_episode_id = ?,
                   execution_failure_memory_id = ?,
                   execution_outcome_updated_at = CURRENT_TIMESTAMP,
                   updated_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (normalized, episode_id, failure_memory_id, input_id),
        )
        if cursor.rowcount != 1:
            raise ValueError("Telegram input not found")
        connection.commit()
        row = connection.execute(
            "SELECT * FROM telegram_user_inputs WHERE id = ?",
            (input_id,),
        ).fetchone()
        record = _row_to_record(row)
        if record is None:
            raise RuntimeError("Telegram input disappeared after outcome update")
        return record
    finally:
        connection.close()


def list_recent_telegram_user_inputs(*, limit: int = 20) -> list[dict[str, Any]]:
    if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
        raise ValueError("limit must be a positive integer")
    connection = get_connection()
    try:
        _ensure_schema(connection)
        rows = connection.execute(
            """
            SELECT * FROM telegram_user_inputs
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [record for row in rows if (record := _row_to_record(row)) is not None]
    finally:
        connection.close()
