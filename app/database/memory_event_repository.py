from __future__ import annotations

import json
from typing import Any

from app.database.connection import get_connection
from app.services.memory_event_service import MemoryEvent


def insert_memory_event(
    event: MemoryEvent,
) -> int:
    """Persiste um evento histórico sem permitir sobrescrita."""

    connection = get_connection()

    try:
        cursor = connection.execute(
            """
            INSERT INTO memory_events (
                event_type,
                source_type,
                source_id,
                content,
                scope,
                occurred_at,
                observed_at,
                provenance,
                metadata
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.event_type,
                event.source_type,
                event.source_id,
                event.content,
                event.scope,
                event.occurred_at,
                event.observed_at,
                event.provenance,
                json.dumps(
                    event.metadata,
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            ),
        )

        connection.commit()

        return int(cursor.lastrowid)

    finally:
        connection.close()


def _deserialize_event(
    row: Any,
) -> dict[str, Any]:
    """Converte uma linha SQLite para o formato do domínio."""

    event = dict(row)

    metadata = event.get("metadata", "{}")

    try:
        event["metadata"] = json.loads(metadata)
    except (TypeError, json.JSONDecodeError):
        event["metadata"] = {}

    return event


def get_memory_event(
    event_id: int,
) -> dict[str, Any] | None:
    """Busca um evento histórico pelo ID."""

    connection = get_connection()

    try:
        row = connection.execute(
            """
            SELECT
                id,
                event_type,
                source_type,
                source_id,
                content,
                scope,
                occurred_at,
                observed_at,
                provenance,
                metadata,
                created_at
            FROM memory_events
            WHERE id = ?
            """,
            (event_id,),
        ).fetchone()

        if row is None:
            return None

        return _deserialize_event(row)

    finally:
        connection.close()


def list_memory_events(
    *,
    event_type: str | None = None,
    source_type: str | None = None,
    source_id: str | None = None,
    scope: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Lista eventos históricos sem alterar seu conteúdo."""

    if (
        not isinstance(limit, int)
        or isinstance(limit, bool)
        or limit <= 0
    ):
        raise ValueError(
            "limit deve ser um inteiro positivo."
        )

    connection = get_connection()

    try:
        conditions: list[str] = []
        parameters: list[Any] = []

        if event_type is not None:
            conditions.append(
                "event_type = ?"
            )
            parameters.append(event_type)

        if source_type is not None:
            conditions.append(
                "source_type = ?"
            )
            parameters.append(source_type)

        if source_id is not None:
            conditions.append(
                "source_id = ?"
            )
            parameters.append(source_id)

        if scope is not None:
            conditions.append(
                "scope = ?"
            )
            parameters.append(scope)

        query = """
            SELECT
                id,
                event_type,
                source_type,
                source_id,
                content,
                scope,
                occurred_at,
                observed_at,
                provenance,
                metadata,
                created_at
            FROM memory_events
        """

        if conditions:
            query += (
                " WHERE "
                + " AND ".join(conditions)
            )

        query += """
            ORDER BY id ASC
            LIMIT ?
        """

        parameters.append(limit)

        rows = connection.execute(
            query,
            parameters,
        ).fetchall()

        return [
            _deserialize_event(row)
            for row in rows
        ]

    finally:
        connection.close()


def list_memory_events_by_source(
    *,
    source_type: str,
    source_id: str,
) -> list[dict[str, Any]]:
    """Recupera todo o histórico de uma evidência específica."""

    connection = get_connection()

    try:
        rows = connection.execute(
            """
            SELECT
                id,
                event_type,
                source_type,
                source_id,
                content,
                scope,
                occurred_at,
                observed_at,
                provenance,
                metadata,
                created_at
            FROM memory_events
            WHERE source_type = ?
              AND source_id = ?
            ORDER BY id ASC
            """,
            (
                source_type,
                source_id,
            ),
        ).fetchall()

        return [
            _deserialize_event(row)
            for row in rows
        ]

    finally:
        connection.close()


def count_memory_events() -> int:
    """Retorna a quantidade total de eventos históricos."""

    connection = get_connection()

    try:
        row = connection.execute(
            """
            SELECT COUNT(*) AS total
            FROM memory_events
            """
        ).fetchone()

        return int(row["total"])

    finally:
        connection.close()
