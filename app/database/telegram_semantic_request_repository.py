from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from typing import Any

from app.database.connection import get_connection


VALID_STATUSES = {
    "RECEIVED",
    "CONTEXT_BOUND",
    "READY",
    "RUNNING",
    "WAITING_FOR_PROVIDER_AVAILABILITY",
    "RESULT_PERSISTED",
    "EGRESS_PENDING",
    "DELIVERED",
    "UNKNOWN_REMOTE_STATE",
    "FAILED_PERMANENT",
}


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_schema(connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS telegram_semantic_reasoning_requests (
            request_id TEXT PRIMARY KEY,
            telegram_input_id INTEGER,
            telegram_update_id INTEGER,
            telegram_message_id INTEGER NOT NULL,
            telegram_chat_id INTEGER NOT NULL,
            human_turn_id INTEGER NOT NULL,
            thread_id TEXT,
            human_identity_id TEXT,
            human_text TEXT NOT NULL,
            human_text_sha256 TEXT NOT NULL,
            resolved_reference TEXT,
            artifact_ref TEXT,
            obsidian_note_ref TEXT,
            artifact_content_sha256 TEXT,
            normalization_state TEXT,
            source_attachment_input_id INTEGER,
            source_attachment_turn_id INTEGER,
            source_attachment_message_id INTEGER,
            context_digest TEXT NOT NULL,
            context_json TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            provider_attempts TEXT NOT NULL DEFAULT '[]',
            routing_ids TEXT NOT NULL DEFAULT '[]',
            unavailable_provider_ids TEXT NOT NULL DEFAULT '[]',
            unavailable_model_ids TEXT NOT NULL DEFAULT '[]',
            exhausted_provider_model_pairs TEXT NOT NULL DEFAULT '[]',
            exhausted_free_quota_provider_ids TEXT NOT NULL DEFAULT '[]',
            failure_class TEXT,
            provider_health_snapshot_ref TEXT,
            provider_health_snapshot_sha256 TEXT,
            next_attempt_at TEXT,
            wake_condition TEXT,
            lease_owner TEXT,
            lease_expiry TEXT,
            canonical_result_ref TEXT,
            canonical_result_json TEXT,
            outbox_ref TEXT,
            wait_message_id INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    existing_columns = {
        row["name"]
        for row in connection.execute(
            "PRAGMA table_info(telegram_semantic_reasoning_requests)"
        ).fetchall()
    }
    additions = {
        "source_attachment_input_id": "INTEGER",
        "source_attachment_turn_id": "INTEGER",
        "source_attachment_message_id": "INTEGER",
    }
    for column, declaration in additions.items():
        if column not in existing_columns:
            connection.execute(
                f"ALTER TABLE telegram_semantic_reasoning_requests "
                f"ADD COLUMN {column} {declaration}"
            )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_telegram_semantic_due
        ON telegram_semantic_reasoning_requests(status, next_attempt_at, lease_expiry)
        """
    )
    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_telegram_semantic_ingress_identity
        ON telegram_semantic_reasoning_requests(
            telegram_chat_id, telegram_message_id, human_turn_id, human_text_sha256
        )
        """
    )


def _loads(value: Any, fallback: Any) -> Any:
    if value in (None, ""):
        return fallback
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _row_to_record(row) -> dict[str, Any] | None:
    if row is None:
        return None
    record = dict(row)
    for key, fallback in (
        ("context_json", {}),
        ("provider_attempts", []),
        ("routing_ids", []),
        ("unavailable_provider_ids", []),
        ("unavailable_model_ids", []),
        ("exhausted_provider_model_pairs", []),
        ("exhausted_free_quota_provider_ids", []),
        ("canonical_result_json", None),
    ):
        record[key] = _loads(record.get(key), fallback)
    return record


def upsert_telegram_semantic_request(
    *,
    request_id: str,
    telegram_input_id: int | None,
    telegram_update_id: int | None,
    telegram_message_id: int,
    telegram_chat_id: int,
    human_turn_id: int,
    thread_id: str | None,
    human_identity_id: str | None,
    human_text: str,
    human_text_sha256: str,
    resolved_reference: str | None,
    artifact_ref: str | None,
    obsidian_note_ref: str | None,
    artifact_content_sha256: str | None,
    normalization_state: str | None,
    source_attachment_input_id: int | None = None,
    source_attachment_turn_id: int | None = None,
    source_attachment_message_id: int | None = None,
    context_digest: str = "",
    context_json: dict[str, Any],
    status: str = "RECEIVED",
    next_attempt_at: str | None = None,
    wake_condition: str | None = None,
) -> dict[str, Any]:
    normalized_status = str(status or "").strip().upper()
    if normalized_status not in VALID_STATUSES:
        raise ValueError("invalid Telegram semantic request status")
    rid = str(request_id or "").strip()
    if not rid:
        raise ValueError("request_id is required")
    now = _utcnow()
    connection = get_connection()
    try:
        _ensure_schema(connection)
        connection.execute("BEGIN IMMEDIATE")
        existing = connection.execute(
            "SELECT * FROM telegram_semantic_reasoning_requests WHERE request_id = ?",
            (rid,),
        ).fetchone()
        if existing is None:
            connection.execute(
                """
                INSERT INTO telegram_semantic_reasoning_requests (
                    request_id, telegram_input_id, telegram_update_id,
                    telegram_message_id, telegram_chat_id, human_turn_id,
                    thread_id, human_identity_id, human_text, human_text_sha256,
                    resolved_reference, artifact_ref, obsidian_note_ref,
                    artifact_content_sha256, normalization_state,
                    source_attachment_input_id, source_attachment_turn_id,
                    source_attachment_message_id, context_digest,
                    context_json, status, next_attempt_at, wake_condition,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rid, telegram_input_id, telegram_update_id,
                    int(telegram_message_id), int(telegram_chat_id), int(human_turn_id),
                    thread_id, human_identity_id, str(human_text),
                    str(human_text_sha256).lower(), resolved_reference, artifact_ref,
                    obsidian_note_ref,
                    str(artifact_content_sha256 or "").lower() or None,
                    normalization_state,
                    int(source_attachment_input_id) if source_attachment_input_id is not None else None,
                    int(source_attachment_turn_id) if source_attachment_turn_id is not None else None,
                    int(source_attachment_message_id) if source_attachment_message_id is not None else None,
                    str(context_digest).lower(),
                    json.dumps(context_json or {}, ensure_ascii=False, sort_keys=True),
                    normalized_status, next_attempt_at, wake_condition, now, now,
                ),
            )
        else:
            immutable = _row_to_record(existing) or {}
            checks = {
                "telegram_message_id": int(telegram_message_id),
                "telegram_chat_id": int(telegram_chat_id),
                "human_turn_id": int(human_turn_id),
                "human_text_sha256": str(human_text_sha256).lower(),
                "context_digest": str(context_digest).lower(),
                "source_attachment_input_id": (
                    int(source_attachment_input_id)
                    if source_attachment_input_id is not None else None
                ),
                "source_attachment_turn_id": (
                    int(source_attachment_turn_id)
                    if source_attachment_turn_id is not None else None
                ),
                "source_attachment_message_id": (
                    int(source_attachment_message_id)
                    if source_attachment_message_id is not None else None
                ),
            }
            for key, expected in checks.items():
                if expected is None:
                    continue
                if immutable.get(key) not in {None, expected}:
                    raise ValueError(f"semantic request identity collision: {key}")
            parent_updates = {
                key: expected
                for key, expected in checks.items()
                if key.startswith("source_attachment_")
                and expected is not None
                and immutable.get(key) is None
            }
            if parent_updates:
                assignments = ", ".join(f"{key}=?" for key in parent_updates)
                connection.execute(
                    f"UPDATE telegram_semantic_reasoning_requests "
                    f"SET {assignments}, updated_at=? WHERE request_id=?",
                    (*parent_updates.values(), now, rid),
                )
        connection.commit()
        row = connection.execute(
            "SELECT * FROM telegram_semantic_reasoning_requests WHERE request_id = ?",
            (rid,),
        ).fetchone()
        record = _row_to_record(row)
        if record is None:
            raise RuntimeError("semantic request disappeared after persistence")
        return record
    finally:
        connection.close()


def get_telegram_semantic_request(request_id: str) -> dict[str, Any] | None:
    connection = get_connection()
    try:
        _ensure_schema(connection)
        return _row_to_record(
            connection.execute(
                "SELECT * FROM telegram_semantic_reasoning_requests WHERE request_id = ?",
                (str(request_id),),
            ).fetchone()
        )
    finally:
        connection.close()


def update_telegram_semantic_request(
    request_id: str,
    *,
    status: str | None = None,
    attempt_count: int | None = None,
    provider_attempts: list[dict[str, Any]] | None = None,
    routing_ids: list[str] | None = None,
    unavailable_provider_ids: list[str] | None = None,
    unavailable_model_ids: list[str] | None = None,
    exhausted_provider_model_pairs: list[list[str] | tuple[str, str]] | None = None,
    exhausted_free_quota_provider_ids: list[str] | None = None,
    failure_class: str | None = None,
    provider_health_snapshot_ref: str | None = None,
    provider_health_snapshot_sha256: str | None = None,
    next_attempt_at: str | None = None,
    wake_condition: str | None = None,
    lease_owner: str | None = None,
    lease_expiry: str | None = None,
    canonical_result_ref: str | None = None,
    canonical_result_json: dict[str, Any] | None = None,
    outbox_ref: str | None = None,
    wait_message_id: int | None = None,
) -> dict[str, Any]:
    current = get_telegram_semantic_request(request_id)
    if current is None:
        raise ValueError("Telegram semantic request not found")
    next_status = str(status or current["status"]).upper()
    if next_status not in VALID_STATUSES:
        raise ValueError("invalid Telegram semantic request status")
    fields = {
        "status": next_status,
        "attempt_count": current["attempt_count"] if attempt_count is None else int(attempt_count),
        "provider_attempts": current["provider_attempts"] if provider_attempts is None else provider_attempts,
        "routing_ids": current["routing_ids"] if routing_ids is None else routing_ids,
        "unavailable_provider_ids": current["unavailable_provider_ids"] if unavailable_provider_ids is None else unavailable_provider_ids,
        "unavailable_model_ids": current["unavailable_model_ids"] if unavailable_model_ids is None else unavailable_model_ids,
        "exhausted_provider_model_pairs": current["exhausted_provider_model_pairs"] if exhausted_provider_model_pairs is None else exhausted_provider_model_pairs,
        "exhausted_free_quota_provider_ids": current["exhausted_free_quota_provider_ids"] if exhausted_free_quota_provider_ids is None else exhausted_free_quota_provider_ids,
        "failure_class": failure_class if failure_class is not None else current.get("failure_class"),
        "provider_health_snapshot_ref": provider_health_snapshot_ref if provider_health_snapshot_ref is not None else current.get("provider_health_snapshot_ref"),
        "provider_health_snapshot_sha256": provider_health_snapshot_sha256 if provider_health_snapshot_sha256 is not None else current.get("provider_health_snapshot_sha256"),
        "next_attempt_at": next_attempt_at,
        "wake_condition": wake_condition if wake_condition is not None else current.get("wake_condition"),
        "lease_owner": lease_owner,
        "lease_expiry": lease_expiry,
        "canonical_result_ref": canonical_result_ref if canonical_result_ref is not None else current.get("canonical_result_ref"),
        "canonical_result_json": canonical_result_json if canonical_result_json is not None else current.get("canonical_result_json"),
        "outbox_ref": outbox_ref if outbox_ref is not None else current.get("outbox_ref"),
        "wait_message_id": wait_message_id if wait_message_id is not None else current.get("wait_message_id"),
    }
    connection = get_connection()
    try:
        _ensure_schema(connection)
        connection.execute(
            """
            UPDATE telegram_semantic_reasoning_requests
               SET status=?, attempt_count=?, provider_attempts=?, routing_ids=?,
                   unavailable_provider_ids=?, unavailable_model_ids=?,
                   exhausted_provider_model_pairs=?,
                   exhausted_free_quota_provider_ids=?, failure_class=?,
                   provider_health_snapshot_ref=?, provider_health_snapshot_sha256=?,
                   next_attempt_at=?, wake_condition=?, lease_owner=?, lease_expiry=?,
                   canonical_result_ref=?, canonical_result_json=?, outbox_ref=?,
                   wait_message_id=?, updated_at=?
             WHERE request_id=?
            """,
            (
                fields["status"], fields["attempt_count"],
                json.dumps(fields["provider_attempts"], sort_keys=True),
                json.dumps(fields["routing_ids"], sort_keys=True),
                json.dumps(fields["unavailable_provider_ids"], sort_keys=True),
                json.dumps(fields["unavailable_model_ids"], sort_keys=True),
                json.dumps(fields["exhausted_provider_model_pairs"], sort_keys=True),
                json.dumps(fields["exhausted_free_quota_provider_ids"], sort_keys=True),
                fields["failure_class"], fields["provider_health_snapshot_ref"],
                fields["provider_health_snapshot_sha256"], fields["next_attempt_at"],
                fields["wake_condition"], fields["lease_owner"], fields["lease_expiry"],
                fields["canonical_result_ref"],
                json.dumps(fields["canonical_result_json"], ensure_ascii=False, sort_keys=True)
                if fields["canonical_result_json"] is not None else None,
                fields["outbox_ref"], fields["wait_message_id"], _utcnow(), str(request_id),
            ),
        )
        connection.commit()
    finally:
        connection.close()
    updated = get_telegram_semantic_request(request_id)
    if updated is None:
        raise RuntimeError("semantic request disappeared after update")
    return updated


def claim_due_telegram_semantic_requests(
    *,
    lease_owner: str,
    lease_seconds: int = 60,
    limit: int = 10,
    now_iso: str | None = None,
) -> list[dict[str, Any]]:
    if lease_seconds <= 0 or limit <= 0:
        raise ValueError("lease_seconds and limit must be positive")
    now = datetime.fromisoformat(now_iso) if now_iso else datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now_text = now.isoformat()
    expiry = (now + timedelta(seconds=int(lease_seconds))).isoformat()
    connection = get_connection()
    claimed_ids: list[str] = []
    try:
        _ensure_schema(connection)
        connection.execute("BEGIN IMMEDIATE")
        rows = connection.execute(
            """
            SELECT request_id
              FROM telegram_semantic_reasoning_requests
             WHERE status IN ('READY', 'WAITING_FOR_PROVIDER_AVAILABILITY')
               AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
               AND (lease_expiry IS NULL OR lease_expiry <= ?)
             ORDER BY created_at ASC
             LIMIT ?
            """,
            (now_text, now_text, int(limit)),
        ).fetchall()
        for row in rows:
            rid = str(row["request_id"])
            cursor = connection.execute(
                """
                UPDATE telegram_semantic_reasoning_requests
                   SET status='RUNNING', lease_owner=?, lease_expiry=?,
                       updated_at=?
                 WHERE request_id=?
                   AND status IN ('READY', 'WAITING_FOR_PROVIDER_AVAILABILITY')
                   AND (lease_expiry IS NULL OR lease_expiry <= ?)
                """,
                (str(lease_owner), expiry, now_text, rid, now_text),
            )
            if cursor.rowcount == 1:
                claimed_ids.append(rid)
        connection.commit()
        records: list[dict[str, Any]] = []
        for rid in claimed_ids:
            row = connection.execute(
                "SELECT * FROM telegram_semantic_reasoning_requests WHERE request_id=?",
                (rid,),
            ).fetchone()
            record = _row_to_record(row)
            if record is not None:
                records.append(record)
        return records
    finally:
        connection.close()


def promote_context_bound_semantic_requests_for_restart(
    *,
    now_iso: str | None = None,
) -> int:
    now = str(now_iso or _utcnow())
    connection = get_connection()
    try:
        _ensure_schema(connection)
        cursor = connection.execute(
            """
            UPDATE telegram_semantic_reasoning_requests
               SET status='READY',
                   next_attempt_at=?,
                   wake_condition='gateway-restart-recovery',
                   lease_owner=NULL,
                   lease_expiry=NULL,
                   updated_at=?
             WHERE status='CONTEXT_BOUND'
            """,
            (now, now),
        )
        connection.commit()
        return int(cursor.rowcount or 0)
    finally:
        connection.close()


def list_telegram_semantic_requests_for_source_input(
    source_attachment_input_id: int,
    *,
    limit: int = 50,
) -> list[dict[str, Any]]:
    connection = get_connection()
    try:
        _ensure_schema(connection)
        rows = connection.execute(
            """
            SELECT *
              FROM telegram_semantic_reasoning_requests
             WHERE source_attachment_input_id=?
             ORDER BY created_at ASC, request_id ASC
             LIMIT ?
            """,
            (
                int(source_attachment_input_id),
                max(1, min(int(limit), 200)),
            ),
        ).fetchall()
        return [
            record
            for row in rows
            if (record := _row_to_record(row)) is not None
        ]
    finally:
        connection.close()


def list_telegram_semantic_requests_for_artifact(
    *,
    telegram_chat_id: int,
    artifact_content_sha256: str,
    artifact_ref: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    digest = str(artifact_content_sha256 or "").strip().lower()
    if not digest:
        return []
    connection = get_connection()
    try:
        _ensure_schema(connection)
        params: list[Any] = [int(telegram_chat_id), digest]
        where = "telegram_chat_id=? AND artifact_content_sha256=?"
        normalized_ref = str(artifact_ref or "").strip()
        if normalized_ref:
            where += " AND artifact_ref=?"
            params.append(normalized_ref)
        params.append(max(1, min(int(limit), 200)))
        rows = connection.execute(
            f"""
            SELECT *
              FROM telegram_semantic_reasoning_requests
             WHERE {where}
             ORDER BY created_at ASC, request_id ASC
             LIMIT ?
            """,
            tuple(params),
        ).fetchall()
        return [
            record
            for row in rows
            if (record := _row_to_record(row)) is not None
        ]
    finally:
        connection.close()


def get_latest_telegram_semantic_request_for_input(
    telegram_input_id: int,
) -> dict[str, Any] | None:
    connection = get_connection()
    try:
        _ensure_schema(connection)
        row = connection.execute(
            """
            SELECT *
              FROM telegram_semantic_reasoning_requests
             WHERE telegram_input_id=?
             ORDER BY updated_at DESC, created_at DESC
             LIMIT 1
            """,
            (int(telegram_input_id),),
        ).fetchone()
        return _row_to_record(row)
    finally:
        connection.close()
