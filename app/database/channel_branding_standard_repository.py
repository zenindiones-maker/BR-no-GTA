from __future__ import annotations

import json
from typing import Any

from app.database.connection import get_connection


REQUIRED_ASSET_TYPES = ("intro", "watermark")


def _ensure_schema(connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS channel_branding_standard (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            active INTEGER NOT NULL DEFAULT 0,
            required_asset_types TEXT NOT NULL DEFAULT '["intro","watermark"]',
            activation_source TEXT,
            activation_provenance TEXT NOT NULL DEFAULT '{}',
            activated_at TEXT,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    connection.execute(
        """
        INSERT OR IGNORE INTO channel_branding_standard (
            id, active, required_asset_types, activation_provenance
        ) VALUES (1, 0, ?, '{}')
        """,
        (json.dumps(list(REQUIRED_ASSET_TYPES)),),
    )


def _row_to_record(row) -> dict[str, Any]:
    record = dict(row)
    record["active"] = bool(record["active"])
    try:
        required = json.loads(record.get("required_asset_types") or "[]")
    except (TypeError, json.JSONDecodeError):
        required = []
    record["required_asset_types"] = tuple(str(item) for item in required)
    try:
        record["activation_provenance"] = json.loads(
            record.get("activation_provenance") or "{}"
        )
    except (TypeError, json.JSONDecodeError):
        record["activation_provenance"] = {}
    return record


def get_channel_branding_standard() -> dict[str, Any]:
    connection = get_connection()
    try:
        _ensure_schema(connection)
        connection.commit()
        row = connection.execute(
            "SELECT * FROM channel_branding_standard WHERE id = 1"
        ).fetchone()
        if row is None:
            raise RuntimeError("channel branding standard row is missing")
        return _row_to_record(row)
    finally:
        connection.close()


def activate_channel_branding_standard(
    *,
    source: str,
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source = str(source or "").strip()
    if not source:
        raise ValueError("channel branding activation source is required")
    connection = get_connection()
    try:
        _ensure_schema(connection)
        connection.execute(
            """
            UPDATE channel_branding_standard
            SET active = 1,
                required_asset_types = ?,
                activation_source = ?,
                activation_provenance = ?,
                activated_at = COALESCE(activated_at, CURRENT_TIMESTAMP),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = 1
            """,
            (
                json.dumps(list(REQUIRED_ASSET_TYPES)),
                source,
                json.dumps(provenance or {}, ensure_ascii=False, sort_keys=True),
            ),
        )
        connection.commit()
        row = connection.execute(
            "SELECT * FROM channel_branding_standard WHERE id = 1"
        ).fetchone()
        if row is None:
            raise RuntimeError("channel branding standard disappeared after activation")
        return _row_to_record(row)
    finally:
        connection.close()
