from __future__ import annotations

from hashlib import sha256
import json
from typing import Any

from app.database.connection import get_connection


VALID_STATES = {"PENDING", "SENDING", "SENT", "UNKNOWN_REMOTE_STATE", "FAILED_PERMANENT"}


def _ensure_schema(connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS telegram_egress_operations (
            operation_id TEXT PRIMARY KEY,
            request_id TEXT NOT NULL,
            chat_id INTEGER NOT NULL,
            reply_to_message_id INTEGER,
            kind TEXT NOT NULL,
            sequence_number INTEGER NOT NULL,
            payload_text TEXT NOT NULL,
            payload_sha256 TEXT NOT NULL,
            state TEXT NOT NULL,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            telegram_message_id INTEGER,
            edit_message_id INTEGER,
            last_error TEXT,
            lease_owner TEXT,
            lease_expiry TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(request_id, kind, sequence_number)
        )
        """
    )
    existing_columns = {
        row["name"]
        for row in connection.execute(
            "PRAGMA table_info(telegram_egress_operations)"
        ).fetchall()
    }
    for column, declaration in {
        "lease_owner": "TEXT",
        "lease_expiry": "TEXT",
    }.items():
        if column not in existing_columns:
            connection.execute(
                f"ALTER TABLE telegram_egress_operations ADD COLUMN {column} {declaration}"
            )


def _row_to_record(row) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def upsert_telegram_egress_operation(
    *,
    operation_id: str,
    request_id: str,
    chat_id: int,
    reply_to_message_id: int | None,
    kind: str,
    sequence_number: int,
    payload_text: str,
    edit_message_id: int | None = None,
) -> dict[str, Any]:
    digest = sha256(str(payload_text).encode("utf-8")).hexdigest()
    connection = get_connection()
    try:
        _ensure_schema(connection)
        connection.execute("BEGIN IMMEDIATE")
        existing = connection.execute(
            """
            SELECT * FROM telegram_egress_operations
             WHERE request_id=? AND kind=? AND sequence_number=?
            """,
            (str(request_id), str(kind), int(sequence_number)),
        ).fetchone()
        if existing is None:
            connection.execute(
                """
                INSERT INTO telegram_egress_operations(
                    operation_id, request_id, chat_id, reply_to_message_id,
                    kind, sequence_number, payload_text, payload_sha256,
                    state, edit_message_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?)
                """,
                (
                    str(operation_id), str(request_id), int(chat_id),
                    int(reply_to_message_id) if reply_to_message_id is not None else None,
                    str(kind), int(sequence_number), str(payload_text), digest,
                    int(edit_message_id) if edit_message_id is not None else None,
                ),
            )
        else:
            row = dict(existing)
            if row["payload_sha256"] != digest:
                raise ValueError("egress identity collision with different payload")
        connection.commit()
        row = connection.execute(
            "SELECT * FROM telegram_egress_operations WHERE request_id=? AND kind=? AND sequence_number=?",
            (str(request_id), str(kind), int(sequence_number)),
        ).fetchone()
        record = _row_to_record(row)
        if record is None:
            raise RuntimeError("egress operation disappeared after persistence")
        return record
    finally:
        connection.close()


def get_telegram_egress_operation(operation_id: str) -> dict[str, Any] | None:
    connection = get_connection()
    try:
        _ensure_schema(connection)
        return _row_to_record(connection.execute(
            "SELECT * FROM telegram_egress_operations WHERE operation_id=?",
            (str(operation_id),),
        ).fetchone())
    finally:
        connection.close()


def update_telegram_egress_operation(
    operation_id: str,
    *,
    state: str,
    telegram_message_id: int | None = None,
    last_error: str | None = None,
    increment_attempt: bool = False,
) -> dict[str, Any]:
    normalized = str(state or "").upper()
    if normalized not in VALID_STATES:
        raise ValueError("invalid Telegram egress state")
    connection = get_connection()
    try:
        _ensure_schema(connection)
        cursor = connection.execute(
            """
            UPDATE telegram_egress_operations
               SET state=?,
                   telegram_message_id=COALESCE(?, telegram_message_id),
                   last_error=?,
                   attempt_count=attempt_count + ?,
                   lease_owner=CASE WHEN ? IN ('SENT','UNKNOWN_REMOTE_STATE','FAILED_PERMANENT') THEN NULL ELSE lease_owner END,
                   lease_expiry=CASE WHEN ? IN ('SENT','UNKNOWN_REMOTE_STATE','FAILED_PERMANENT') THEN NULL ELSE lease_expiry END,
                   updated_at=CURRENT_TIMESTAMP
             WHERE operation_id=?
            """,
            (
                normalized,
                int(telegram_message_id) if telegram_message_id is not None else None,
                str(last_error)[:1200] if last_error else None,
                1 if increment_attempt else 0,
                normalized,
                normalized,
                str(operation_id),
            ),
        )
        if cursor.rowcount != 1:
            raise ValueError("Telegram egress operation not found")
        connection.commit()
    finally:
        connection.close()
    updated = get_telegram_egress_operation(operation_id)
    if updated is None:
        raise RuntimeError("egress operation disappeared after update")
    return updated


def list_telegram_egress_operations_for_request(
    request_id: str,
) -> list[dict[str, Any]]:
    connection = get_connection()
    try:
        _ensure_schema(connection)
        rows = connection.execute(
            """
            SELECT * FROM telegram_egress_operations
             WHERE request_id=?
             ORDER BY sequence_number ASC, created_at ASC, operation_id ASC
            """,
            (str(request_id),),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        connection.close()


def list_pending_telegram_egress_operations(
    *,
    limit: int = 50,
) -> list[dict[str, Any]]:
    connection = get_connection()
    try:
        _ensure_schema(connection)
        rows = connection.execute(
            """
            SELECT * FROM telegram_egress_operations
             WHERE state = 'PENDING'
             ORDER BY created_at ASC, sequence_number ASC
             LIMIT ?
            """,
            (max(1, int(limit)),),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        connection.close()


def persist_semantic_result_and_egress_operations(
    *,
    request_id: str,
    canonical_result_ref: str,
    canonical_result_json: dict[str, Any],
    operations: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not operations:
        raise ValueError("at least one egress operation is required")
    from app.database.telegram_semantic_request_repository import (
        _ensure_schema as _ensure_semantic_schema,
        _row_to_record as _semantic_row_to_record,
    )

    connection = get_connection()
    try:
        _ensure_semantic_schema(connection)
        _ensure_schema(connection)
        connection.execute("BEGIN IMMEDIATE")
        request = connection.execute(
            "SELECT * FROM telegram_semantic_reasoning_requests WHERE request_id=?",
            (str(request_id),),
        ).fetchone()
        if request is None:
            raise ValueError("Telegram semantic request not found")

        operation_ids: list[str] = []
        for operation in operations:
            operation_id = str(operation["operation_id"])
            payload_text = str(operation["payload_text"])
            digest = sha256(payload_text.encode("utf-8")).hexdigest()
            existing = connection.execute(
                """
                SELECT * FROM telegram_egress_operations
                 WHERE request_id=? AND kind=? AND sequence_number=?
                """,
                (
                    str(request_id),
                    str(operation["kind"]),
                    int(operation["sequence_number"]),
                ),
            ).fetchone()
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO telegram_egress_operations(
                        operation_id, request_id, chat_id, reply_to_message_id,
                        kind, sequence_number, payload_text, payload_sha256,
                        state, edit_message_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?)
                    """,
                    (
                        operation_id,
                        str(request_id),
                        int(operation["chat_id"]),
                        (
                            int(operation["reply_to_message_id"])
                            if operation.get("reply_to_message_id") is not None
                            else None
                        ),
                        str(operation["kind"]),
                        int(operation["sequence_number"]),
                        payload_text,
                        digest,
                        (
                            int(operation["edit_message_id"])
                            if operation.get("edit_message_id") is not None
                            else None
                        ),
                    ),
                )
            else:
                existing_dict = dict(existing)
                if (
                    existing_dict["operation_id"] != operation_id
                    or existing_dict["payload_sha256"] != digest
                ):
                    raise ValueError(
                        "egress operation identity collision during result persistence"
                    )
            operation_ids.append(operation_id)

        connection.execute(
            """
            UPDATE telegram_semantic_reasoning_requests
               SET status='EGRESS_PENDING',
                   canonical_result_ref=?,
                   canonical_result_json=?,
                   outbox_ref=?,
                   failure_class=NULL,
                   next_attempt_at=NULL,
                   wake_condition=NULL,
                   lease_owner=NULL,
                   lease_expiry=NULL,
                   updated_at=?
             WHERE request_id=?
            """,
            (
                str(canonical_result_ref),
                json.dumps(
                    canonical_result_json,
                    ensure_ascii=False,
                    sort_keys=True,
                    default=str,
                ),
                operation_ids[0],
                __import__("datetime").datetime.now(
                    __import__("datetime").timezone.utc
                ).isoformat(),
                str(request_id),
            ),
        )
        connection.commit()

        request_row = connection.execute(
            "SELECT * FROM telegram_semantic_reasoning_requests WHERE request_id=?",
            (str(request_id),),
        ).fetchone()
        request_record = _semantic_row_to_record(request_row)
        if request_record is None:
            raise RuntimeError("semantic request disappeared after atomic persistence")
        op_records = []
        for operation_id in operation_ids:
            row = connection.execute(
                "SELECT * FROM telegram_egress_operations WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
            if row is None:
                raise RuntimeError("egress operation disappeared after atomic persistence")
            op_records.append(dict(row))
        return request_record, op_records
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def claim_pending_telegram_egress_operations(
    *,
    lease_owner: str,
    lease_seconds: int = 60,
    limit: int = 50,
    now_iso: str | None = None,
) -> list[dict[str, Any]]:
    from datetime import datetime, timedelta, timezone

    if lease_seconds <= 0 or limit <= 0:
        raise ValueError("lease_seconds and limit must be positive")
    now = datetime.fromisoformat(now_iso) if now_iso else datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now_text = now.isoformat()
    expiry = (now + timedelta(seconds=int(lease_seconds))).isoformat()
    connection = get_connection()
    claimed: list[str] = []
    try:
        _ensure_schema(connection)
        connection.execute("BEGIN IMMEDIATE")
        rows = connection.execute(
            """
            SELECT operation_id
              FROM telegram_egress_operations
             WHERE state='PENDING'
               AND (lease_expiry IS NULL OR lease_expiry <= ?)
             ORDER BY created_at ASC, sequence_number ASC, operation_id ASC
             LIMIT ?
            """,
            (now_text, int(limit)),
        ).fetchall()
        for row in rows:
            operation_id = str(row["operation_id"])
            cursor = connection.execute(
                """
                UPDATE telegram_egress_operations
                   SET lease_owner=?, lease_expiry=?, updated_at=CURRENT_TIMESTAMP
                 WHERE operation_id=?
                   AND state='PENDING'
                   AND (lease_expiry IS NULL OR lease_expiry <= ?)
                """,
                (str(lease_owner), expiry, operation_id, now_text),
            )
            if cursor.rowcount == 1:
                claimed.append(operation_id)
        connection.commit()
        records = []
        for operation_id in claimed:
            row = connection.execute(
                "SELECT * FROM telegram_egress_operations WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
            if row is not None:
                records.append(dict(row))
        return records
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def persist_wait_state_and_wait_outbox(
    *,
    request_id: str,
    attempt_count: int,
    provider_attempts: list[dict[str, Any]],
    routing_ids: list[str],
    unavailable_provider_ids: list[str],
    unavailable_model_ids: list[str],
    exhausted_provider_model_pairs: list[list[str] | tuple[str, str]],
    exhausted_free_quota_provider_ids: list[str],
    provider_health_snapshot_ref: str | None,
    provider_health_snapshot_sha256: str | None,
    next_attempt_at: str,
    wake_condition: str,
    operation: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    from app.database.telegram_semantic_request_repository import (
        _ensure_schema as _ensure_semantic_schema,
        _row_to_record as _semantic_row_to_record,
    )

    connection = get_connection()
    try:
        _ensure_semantic_schema(connection)
        _ensure_schema(connection)
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT * FROM telegram_semantic_reasoning_requests WHERE request_id=?",
            (str(request_id),),
        ).fetchone()
        if row is None:
            raise ValueError("Telegram semantic request not found")
        request = _semantic_row_to_record(row)
        if request is None:
            raise RuntimeError("Telegram semantic request is unreadable")
        if request["status"] != "RUNNING":
            raise PermissionError("semantic WAIT transition requires RUNNING request")

        payload_text = str(operation["payload_text"])
        digest = sha256(payload_text.encode("utf-8")).hexdigest()
        existing = connection.execute(
            """
            SELECT * FROM telegram_egress_operations
             WHERE request_id=? AND kind=? AND sequence_number=?
            """,
            (
                str(request_id),
                str(operation["kind"]),
                int(operation["sequence_number"]),
            ),
        ).fetchone()
        if existing is None:
            connection.execute(
                """
                INSERT INTO telegram_egress_operations(
                    operation_id, request_id, chat_id, reply_to_message_id,
                    kind, sequence_number, payload_text, payload_sha256,
                    state, edit_message_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?)
                """,
                (
                    str(operation["operation_id"]), str(request_id),
                    int(operation["chat_id"]),
                    int(operation["reply_to_message_id"])
                    if operation.get("reply_to_message_id") is not None else None,
                    str(operation["kind"]), int(operation["sequence_number"]),
                    payload_text, digest,
                    int(operation["edit_message_id"])
                    if operation.get("edit_message_id") is not None else None,
                ),
            )
        else:
            existing_dict = dict(existing)
            if (
                existing_dict["operation_id"] != str(operation["operation_id"])
                or existing_dict["payload_sha256"] != digest
            ):
                raise ValueError("WAIT egress identity collision")

        connection.execute(
            """
            UPDATE telegram_semantic_reasoning_requests
               SET status='WAITING_FOR_PROVIDER_AVAILABILITY',
                   attempt_count=?,
                   provider_attempts=?,
                   routing_ids=?,
                   unavailable_provider_ids=?,
                   unavailable_model_ids=?,
                   exhausted_provider_model_pairs=?,
                   exhausted_free_quota_provider_ids=?,
                   provider_health_snapshot_ref=?,
                   provider_health_snapshot_sha256=?,
                   failure_class='PROVIDER_POOL_EXHAUSTED',
                   next_attempt_at=?,
                   wake_condition=?,
                   outbox_ref=?,
                   lease_owner=NULL,
                   lease_expiry=NULL,
                   updated_at=CURRENT_TIMESTAMP
             WHERE request_id=? AND status='RUNNING'
            """,
            (
                int(attempt_count),
                json.dumps(provider_attempts, ensure_ascii=False, sort_keys=True),
                json.dumps(routing_ids, ensure_ascii=False, sort_keys=True),
                json.dumps(unavailable_provider_ids, ensure_ascii=False, sort_keys=True),
                json.dumps(unavailable_model_ids, ensure_ascii=False, sort_keys=True),
                json.dumps(exhausted_provider_model_pairs, ensure_ascii=False, sort_keys=True),
                json.dumps(exhausted_free_quota_provider_ids, ensure_ascii=False, sort_keys=True),
                provider_health_snapshot_ref,
                provider_health_snapshot_sha256,
                str(next_attempt_at), str(wake_condition),
                str(operation["operation_id"]), str(request_id),
            ),
        )
        connection.commit()
        request_row = connection.execute(
            "SELECT * FROM telegram_semantic_reasoning_requests WHERE request_id=?",
            (str(request_id),),
        ).fetchone()
        op_row = connection.execute(
            "SELECT * FROM telegram_egress_operations WHERE operation_id=?",
            (str(operation["operation_id"]),),
        ).fetchone()
        request_record = _semantic_row_to_record(request_row)
        if request_record is None or op_row is None:
            raise RuntimeError("atomic WAIT persistence disappeared")
        return request_record, dict(op_row)
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
