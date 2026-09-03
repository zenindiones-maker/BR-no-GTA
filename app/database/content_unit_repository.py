from __future__ import annotations

import json
from typing import Any

from app.database.connection import get_connection


def insert_content_unit(
    *,
    content_item_id: int,
    title: str,
    unit_type: str,
    duration_seconds: float,
    media_format: str,
    script_id: int,
    idea_id: int,
    objective: str,
    hook: str,
    narration: str,
    visual_requirements: list[dict[str, Any]] | None = None,
    status: str = "ready",
    file_path: str | None = None,
) -> int:
    requirements = (
        [] if visual_requirements is None else visual_requirements
    )

    connection = get_connection()

    cursor = connection.execute(
        """
        INSERT INTO content_units (
            content_item_id,
            title,
            unit_type,
            duration_seconds,
            media_format,
            script_id,
            idea_id,
            objective,
            hook,
            narration,
            visual_requirements,
            status,
            file_path
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            content_item_id,
            title,
            unit_type,
            duration_seconds,
            media_format,
            script_id,
            idea_id,
            objective,
            hook,
            narration,
            json.dumps(
                requirements,
                ensure_ascii=False,
            ),
            status,
            file_path,
        ),
    )

    connection.commit()
    return int(cursor.lastrowid)


def _deserialize(row: Any) -> dict[str, Any]:
    result = dict(row)

    result["visual_requirements"] = json.loads(
        result["visual_requirements"]
    )

    return result


def get_content_unit(
    content_unit_id: int,
) -> dict[str, Any] | None:
    connection = get_connection()

    row = connection.execute(
        """
        SELECT *
        FROM content_units
        WHERE id = ?
        """,
        (content_unit_id,),
    ).fetchone()

    if row is None:
        return None

    return _deserialize(row)


def list_content_units(
    *,
    content_item_id: int | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    connection = get_connection()

    clauses: list[str] = []
    parameters: list[Any] = []

    if content_item_id is not None:
        clauses.append("content_item_id = ?")
        parameters.append(content_item_id)

    if status is not None:
        clauses.append("status = ?")
        parameters.append(status)

    where = (
        "WHERE " + " AND ".join(clauses)
        if clauses
        else ""
    )

    rows = connection.execute(
        f"""
        SELECT *
        FROM content_units
        {where}
        ORDER BY id ASC
        """,
        parameters,
    ).fetchall()

    return [_deserialize(row) for row in rows]


def update_content_unit_status(
    content_unit_id: int,
    status: str,
) -> bool:
    connection = get_connection()

    cursor = connection.execute(
        """
        UPDATE content_units
        SET status = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (status, content_unit_id),
    )

    connection.commit()
    return cursor.rowcount == 1


def update_content_unit_file_path(
    content_unit_id: int,
    file_path: str | None,
) -> bool:
    connection = get_connection()

    cursor = connection.execute(
        """
        UPDATE content_units
        SET file_path = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (file_path, content_unit_id),
    )

    connection.commit()
    return cursor.rowcount == 1
