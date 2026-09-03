from __future__ import annotations

from typing import Any

from app.database.connection import get_connection


def insert_memory_record_claim(
    *,
    memory_record_id: int,
    claim_id: int,
) -> int:
    """Persiste uma relação memória semântica ↔ Claim."""

    if (
        not isinstance(memory_record_id, int)
        or isinstance(memory_record_id, bool)
        or memory_record_id <= 0
    ):
        raise ValueError(
            "memory_record_id deve ser um inteiro positivo."
        )

    if (
        not isinstance(claim_id, int)
        or isinstance(claim_id, bool)
        or claim_id <= 0
    ):
        raise ValueError(
            "claim_id deve ser um inteiro positivo."
        )

    connection = get_connection()

    try:
        cursor = connection.execute(
            """
            INSERT INTO memory_record_claims (
                memory_record_id,
                claim_id
            )
            VALUES (?, ?)
            """,
            (
                memory_record_id,
                claim_id,
            ),
        )

        connection.commit()

        return int(cursor.lastrowid)

    finally:
        connection.close()


def get_memory_record_claim(
    relation_id: int,
) -> dict[str, Any] | None:
    """Busca uma relação memória semântica ↔ Claim pelo ID."""

    connection = get_connection()

    try:
        row = connection.execute(
            """
            SELECT
                id,
                memory_record_id,
                claim_id,
                created_at
            FROM memory_record_claims
            WHERE id = ?
            """,
            (relation_id,),
        ).fetchone()

        if row is None:
            return None

        return {
            "id": row["id"],
            "memory_record_id": row["memory_record_id"],
            "claim_id": row["claim_id"],
            "created_at": row["created_at"],
        }

    finally:
        connection.close()


def list_memory_record_claims(
    *,
    memory_record_id: int | None = None,
    claim_id: int | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Lista relações de linhagem com filtros opcionais."""

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

        if memory_record_id is not None:
            if (
                not isinstance(memory_record_id, int)
                or isinstance(memory_record_id, bool)
                or memory_record_id <= 0
            ):
                raise ValueError(
                    "memory_record_id deve ser um inteiro positivo."
                )

            conditions.append("memory_record_id = ?")
            parameters.append(memory_record_id)

        if claim_id is not None:
            if (
                not isinstance(claim_id, int)
                or isinstance(claim_id, bool)
                or claim_id <= 0
            ):
                raise ValueError(
                    "claim_id deve ser um inteiro positivo."
                )

            conditions.append("claim_id = ?")
            parameters.append(claim_id)

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
                memory_record_id,
                claim_id,
                created_at
            FROM memory_record_claims
            {where_clause}
            ORDER BY id ASC
            LIMIT ?
            """,
            (*parameters, limit),
        ).fetchall()

        return [
            {
                "id": row["id"],
                "memory_record_id": row["memory_record_id"],
                "claim_id": row["claim_id"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    finally:
        connection.close()


def list_claims_for_memory_record(
    memory_record_id: int,
    *,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Retorna os Claims que originaram uma memória semântica."""

    return list_memory_record_claims(
        memory_record_id=memory_record_id,
        limit=limit,
    )


def list_memory_records_for_claim(
    claim_id: int,
    *,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Retorna as memórias semânticas derivadas de um Claim."""

    return list_memory_record_claims(
        claim_id=claim_id,
        limit=limit,
    )
