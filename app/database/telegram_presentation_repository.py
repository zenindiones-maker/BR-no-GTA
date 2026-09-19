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
            canonical_lines INTEGER NOT NULL DEFAULT 0,
            presented_lines INTEGER NOT NULL DEFAULT 0,
            canonical_internal_id_mentions INTEGER NOT NULL DEFAULT 0,
            presented_internal_id_mentions INTEGER NOT NULL DEFAULT 0,
            conclusion_present INTEGER NOT NULL DEFAULT 0,
            next_action_present INTEGER NOT NULL DEFAULT 0,
            material_warnings_preserved INTEGER NOT NULL DEFAULT 1,
            evidence_access_present INTEGER NOT NULL DEFAULT 0,
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
    existing = {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(telegram_presentation_audits)").fetchall()
    }
    for name, ddl in {
        "canonical_lines": "INTEGER NOT NULL DEFAULT 0",
        "presented_lines": "INTEGER NOT NULL DEFAULT 0",
        "canonical_internal_id_mentions": "INTEGER NOT NULL DEFAULT 0",
        "presented_internal_id_mentions": "INTEGER NOT NULL DEFAULT 0",
        "conclusion_present": "INTEGER NOT NULL DEFAULT 0",
        "next_action_present": "INTEGER NOT NULL DEFAULT 0",
        "material_warnings_preserved": "INTEGER NOT NULL DEFAULT 1",
        "evidence_access_present": "INTEGER NOT NULL DEFAULT 0",
    }.items():
        if name not in existing:
            connection.execute(
                f"ALTER TABLE telegram_presentation_audits ADD COLUMN {name} {ddl}"
            )


def _row(row) -> dict[str, Any] | None:
    if row is None:
        return None
    result = dict(row)
    for key in (
        "canonical_unchanged",
        "conclusion_present",
        "next_action_present",
        "material_warnings_preserved",
        "evidence_access_present",
    ):
        result[key] = bool(result.get(key))
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
    canonical_lines = int(presentation.get("canonical_lines") or 0)
    presented_lines = int(presentation.get("presented_lines") or 0)
    canonical_internal_id_mentions = int(
        presentation.get("canonical_internal_id_mentions") or 0
    )
    presented_internal_id_mentions = int(
        presentation.get("presented_internal_id_mentions") or 0
    )
    conclusion_present = bool(presentation.get("conclusion_present"))
    next_action_present = bool(presentation.get("next_action_present"))
    material_warnings_preserved = bool(
        presentation.get("material_warnings_preserved", True)
    )
    evidence_access_present = bool(presentation.get("evidence_access_present"))
    if min(
        canonical_chars,
        presented_chars,
        canonical_lines,
        presented_lines,
        canonical_internal_id_mentions,
        presented_internal_id_mentions,
    ) < 0:
        raise ValueError("presentation audit metrics must be non-negative")
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
                routing_id, authorization_id, canonical_lines, presented_lines,
                canonical_internal_id_mentions, presented_internal_id_mentions,
                conclusion_present, next_action_present,
                material_warnings_preserved, evidence_access_present
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                telegram_input_id, mode, surface, canonical_sha256,
                canonical_chars, presented_chars, reply_sha256,
                1, authority, routing_id, authorization_id,
                canonical_lines, presented_lines,
                canonical_internal_id_mentions, presented_internal_id_mentions,
                int(conclusion_present), int(next_action_present),
                int(material_warnings_preserved), int(evidence_access_present),
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
            "canonical_lines": canonical_lines,
            "presented_lines": presented_lines,
            "canonical_internal_id_mentions": canonical_internal_id_mentions,
            "presented_internal_id_mentions": presented_internal_id_mentions,
            "conclusion_present": conclusion_present,
            "next_action_present": next_action_present,
            "material_warnings_preserved": material_warnings_preserved,
            "evidence_access_present": evidence_access_present,
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
