from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app.database.connection import get_connection


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _load(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def _ensure_schema(connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS telegram_conversation_states (
            conversation_id TEXT PRIMARY KEY,
            telegram_chat_id INTEGER NOT NULL UNIQUE,
            active_goal_id TEXT,
            active_project TEXT,
            active_task TEXT,
            current_subject TEXT,
            last_human_intent TEXT,
            last_human_decision TEXT,
            pending_human_review TEXT,
            pending_question TEXT,
            pending_action TEXT,
            active_artifact TEXT,
            active_run_id TEXT,
            active_stage TEXT,
            active_blocker TEXT,
            execution_status TEXT NOT NULL DEFAULT 'IDLE',
            waiting_for_human INTEGER NOT NULL DEFAULT 0,
            last_execution_result TEXT NOT NULL DEFAULT '{}',
            recent_turn_ids TEXT NOT NULL DEFAULT '[]',
            updated_at TEXT NOT NULL
        )
        """
    )
    existing_state_columns = {
        row["name"]
        for row in connection.execute(
            "PRAGMA table_info(telegram_conversation_states)"
        ).fetchall()
    }
    if "pending_action" not in existing_state_columns:
        connection.execute(
            "ALTER TABLE telegram_conversation_states ADD COLUMN pending_action TEXT"
        )

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS telegram_conversation_turns (
            turn_id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id TEXT NOT NULL,
            telegram_chat_id INTEGER NOT NULL,
            telegram_message_id INTEGER,
            role TEXT NOT NULL,
            text_content TEXT NOT NULL DEFAULT '',
            intent TEXT,
            resolved_reference TEXT,
            artifact_ref TEXT,
            run_id TEXT,
            execution_id TEXT,
            metadata TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            FOREIGN KEY(conversation_id)
                REFERENCES telegram_conversation_states(conversation_id)
                ON DELETE CASCADE
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_telegram_conversation_turns_context
        ON telegram_conversation_turns(conversation_id, turn_id DESC)
        """
    )
    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_telegram_conversation_human_message
        ON telegram_conversation_turns(telegram_chat_id, telegram_message_id, role)
        WHERE telegram_message_id IS NOT NULL
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS telegram_human_decisions (
            decision_id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id TEXT NOT NULL,
            turn_id INTEGER,
            decision_type TEXT NOT NULL,
            target_kind TEXT,
            target_ref TEXT,
            active_goal_id TEXT,
            active_task TEXT,
            artifact_ref TEXT,
            run_id TEXT,
            comment TEXT NOT NULL DEFAULT '',
            learning_correction_id TEXT,
            metadata TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            FOREIGN KEY(conversation_id)
                REFERENCES telegram_conversation_states(conversation_id)
                ON DELETE CASCADE
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_telegram_human_decisions_context
        ON telegram_human_decisions(conversation_id, decision_id DESC)
        """
    )
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS telegram_human_identities (
            human_identity_id TEXT PRIMARY KEY,
            telegram_user_id INTEGER NOT NULL UNIQUE,
            project_key TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS telegram_conversation_threads (
            thread_id TEXT PRIMARY KEY,
            human_identity_id TEXT NOT NULL,
            project_key TEXT NOT NULL,
            goal_id TEXT,
            canonical_context TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(human_identity_id, project_key),
            FOREIGN KEY(human_identity_id)
                REFERENCES telegram_human_identities(human_identity_id)
                ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS telegram_surface_sessions (
            surface_session_id TEXT PRIMARY KEY,
            thread_id TEXT NOT NULL,
            telegram_chat_id INTEGER NOT NULL UNIQUE,
            chat_type TEXT NOT NULL,
            allowed INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(thread_id)
                REFERENCES telegram_conversation_threads(thread_id)
                ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_telegram_surface_sessions_thread
        ON telegram_surface_sessions(thread_id, telegram_chat_id);

        CREATE INDEX IF NOT EXISTS idx_telegram_threads_human_project
        ON telegram_conversation_threads(human_identity_id, project_key);
        """
    )


def _project_key(value: str | None = None) -> str:
    text = str(value or "BR-no-GTA").strip()
    if not text:
        raise ValueError("project_key is required")
    return text


def resolve_telegram_human_context(
    *,
    telegram_user_id: int,
    telegram_chat_id: int,
    chat_type: str,
    project_key: str = "BR-no-GTA",
    allowed: bool,
) -> dict[str, Any]:
    user_id = int(telegram_user_id)
    chat_id = int(telegram_chat_id)
    if user_id <= 0 or chat_id == 0:
        raise ValueError("Telegram identity requires positive user_id and non-zero chat_id")
    normalized_chat_type = str(chat_type or "").strip().lower()
    if normalized_chat_type not in {"private", "group", "supergroup"}:
        raise ValueError("unsupported Telegram chat type")
    project = _project_key(project_key)
    human_identity_id = f"telegram-user:{user_id}"
    thread_id = f"human:{user_id}:project:{project.casefold()}"
    surface_session_id = f"telegram-chat:{chat_id}"
    now = _utcnow()
    with get_connection() as connection:
        _ensure_schema(connection)
        connection.execute(
            """
            INSERT INTO telegram_human_identities (
                human_identity_id, telegram_user_id, project_key, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(human_identity_id) DO UPDATE SET
                telegram_user_id = excluded.telegram_user_id,
                project_key = excluded.project_key,
                updated_at = excluded.updated_at
            """,
            (human_identity_id, user_id, project, now, now),
        )
        connection.execute(
            """
            INSERT INTO telegram_conversation_threads (
                thread_id, human_identity_id, project_key, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(thread_id) DO UPDATE SET
                human_identity_id = excluded.human_identity_id,
                project_key = excluded.project_key,
                updated_at = excluded.updated_at
            """,
            (thread_id, human_identity_id, project, now, now),
        )
        connection.execute(
            """
            INSERT INTO telegram_surface_sessions (
                surface_session_id, thread_id, telegram_chat_id, chat_type,
                allowed, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(telegram_chat_id) DO UPDATE SET
                surface_session_id = excluded.surface_session_id,
                thread_id = excluded.thread_id,
                chat_type = excluded.chat_type,
                allowed = excluded.allowed,
                updated_at = excluded.updated_at
            """,
            (
                surface_session_id, thread_id, chat_id, normalized_chat_type,
                int(bool(allowed)), now, now,
            ),
        )
        thread = connection.execute(
            "SELECT * FROM telegram_conversation_threads WHERE thread_id = ?",
            (thread_id,),
        ).fetchone()
        session = connection.execute(
            "SELECT * FROM telegram_surface_sessions WHERE telegram_chat_id = ?",
            (chat_id,),
        ).fetchone()
    thread_record = dict(thread)
    thread_record["canonical_context"] = _load(
        thread_record.get("canonical_context"), {}
    )
    session_record = dict(session)
    session_record["allowed"] = bool(session_record.get("allowed"))
    return {
        "human_identity_id": human_identity_id,
        "thread_id": thread_id,
        "surface_session_id": surface_session_id,
        "project_key": project,
        "telegram_user_id": user_id,
        "telegram_chat_id": chat_id,
        "chat_type": normalized_chat_type,
        "allowed": bool(allowed),
        "thread": thread_record,
        "surface_session": session_record,
    }


def get_shared_thread_context(thread_id: str) -> dict[str, Any]:
    identity = str(thread_id or "").strip()
    if not identity:
        raise ValueError("thread_id is required")
    with get_connection() as connection:
        _ensure_schema(connection)
        row = connection.execute(
            "SELECT * FROM telegram_conversation_threads WHERE thread_id = ?",
            (identity,),
        ).fetchone()
    if row is None:
        raise ValueError("conversation thread not found")
    record = dict(row)
    record["canonical_context"] = _load(record.get("canonical_context"), {})
    return record


def update_shared_thread_context(
    thread_id: str,
    **changes: Any,
) -> dict[str, Any]:
    allowed_fields = {
        "active_goal_id", "active_task", "current_subject", "active_artifact",
        "active_run_id", "last_human_decision", "waiting_for_human",
        "pending_question", "pending_human_review",
    }
    unknown = set(changes) - allowed_fields
    if unknown:
        raise ValueError(f"unsupported shared thread fields: {sorted(unknown)}")
    current = get_shared_thread_context(thread_id)
    context = dict(current.get("canonical_context") or {})
    for key, value in changes.items():
        if value is None:
            context.pop(key, None)
        else:
            context[key] = value
    goal_id = context.get("active_goal_id")
    now = _utcnow()
    with get_connection() as connection:
        _ensure_schema(connection)
        connection.execute(
            """
            UPDATE telegram_conversation_threads
            SET goal_id = ?, canonical_context = ?, updated_at = ?
            WHERE thread_id = ?
            """,
            (goal_id, _dump(context), now, str(thread_id)),
        )
    return get_shared_thread_context(thread_id)


def conversation_id_for_chat(telegram_chat_id: int) -> str:
    chat_id = int(telegram_chat_id)
    if chat_id == 0:
        raise ValueError("telegram_chat_id must be non-zero")
    return f"telegram:{chat_id}"


def _state_record(row) -> dict[str, Any] | None:
    if row is None:
        return None
    record = dict(row)
    record["waiting_for_human"] = bool(record.get("waiting_for_human"))
    record["last_execution_result"] = _load(record.get("last_execution_result"), {})
    record["recent_turn_ids"] = _load(record.get("recent_turn_ids"), [])
    record["pending_action"] = _load(record.get("pending_action"), None)
    return record


def get_or_create_conversation_state(telegram_chat_id: int) -> dict[str, Any]:
    conversation_id = conversation_id_for_chat(telegram_chat_id)
    now = _utcnow()
    with get_connection() as connection:
        _ensure_schema(connection)
        connection.execute(
            """
            INSERT OR IGNORE INTO telegram_conversation_states (
                conversation_id, telegram_chat_id, active_project, updated_at
            ) VALUES (?, ?, 'BR-no-GTA', ?)
            """,
            (conversation_id, int(telegram_chat_id), now),
        )
        row = connection.execute(
            "SELECT * FROM telegram_conversation_states WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()
        if row is None:
            raise RuntimeError("Telegram conversation state persistence failed")
        return _state_record(row) or {}


def update_conversation_state(
    telegram_chat_id: int,
    **changes: Any,
) -> dict[str, Any]:
    allowed = {
        "active_goal_id", "active_project", "active_task", "current_subject",
        "last_human_intent", "last_human_decision", "pending_human_review",
        "pending_question", "pending_action", "active_artifact", "active_run_id", "active_stage",
        "active_blocker", "execution_status", "waiting_for_human",
        "last_execution_result", "recent_turn_ids",
    }
    unknown = set(changes) - allowed
    if unknown:
        raise ValueError(f"unsupported conversation state fields: {sorted(unknown)}")
    state = get_or_create_conversation_state(telegram_chat_id)
    if not changes:
        return state
    values = dict(changes)
    if "waiting_for_human" in values:
        values["waiting_for_human"] = int(bool(values["waiting_for_human"]))
    for key in ("last_execution_result", "recent_turn_ids", "pending_action"):
        if key in values:
            values[key] = _dump(values[key]) if values[key] is not None else None
    values["updated_at"] = _utcnow()
    assignments = ", ".join(f"{key} = ?" for key in values)
    params = list(values.values()) + [state["conversation_id"]]
    with get_connection() as connection:
        _ensure_schema(connection)
        connection.execute(
            f"UPDATE telegram_conversation_states SET {assignments} WHERE conversation_id = ?",
            params,
        )
        row = connection.execute(
            "SELECT * FROM telegram_conversation_states WHERE conversation_id = ?",
            (state["conversation_id"],),
        ).fetchone()
        return _state_record(row) or {}


def append_conversation_turn(
    *,
    telegram_chat_id: int,
    role: str,
    text_content: str,
    telegram_message_id: int | None = None,
    intent: str | None = None,
    resolved_reference: str | None = None,
    artifact_ref: str | None = None,
    run_id: str | None = None,
    execution_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    recent_limit: int = 24,
) -> dict[str, Any]:
    state = get_or_create_conversation_state(telegram_chat_id)
    normalized_role = str(role or "").strip().upper()
    if normalized_role not in {"HUMAN", "ASSISTANT", "SYSTEM"}:
        raise ValueError("invalid Telegram conversation role")
    with get_connection() as connection:
        _ensure_schema(connection)
        if telegram_message_id is not None:
            existing = connection.execute(
                """
                SELECT * FROM telegram_conversation_turns
                WHERE telegram_chat_id = ? AND telegram_message_id = ? AND role = ?
                """,
                (int(telegram_chat_id), int(telegram_message_id), normalized_role),
            ).fetchone()
            if existing is not None:
                record = dict(existing)
                record["metadata"] = _load(record.get("metadata"), {})
                return record
        cursor = connection.execute(
            """
            INSERT INTO telegram_conversation_turns (
                conversation_id, telegram_chat_id, telegram_message_id, role,
                text_content, intent, resolved_reference, artifact_ref, run_id,
                execution_id, metadata, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                state["conversation_id"], int(telegram_chat_id),
                int(telegram_message_id) if telegram_message_id is not None else None,
                normalized_role, str(text_content or ""), intent, resolved_reference,
                artifact_ref, run_id, execution_id, _dump(metadata or {}), _utcnow(),
            ),
        )
        turn_id = int(cursor.lastrowid)
        rows = connection.execute(
            """
            SELECT turn_id FROM telegram_conversation_turns
            WHERE conversation_id = ?
            ORDER BY turn_id DESC LIMIT ?
            """,
            (state["conversation_id"], max(1, min(int(recent_limit), 50))),
        ).fetchall()
        recent = [int(row["turn_id"]) for row in reversed(rows)]
        connection.execute(
            """
            UPDATE telegram_conversation_states
            SET recent_turn_ids = ?, updated_at = ?
            WHERE conversation_id = ?
            """,
            (_dump(recent), _utcnow(), state["conversation_id"]),
        )
        row = connection.execute(
            "SELECT * FROM telegram_conversation_turns WHERE turn_id = ?",
            (turn_id,),
        ).fetchone()
        record = dict(row)
        record["metadata"] = _load(record.get("metadata"), {})
        return record


def list_recent_conversation_turns(
    telegram_chat_id: int,
    *,
    limit: int = 12,
) -> list[dict[str, Any]]:
    state = get_or_create_conversation_state(telegram_chat_id)
    with get_connection() as connection:
        _ensure_schema(connection)
        rows = connection.execute(
            """
            SELECT * FROM telegram_conversation_turns
            WHERE conversation_id = ?
            ORDER BY turn_id DESC LIMIT ?
            """,
            (state["conversation_id"], max(1, min(int(limit), 50))),
        ).fetchall()
    result = []
    for row in reversed(rows):
        record = dict(row)
        record["metadata"] = _load(record.get("metadata"), {})
        result.append(record)
    return result


def record_human_decision(
    *,
    telegram_chat_id: int,
    decision_type: str,
    comment: str,
    turn_id: int | None = None,
    target_kind: str | None = None,
    target_ref: str | None = None,
    active_goal_id: str | None = None,
    active_task: str | None = None,
    artifact_ref: str | None = None,
    run_id: str | None = None,
    learning_correction_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state = get_or_create_conversation_state(telegram_chat_id)
    normalized = str(decision_type or "").strip().upper()
    if normalized not in {"APPROVAL", "REJECTION", "FEEDBACK", "CANCEL"}:
        raise ValueError("invalid human decision type")
    with get_connection() as connection:
        _ensure_schema(connection)
        cursor = connection.execute(
            """
            INSERT INTO telegram_human_decisions (
                conversation_id, turn_id, decision_type, target_kind, target_ref,
                active_goal_id, active_task, artifact_ref, run_id, comment,
                learning_correction_id, metadata, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                state["conversation_id"], turn_id, normalized, target_kind, target_ref,
                active_goal_id, active_task, artifact_ref, run_id, str(comment or ""),
                learning_correction_id, _dump(metadata or {}), _utcnow(),
            ),
        )
        row = connection.execute(
            "SELECT * FROM telegram_human_decisions WHERE decision_id = ?",
            (int(cursor.lastrowid),),
        ).fetchone()
        record = dict(row)
        record["metadata"] = _load(record.get("metadata"), {})
        return record


def list_recent_human_decisions(
    telegram_chat_id: int,
    *,
    limit: int = 8,
) -> list[dict[str, Any]]:
    state = get_or_create_conversation_state(telegram_chat_id)
    with get_connection() as connection:
        _ensure_schema(connection)
        rows = connection.execute(
            """
            SELECT * FROM telegram_human_decisions
            WHERE conversation_id = ?
            ORDER BY decision_id DESC LIMIT ?
            """,
            (state["conversation_id"], max(1, min(int(limit), 25))),
        ).fetchall()
    result: list[dict[str, Any]] = []
    for row in reversed(rows):
        record = dict(row)
        record["metadata"] = _load(record.get("metadata"), {})
        result.append(record)
    return result
