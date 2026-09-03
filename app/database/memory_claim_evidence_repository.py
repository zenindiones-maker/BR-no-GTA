from __future__ import annotations

from typing import Any

from app.database.connection import get_connection
from app.services.memory_claim_evidence_service import (
    MemoryClaimEvidence,
    VALID_EVIDENCE_ROLES,
)


def insert_memory_claim_evidence(
    evidence: MemoryClaimEvidence,
) -> int:
    """Persiste uma relação Claim ↔ Evidence."""

    connection = get_connection()

    try:
        cursor = connection.execute(
            """
            INSERT INTO memory_claim_evidence (
                claim_id,
                event_id,
                evidence_role,
                weight
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                evidence.claim_id,
                evidence.event_id,
                evidence.evidence_role,
                evidence.weight,
            ),
        )

        connection.commit()

        return int(cursor.lastrowid)

    finally:
        connection.close()


def _deserialize_claim_evidence(
    row: Any,
) -> dict[str, Any]:
    """Converte uma relação SQLite em dicionário."""

    return {
        "id": row["id"],
        "claim_id": row["claim_id"],
        "event_id": row["event_id"],
        "evidence_role": row["evidence_role"],
        "weight": row["weight"],
        "created_at": row["created_at"],
    }


def get_memory_claim_evidence(
    relation_id: int,
) -> dict[str, Any] | None:
    """Busca uma relação Claim ↔ Evidence pelo ID."""

    connection = get_connection()

    try:
        row = connection.execute(
            """
            SELECT
                id,
                claim_id,
                event_id,
                evidence_role,
                weight,
                created_at
            FROM memory_claim_evidence
            WHERE id = ?
            """,
            (relation_id,),
        ).fetchone()

        if row is None:
            return None

        return _deserialize_claim_evidence(row)

    finally:
        connection.close()


def list_memory_claim_evidence(
    *,
    claim_id: int | None = None,
    event_id: int | None = None,
    evidence_role: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Lista relações Claim ↔ Evidence com filtros opcionais."""

    if (
        not isinstance(limit, int)
        or isinstance(limit, bool)
        or limit <= 0
    ):
        raise ValueError(
            "limit deve ser um inteiro positivo."
        )

    if evidence_role is not None:
        if evidence_role not in VALID_EVIDENCE_ROLES:
            raise ValueError(
                f"Role de evidência inválida: {evidence_role}"
            )

    connection = get_connection()

    try:
        conditions: list[str] = []
        parameters: list[Any] = []

        if claim_id is not None:
            conditions.append("claim_id = ?")
            parameters.append(claim_id)

        if event_id is not None:
            conditions.append("event_id = ?")
            parameters.append(event_id)

        if evidence_role is not None:
            conditions.append("evidence_role = ?")
            parameters.append(evidence_role)

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
                claim_id,
                event_id,
                evidence_role,
                weight,
                created_at
            FROM memory_claim_evidence
            {where_clause}
            ORDER BY id ASC
            LIMIT ?
            """,
            (*parameters, limit),
        ).fetchall()

        return [
            _deserialize_claim_evidence(row)
            for row in rows
        ]

    finally:
        connection.close()


def list_memory_claim_evidence_for_claim(
    claim_id: int,
    *,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Retorna todas as evidências associadas a um Claim."""

    return list_memory_claim_evidence(
        claim_id=claim_id,
        limit=limit,
    )


def list_memory_claim_evidence_for_event(
    event_id: int,
    *,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Retorna todos os Claims associados a uma evidência."""

    return list_memory_claim_evidence(
        event_id=event_id,
        limit=limit,
    )
