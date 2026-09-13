from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.database.connection import get_connection


GTA6_GOAL_TYPES = {
    "NEWS",
    "GAMEPLAY",
    "EVERGREEN",
}

GTA6_GOAL_STATUSES = {
    "DISCOVERED",
    "SELECTED",
    "ACTIVE",
    "RESEARCHING",
    "SCRIPTING",
    "PLANNING",
    "EDITING",
    "RENDERING",
    "READY",
    "PUBLISHED",
    "COMPLETED",
    "BLOCKED",
    "FAILED",
    "CANCELLED",
}

GTA6_GOAL_PRIORITIES = {
    "LOW",
    "MEDIUM",
    "HIGH",
}

GTA6_GOAL_STAGES = {
    "DISCOVERY",
    "RESEARCH",
    "SCRIPT",
    "SCRIPT_SPEC",
    "CONTENT_ITEM",
    "PRODUCTION_PLAN",
    "VIDEO",
    "EDITING",
    "RENDER",
    "YOUTUBE_UPLOAD",
    "YOUTUBE_PUBLISH",
    "COMPLETE",
}


def _validate_goal_id(goal_id: str) -> str:
    if not isinstance(goal_id, str) or not goal_id.strip():
        raise ValueError("goal_id must be a non-empty string")
    return goal_id.strip()


def _validate_goal_type(goal_type: str) -> str:
    if goal_type not in GTA6_GOAL_TYPES:
        raise ValueError(
            f"goal_type must be one of {sorted(GTA6_GOAL_TYPES)}"
        )
    return goal_type


def _validate_status(status: str) -> str:
    if status not in GTA6_GOAL_STATUSES:
        raise ValueError(
            f"status must be one of {sorted(GTA6_GOAL_STATUSES)}"
        )
    return status


def _validate_priority(priority: str) -> str:
    if priority not in GTA6_GOAL_PRIORITIES:
        raise ValueError(
            f"priority must be one of {sorted(GTA6_GOAL_PRIORITIES)}"
        )
    return priority


def _validate_stage(stage: str) -> str:
    if stage not in GTA6_GOAL_STAGES:
        raise ValueError(
            f"current_stage must be one of {sorted(GTA6_GOAL_STAGES)}"
        )
    return stage


def create_gta6_goal(
    *,
    goal_type: str,
    topic: str,
    priority: str = "MEDIUM",
    opportunity_score: float = 0.0,
    target_duration: str | None = None,
    status: str = "DISCOVERED",
    current_stage: str = "DISCOVERY",
    goal_id: str | None = None,
) -> dict[str, Any]:
    """Cria e persiste um Goal do GTA6."""

    _validate_goal_type(goal_type)
    _validate_status(status)
    _validate_priority(priority)
    _validate_stage(current_stage)

    if not isinstance(topic, str) or not topic.strip():
        raise ValueError("topic must be a non-empty string")

    if (
        isinstance(opportunity_score, bool)
        or not isinstance(opportunity_score, (int, float))
    ):
        raise ValueError("opportunity_score must be numeric")

    if opportunity_score < 0:
        raise ValueError("opportunity_score must be greater than or equal to zero")

    if target_duration is not None:
        if not isinstance(target_duration, str) or not target_duration.strip():
            raise ValueError(
                "target_duration must be a non-empty string or None"
            )

    if goal_id is None:
        goal_id = str(uuid4())
    else:
        goal_id = _validate_goal_id(goal_id)

    connection = get_connection()
    try:
        connection.execute(
            """
            INSERT INTO gta6_goals (
                goal_id,
                goal_type,
                topic,
                status,
                priority,
                opportunity_score,
                target_duration,
                current_stage
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                goal_id,
                goal_type,
                topic.strip(),
                status,
                priority,
                float(opportunity_score),
                (
                    target_duration.strip()
                    if target_duration is not None
                    else None
                ),
                current_stage,
            ),
        )

        connection.commit()

        row = connection.execute(
            """
            SELECT
                goal_id,
                goal_type,
                topic,
                status,
                priority,
                opportunity_score,
                target_duration,
                current_stage,
                last_published_at,
                created_at,
                updated_at
            FROM gta6_goals
            WHERE goal_id = ?
            LIMIT 1
            """,
            (goal_id,),
        ).fetchone()

        if row is None:
            raise RuntimeError("GTA6 Goal was not persisted")

        return dict(row)
    finally:
        connection.close()


def get_gta6_goal(
    goal_id: str,
) -> dict[str, Any] | None:
    """Retorna um Goal pelo UUID."""

    goal_id = _validate_goal_id(goal_id)

    connection = get_connection()
    try:
        row = connection.execute(
            """
            SELECT
                goal_id,
                goal_type,
                topic,
                status,
                priority,
                opportunity_score,
                target_duration,
                current_stage,
                last_published_at,
                created_at,
                updated_at
            FROM gta6_goals
            WHERE goal_id = ?
            LIMIT 1
            """,
            (goal_id,),
        ).fetchone()

        return dict(row) if row else None
    finally:
        connection.close()


def get_active_gta6_goal(
    *,
    topic: str | None = None,
) -> dict[str, Any] | None:
    """
    Retorna o Goal ativo mais recente.

    Se topic for informado, restringe a busca ao tópico.
    """

    if topic is not None:
        if not isinstance(topic, str) or not topic.strip():
            raise ValueError("topic must be a non-empty string or None")

    connection = get_connection()
    try:
        query = """
            SELECT
                goal_id,
                goal_type,
                topic,
                status,
                priority,
                opportunity_score,
                target_duration,
                current_stage,
                last_published_at,
                created_at,
                updated_at
            FROM gta6_goals
            WHERE status IN (
                'SELECTED',
                'ACTIVE',
                'RESEARCHING',
                'SCRIPTING',
                'PLANNING',
                'EDITING',
                'RENDERING',
                'READY'
            )
        """

        parameters: list[Any] = []

        if topic is not None:
            query += " AND topic = ?"
            parameters.append(topic.strip())

        query += """
            ORDER BY
                CASE priority
                    WHEN 'HIGH' THEN 3
                    WHEN 'MEDIUM' THEN 2
                    WHEN 'LOW' THEN 1
                    ELSE 0
                END DESC,
                updated_at DESC,
                created_at DESC
            LIMIT 1
        """

        row = connection.execute(query, parameters).fetchone()

        return dict(row) if row else None
    finally:
        connection.close()


def list_gta6_goals(
    *,
    status: str | None = None,
    goal_type: str | None = None,
    topic: str | None = None,
) -> list[dict[str, Any]]:
    """Lista Goals com filtros opcionais."""

    if status is not None:
        _validate_status(status)

    if goal_type is not None:
        _validate_goal_type(goal_type)

    if topic is not None:
        if not isinstance(topic, str) or not topic.strip():
            raise ValueError("topic must be a non-empty string or None")

    connection = get_connection()
    try:
        query = """
            SELECT
                goal_id,
                goal_type,
                topic,
                status,
                priority,
                opportunity_score,
                target_duration,
                current_stage,
                last_published_at,
                created_at,
                updated_at
            FROM gta6_goals
        """

        conditions: list[str] = []
        parameters: list[Any] = []

        if status is not None:
            conditions.append("status = ?")
            parameters.append(status)

        if goal_type is not None:
            conditions.append("goal_type = ?")
            parameters.append(goal_type)

        if topic is not None:
            conditions.append("topic = ?")
            parameters.append(topic.strip())

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += """
            ORDER BY
                opportunity_score DESC,
                updated_at DESC,
                created_at DESC
        """

        rows = connection.execute(
            query,
            parameters,
        ).fetchall()

        return [dict(row) for row in rows]
    finally:
        connection.close()


def update_gta6_goal_status(
    *,
    goal_id: str,
    status: str,
) -> bool:
    """Atualiza somente o status operacional do Goal."""

    goal_id = _validate_goal_id(goal_id)
    _validate_status(status)

    connection = get_connection()
    try:
        cursor = connection.execute(
            """
            UPDATE gta6_goals
            SET
                status = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE goal_id = ?
            """,
            (status, goal_id),
        )

        connection.commit()
        return cursor.rowcount > 0
    finally:
        connection.close()


def update_gta6_goal_stage(
    *,
    goal_id: str,
    current_stage: str,
) -> bool:
    """Atualiza somente o estágio operacional do Goal."""

    goal_id = _validate_goal_id(goal_id)
    _validate_stage(current_stage)

    connection = get_connection()
    try:
        cursor = connection.execute(
            """
            UPDATE gta6_goals
            SET
                current_stage = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE goal_id = ?
            """,
            (current_stage, goal_id),
        )

        connection.commit()
        return cursor.rowcount > 0
    finally:
        connection.close()


def attach_gta6_goal_claim(
    *,
    goal_id: str,
    claim_id: int,
) -> bool:
    """Vincula uma claim de memória ao Goal."""

    goal_id = _validate_goal_id(goal_id)

    if not isinstance(claim_id, int) or isinstance(claim_id, bool):
        raise ValueError("claim_id must be an integer")

    if claim_id <= 0:
        raise ValueError("claim_id must be greater than zero")

    connection = get_connection()
    try:
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO gta6_goal_claims (
                goal_id,
                claim_id
            )
            VALUES (?, ?)
            """,
            (goal_id, claim_id),
        )

        connection.commit()
        return cursor.rowcount > 0
    finally:
        connection.close()


def list_gta6_goal_claims(
    goal_id: str,
) -> list[dict[str, Any]]:
    """Lista as claims vinculadas a um Goal."""

    goal_id = _validate_goal_id(goal_id)

    connection = get_connection()
    try:
        rows = connection.execute(
            """
            SELECT
                goal_id,
                claim_id,
                created_at
            FROM gta6_goal_claims
            WHERE goal_id = ?
            ORDER BY claim_id ASC
            """,
            (goal_id,),
        ).fetchall()

        return [dict(row) for row in rows]
    finally:
        connection.close()


def upsert_gta6_goal_artifacts(
    *,
    goal_id: str,
    idea_id: int | None = None,
    script_id: int | None = None,
    content_item_id: int | None = None,
    video_id: int | None = None,
    render_job_id: int | None = None,
    youtube_publication_id: int | None = None,
) -> dict[str, Any]:
    """Cria ou atualiza a linhagem de artefatos de um Goal."""

    goal_id = _validate_goal_id(goal_id)

    values = {
        "idea_id": idea_id,
        "script_id": script_id,
        "content_item_id": content_item_id,
        "video_id": video_id,
        "render_job_id": render_job_id,
        "youtube_publication_id": youtube_publication_id,
    }

    for field, value in values.items():
        if value is not None:
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError(f"{field} must be an integer or None")
            if value <= 0:
                raise ValueError(f"{field} must be greater than zero")

    connection = get_connection()
    try:
        connection.execute(
            """
            INSERT INTO gta6_goal_artifacts (
                goal_id,
                idea_id,
                script_id,
                content_item_id,
                video_id,
                render_job_id,
                youtube_publication_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(goal_id) DO UPDATE SET
                idea_id = COALESCE(
                    excluded.idea_id,
                    gta6_goal_artifacts.idea_id
                ),
                script_id = COALESCE(
                    excluded.script_id,
                    gta6_goal_artifacts.script_id
                ),
                content_item_id = COALESCE(
                    excluded.content_item_id,
                    gta6_goal_artifacts.content_item_id
                ),
                video_id = COALESCE(
                    excluded.video_id,
                    gta6_goal_artifacts.video_id
                ),
                render_job_id = COALESCE(
                    excluded.render_job_id,
                    gta6_goal_artifacts.render_job_id
                ),
                youtube_publication_id = COALESCE(
                    excluded.youtube_publication_id,
                    gta6_goal_artifacts.youtube_publication_id
                ),
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                goal_id,
                idea_id,
                script_id,
                content_item_id,
                video_id,
                render_job_id,
                youtube_publication_id,
            ),
        )

        connection.commit()

        row = connection.execute(
            """
            SELECT
                goal_id,
                idea_id,
                script_id,
                content_item_id,
                video_id,
                render_job_id,
                youtube_publication_id,
                created_at,
                updated_at
            FROM gta6_goal_artifacts
            WHERE goal_id = ?
            LIMIT 1
            """,
            (goal_id,),
        ).fetchone()

        if row is None:
            raise RuntimeError(
                "GTA6 Goal artifacts were not persisted"
            )

        return dict(row)
    finally:
        connection.close()


def get_gta6_goal_artifacts(
    goal_id: str,
) -> dict[str, Any] | None:
    """Retorna a linhagem de artefatos de um Goal."""

    goal_id = _validate_goal_id(goal_id)

    connection = get_connection()
    try:
        row = connection.execute(
            """
            SELECT
                goal_id,
                idea_id,
                script_id,
                content_item_id,
                video_id,
                render_job_id,
                youtube_publication_id,
                created_at,
                updated_at
            FROM gta6_goal_artifacts
            WHERE goal_id = ?
            LIMIT 1
            """,
            (goal_id,),
        ).fetchone()

        return dict(row) if row else None
    finally:
        connection.close()


def get_gta6_goal_artifacts_by_idea_id(
    idea_id: int,
) -> dict[str, Any] | None:
    """Retorna a linhagem de Goal associada a uma Idea."""

    if (
        not isinstance(idea_id, int)
        or isinstance(idea_id, bool)
        or idea_id <= 0
    ):
        raise ValueError(
            "idea_id must be a positive integer"
        )

    connection = get_connection()

    try:
        row = connection.execute(
            """
            SELECT
                goal_id,
                idea_id,
                script_id,
                content_item_id,
                video_id,
                render_job_id,
                youtube_publication_id,
                created_at,
                updated_at
            FROM gta6_goal_artifacts
            WHERE idea_id = ?
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (idea_id,),
        ).fetchone()

        return dict(row) if row else None
    finally:
        connection.close()
