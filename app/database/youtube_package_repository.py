from __future__ import annotations

import json
from typing import Any

from app.database.connection import get_connection


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _load(value: Any, fallback: Any) -> Any:
    if value in (None, ""):
        return fallback
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _ensure_schema(connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS youtube_content_packages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            goal_id TEXT NOT NULL UNIQUE,
            content_item_id INTEGER NOT NULL UNIQUE,
            script_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            tags TEXT NOT NULL DEFAULT '[]',
            search_intent TEXT NOT NULL,
            thumbnail_concept TEXT NOT NULL,
            thumbnail_copy TEXT,
            strategy_analysis TEXT NOT NULL DEFAULT '',
            script_review TEXT NOT NULL DEFAULT '',
            seo_analysis TEXT NOT NULL DEFAULT '',
            production_analysis TEXT NOT NULL DEFAULT '',
            evidence_refs TEXT NOT NULL DEFAULT '[]',
            provenance TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'planned',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(content_item_id) REFERENCES content_items(id),
            FOREIGN KEY(script_id) REFERENCES scripts(id)
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_youtube_content_packages_status "
        "ON youtube_content_packages(status, updated_at)"
    )


def _deserialize(row) -> dict[str, Any] | None:
    if row is None:
        return None
    item = dict(row)
    item["tags"] = _load(item.get("tags"), [])
    item["evidence_refs"] = _load(item.get("evidence_refs"), [])
    item["provenance"] = _load(item.get("provenance"), {})
    return item


def upsert_youtube_content_package(record: dict[str, Any]) -> dict[str, Any]:
    connection = get_connection()
    try:
        _ensure_schema(connection)
        connection.execute(
            """
            INSERT INTO youtube_content_packages (
                goal_id, content_item_id, script_id, title, description, tags,
                search_intent, thumbnail_concept, thumbnail_copy,
                strategy_analysis, script_review, seo_analysis,
                production_analysis, evidence_refs, provenance, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(goal_id) DO UPDATE SET
                content_item_id=excluded.content_item_id,
                script_id=excluded.script_id,
                title=excluded.title,
                description=excluded.description,
                tags=excluded.tags,
                search_intent=excluded.search_intent,
                thumbnail_concept=excluded.thumbnail_concept,
                thumbnail_copy=excluded.thumbnail_copy,
                strategy_analysis=excluded.strategy_analysis,
                script_review=excluded.script_review,
                seo_analysis=excluded.seo_analysis,
                production_analysis=excluded.production_analysis,
                evidence_refs=excluded.evidence_refs,
                provenance=excluded.provenance,
                status=excluded.status,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                record["goal_id"],
                record["content_item_id"],
                record["script_id"],
                record["title"],
                record["description"],
                _dump(record.get("tags") or []),
                record["search_intent"],
                record["thumbnail_concept"],
                record.get("thumbnail_copy"),
                record.get("strategy_analysis") or "",
                record.get("script_review") or "",
                record.get("seo_analysis") or "",
                record.get("production_analysis") or "",
                _dump(record.get("evidence_refs") or []),
                _dump(record.get("provenance") or {}),
                record.get("status") or "planned",
            ),
        )
        connection.commit()
        row = connection.execute(
            "SELECT * FROM youtube_content_packages WHERE goal_id = ? LIMIT 1",
            (record["goal_id"],),
        ).fetchone()
        result = _deserialize(row)
        if result is None:
            raise RuntimeError("YouTube content package persistence failed")
        return result
    finally:
        connection.close()


def get_youtube_content_package(package_id: int) -> dict[str, Any] | None:
    connection = get_connection()
    try:
        _ensure_schema(connection)
        return _deserialize(
            connection.execute(
                "SELECT * FROM youtube_content_packages WHERE id = ? LIMIT 1",
                (package_id,),
            ).fetchone()
        )
    finally:
        connection.close()


def get_youtube_content_package_by_content_item_id(
    content_item_id: int,
) -> dict[str, Any] | None:
    connection = get_connection()
    try:
        _ensure_schema(connection)
        return _deserialize(
            connection.execute(
                "SELECT * FROM youtube_content_packages WHERE content_item_id = ? LIMIT 1",
                (content_item_id,),
            ).fetchone()
        )
    finally:
        connection.close()
