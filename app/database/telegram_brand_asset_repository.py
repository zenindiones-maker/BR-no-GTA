from __future__ import annotations

import json
from typing import Any

from app.database.connection import get_connection


ASSET_TYPES = {"intro", "watermark"}


def _ensure_schema(connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS telegram_brand_assets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asset_type TEXT NOT NULL,
            telegram_file_id TEXT NOT NULL,
            telegram_file_unique_id TEXT NOT NULL,
            media_kind TEXT NOT NULL,
            file_name TEXT,
            mime_type TEXT,
            file_size INTEGER,
            width INTEGER,
            height INTEGER,
            duration_seconds REAL,
            telegram_user_id INTEGER NOT NULL,
            telegram_chat_id INTEGER NOT NULL,
            telegram_message_id INTEGER NOT NULL,
            telegram_update_id INTEGER,
            caption TEXT NOT NULL DEFAULT '',
            remote_verified INTEGER NOT NULL DEFAULT 0,
            active INTEGER NOT NULL DEFAULT 1,
            provenance TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(asset_type, telegram_chat_id, telegram_message_id)
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_telegram_brand_assets_type_active
        ON telegram_brand_assets(asset_type, active, id)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_telegram_brand_assets_unique_id
        ON telegram_brand_assets(telegram_file_unique_id)
        """
    )


def _normalize_asset_type(asset_type: str) -> str:
    value = str(asset_type or "").strip().lower()
    if value not in ASSET_TYPES:
        raise ValueError(f"unsupported brand asset type: {value!r}")
    return value


def _row_to_record(row) -> dict[str, Any] | None:
    if row is None:
        return None
    record = dict(row)
    record["remote_verified"] = bool(record["remote_verified"])
    record["active"] = bool(record["active"])
    try:
        record["provenance"] = json.loads(record.get("provenance") or "{}")
    except json.JSONDecodeError:
        record["provenance"] = {}
    return record


def upsert_active_brand_asset(
    *,
    asset_type: str,
    telegram_file_id: str,
    telegram_file_unique_id: str,
    media_kind: str,
    telegram_user_id: int,
    telegram_chat_id: int,
    telegram_message_id: int,
    telegram_update_id: int | None = None,
    file_name: str | None = None,
    mime_type: str | None = None,
    file_size: int | None = None,
    width: int | None = None,
    height: int | None = None,
    duration_seconds: float | None = None,
    caption: str = "",
    remote_verified: bool = False,
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    asset_type = _normalize_asset_type(asset_type)
    if not telegram_file_id.strip() or not telegram_file_unique_id.strip():
        raise ValueError("Telegram file identity is required")
    if telegram_user_id <= 0 or telegram_chat_id == 0 or telegram_message_id <= 0:
        raise ValueError("Telegram provenance ids are invalid")

    connection = get_connection()
    try:
        _ensure_schema(connection)
        connection.execute("BEGIN IMMEDIATE")
        existing = connection.execute(
            """
            SELECT id FROM telegram_brand_assets
            WHERE asset_type = ? AND telegram_chat_id = ? AND telegram_message_id = ?
            """,
            (asset_type, telegram_chat_id, telegram_message_id),
        ).fetchone()

        if existing is not None:
            asset_id = int(existing["id"])
            connection.execute(
                "UPDATE telegram_brand_assets SET active = 0, updated_at = CURRENT_TIMESTAMP WHERE asset_type = ? AND id <> ?",
                (asset_type, asset_id),
            )
            connection.execute(
                """
                UPDATE telegram_brand_assets
                SET active = 1,
                    remote_verified = ?,
                    provenance = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    int(remote_verified),
                    json.dumps(provenance or {}, ensure_ascii=False),
                    asset_id,
                ),
            )
        else:
            connection.execute(
                "UPDATE telegram_brand_assets SET active = 0, updated_at = CURRENT_TIMESTAMP WHERE asset_type = ?",
                (asset_type,),
            )
            cursor = connection.execute(
                """
                INSERT INTO telegram_brand_assets (
                    asset_type,
                    telegram_file_id,
                    telegram_file_unique_id,
                    media_kind,
                    file_name,
                    mime_type,
                    file_size,
                    width,
                    height,
                    duration_seconds,
                    telegram_user_id,
                    telegram_chat_id,
                    telegram_message_id,
                    telegram_update_id,
                    caption,
                    remote_verified,
                    active,
                    provenance
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                """,
                (
                    asset_type,
                    telegram_file_id,
                    telegram_file_unique_id,
                    media_kind,
                    file_name,
                    mime_type,
                    file_size,
                    width,
                    height,
                    duration_seconds,
                    telegram_user_id,
                    telegram_chat_id,
                    telegram_message_id,
                    telegram_update_id,
                    caption,
                    int(remote_verified),
                    json.dumps(provenance or {}, ensure_ascii=False),
                ),
            )
            asset_id = int(cursor.lastrowid)

        connection.commit()
        row = connection.execute(
            "SELECT * FROM telegram_brand_assets WHERE id = ?",
            (asset_id,),
        ).fetchone()
        record = _row_to_record(row)
        if record is None:
            raise RuntimeError("Brand asset disappeared after persistence")
        return record
    finally:
        connection.close()


def get_active_brand_asset(asset_type: str) -> dict[str, Any] | None:
    asset_type = _normalize_asset_type(asset_type)
    connection = get_connection()
    try:
        _ensure_schema(connection)
        row = connection.execute(
            """
            SELECT * FROM telegram_brand_assets
            WHERE asset_type = ? AND active = 1
            ORDER BY id DESC
            LIMIT 1
            """,
            (asset_type,),
        ).fetchone()
        return _row_to_record(row)
    finally:
        connection.close()


def list_active_brand_assets() -> list[dict[str, Any]]:
    connection = get_connection()
    try:
        _ensure_schema(connection)
        rows = connection.execute(
            """
            SELECT * FROM telegram_brand_assets
            WHERE active = 1
            ORDER BY asset_type ASC, id DESC
            """
        ).fetchall()
        return [record for row in rows if (record := _row_to_record(row)) is not None]
    finally:
        connection.close()
