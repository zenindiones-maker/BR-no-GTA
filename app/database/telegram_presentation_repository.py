from __future__ import annotations

from hashlib import sha256
from typing import Any

from app.database.connection import get_connection


def _ensure_schema(connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS telegram_presentation_audits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_input_id INTEGER NOT NULL,
            presentation_mode TEXT NOT NULL,
            surface TEXT NOT NULL,
            canonical_sha256 TEXT NOT NULL,
            canonical_chars INTEGER NOT NULL,
            presented_chars INTEGER NOT NULL,
            reply_sha256 TEXT NOT NULL,
            canonical_unchanged INTEGER NOT NULL,
            authority TEXT NOT NULL,
            routing_id TEXT NOT NULL,
            authorization_id TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_telegram_presentation_input
        ON telegram_presentation_audits(telegram_input_id, id DESC)
        """
    )


def _row(row) -> dict[str, Any] | None:
    if row is None:
        return None
    result = dict(row)
    result["canonical_unchanged"] = bool(result.get("canonical_unchanged"))
    return result


def record_telegram_presentation_audit(
    *,
    telegram_input_id: int,
    presentation: dict[str, Any],
    reply_text: str,
) -> dict[str, Any]:
    if not isinstance(telegram_input_id, int) or isinstance(telegram_input_id, bool) or telegram_input_id <= 0:
        raise ValueError("telegram_input_id must be positive")
    mode = str(presentation.get("mode") or "").strip()
    surface = str(presentation.get("surface") or "").strip()
    canonical_sha256 = str(presentation.get("canonical_sha256") or "").strip()
    authority = str(presentation.get("authority") or "").strip()
    routing_id = str(presentation.get("routing_id") or "").strip()
    authorization_id = str(presentation.get("authorization_id") or "").strip()
    if not all((mode, surface, canonical_sha256, authority, routing_id, authorization_id)):
        raise ValueError("presentation audit requires complete Harness provenance")
    canonical_chars = int(presentation.get("canonical_chars"))
    presented_chars = int(presentation.get("presented_chars"))
    canonical_unchanged = bool(presentation.get("canonical_unchanged"))
    if canonical_chars < 0 or presented_chars < 0:
        raise ValueError("presentation audit lengths must be non-negative")
    if not canonical_unchanged:
        raise PermissionError("presentation audit refuses mutated canonical result")
    reply_sha256 = sha256(str(reply_text).encode("utf-8")).hexdigest()

    connection = get_connection()
    try:
        _ensure_schema(connection)
        connection.execute(
            """
            INSERT OR IGNORE INTO telegram_presentation_audits (
                telegram_input_id, presentation_mode, surface,
                canonical_sha256, canonical_chars, presented_chars,
                reply_sha256, canonical_unchanged, authority,
                routing_id, authorization_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                telegram_input_id, mode, surface, canonical_sha256,
                canonical_chars, presented_chars, reply_sha256,
                1, authority, routing_id, authorization_id,
            ),
        )
        connection.commit()
        row = connection.execute(
            """
            SELECT * FROM telegram_presentation_audits
            WHERE authorization_id = ?
            """,
            (authorization_id,),
        ).fetchone()
        result = _row(row)
        if result is None:
            raise RuntimeError("presentation audit persistence failed")
        expected = {
            "telegram_input_id": telegram_input_id,
            "presentation_mode": mode,
            "surface": surface,
            "canonical_sha256": canonical_sha256,
            "canonical_chars": canonical_chars,
            "presented_chars": presented_chars,
            "reply_sha256": reply_sha256,
            "canonical_unchanged": True,
            "authority": authority,
            "routing_id": routing_id,
            "authorization_id": authorization_id,
        }
        for key, value in expected.items():
            if result.get(key) != value:
                raise RuntimeError("presentation audit authorization collision")
        return result
    finally:
        connection.close()


def get_latest_telegram_presentation_audit(
    telegram_input_id: int,
) -> dict[str, Any] | None:
    connection = get_connection()
    try:
        _ensure_schema(connection)
        row = connection.execute(
            """
            SELECT * FROM telegram_presentation_audits
            WHERE telegram_input_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (telegram_input_id,),
        ).fetchone()
        return _row(row)
    finally:
        connection.close()


def list_recent_telegram_presentation_audits(
    *,
    limit: int = 50,
) -> list[dict[str, Any]]:
    if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
        raise ValueError("limit must be positive")
    connection = get_connection()
    try:
        _ensure_schema(connection)
        rows = connection.execute(
            """
            SELECT * FROM telegram_presentation_audits
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [item for row in rows if (item := _row(row)) is not None]
    finally:
        connection.close()
