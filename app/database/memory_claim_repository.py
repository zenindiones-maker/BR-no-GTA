from __future__ import annotations

from typing import Any

from app.database.connection import get_connection
from app.services.memory_claim_service import (
    MemoryClaim,
    VALID_CLAIM_STATUSES,
)


def insert_memory_claim(
    claim: MemoryClaim,
) -> int:
    """Persiste um claim e retorna seu ID."""

    connection = get_connection()

    try:
        cursor = connection.execute(
            """
            INSERT INTO memory_claims (
                claim,
                claim_type,
                confidence,
                status,
                scope,
                valid_at,
                invalid_at,
                extraction_method
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                claim.claim,
                claim.claim_type,
                claim.confidence,
                claim.status,
                claim.scope,
                claim.valid_at,
                claim.invalid_at,
                claim.extraction_method,
            ),
        )

        connection.commit()

        return int(cursor.lastrowid)

    finally:
        connection.close()


def _deserialize_claim(
    row: Any,
) -> dict[str, Any]:
    """Converte uma linha SQLite em dicionário."""

    return {
        "id": row["id"],
        "claim": row["claim"],
        "claim_type": row["claim_type"],
        "confidence": row["confidence"],
        "status": row["status"],
        "scope": row["scope"],
        "valid_at": row["valid_at"],
        "invalid_at": row["invalid_at"],
        "extraction_method": row["extraction_method"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def get_memory_claim(
    claim_id: int,
) -> dict[str, Any] | None:
    """Busca um claim pelo ID."""

    connection = get_connection()

    try:
        row = connection.execute(
            """
            SELECT
                id,
                claim,
                claim_type,
                confidence,
                status,
                scope,
                valid_at,
                invalid_at,
                extraction_method,
                created_at,
                updated_at
            FROM memory_claims
            WHERE id = ?
            """,
            (claim_id,),
        ).fetchone()

        if row is None:
            return None

        return _deserialize_claim(row)

    finally:
        connection.close()


def list_memory_claims(
    *,
    claim_type: str | None = None,
    scope: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Lista claims persistidos com filtros opcionais."""

    if (
        not isinstance(limit, int)
        or isinstance(limit, bool)
        or limit <= 0
    ):
        raise ValueError(
            "limit deve ser um inteiro positivo."
        )

    if status is not None and status not in VALID_CLAIM_STATUSES:
        raise ValueError(
            f"Status de claim inválido: {status}"
        )

    connection = get_connection()

    try:
        conditions: list[str] = []
        parameters: list[Any] = []

        if claim_type is not None:
            conditions.append("claim_type = ?")
            parameters.append(claim_type)

        if scope is not None:
            conditions.append("scope = ?")
            parameters.append(scope)

        if status is not None:
            conditions.append("status = ?")
            parameters.append(status)

        where_clause = ""

        if conditions:
            where_clause = (
                "WHERE "
                + " AND ".join(conditions)
            )

        rows = connection.execute(
            f"""
            SELECT
                id,
                claim,
                claim_type,
                confidence,
                status,
                scope,
                valid_at,
                invalid_at,
                extraction_method,
                created_at,
                updated_at
            FROM memory_claims
            {where_clause}
            ORDER BY id ASC
            LIMIT ?
            """,
            (*parameters, limit),
        ).fetchall()

        return [
            _deserialize_claim(row)
            for row in rows
        ]

    finally:
        connection.close()


def update_memory_claim_status(
    claim_id: int,
    status: str,
) -> bool:
    """
    Atualiza somente o status do claim.

    O conteúdo do claim permanece imutável.
    """

    if status not in VALID_CLAIM_STATUSES:
        raise ValueError(
            f"Status de claim inválido: {status}"
        )

    connection = get_connection()

    try:
        cursor = connection.execute(
            """
            UPDATE memory_claims
            SET
                status = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                status,
                claim_id,
            ),
        )

        connection.commit()

        return cursor.rowcount == 1

    finally:
        connection.close()
