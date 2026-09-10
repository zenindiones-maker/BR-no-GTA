from __future__ import annotations

import json
from typing import Any

from app.database.connection import get_connection
from app.services.speech.models import SpeechAnalysis


class SpeechAnalysisRepository:
    """Persistência das análises especializadas de fala."""

    def save(
        self,
        *,
        media_knowledge_id: int,
        analysis: SpeechAnalysis,
    ) -> int:
        """Persiste uma SpeechAnalysis e retorna seu ID."""

        if not isinstance(media_knowledge_id, int) or media_knowledge_id <= 0:
            raise ValueError(
                "media_knowledge_id must be a positive integer"
            )

        payload = json.dumps(
            analysis.to_dict(),
            ensure_ascii=False,
            separators=(",", ":"),
        )

        connection = get_connection()
        try:
            media_row = connection.execute(
                """
                SELECT source_path
                FROM media_knowledge
                WHERE id = ?
                """,
                (media_knowledge_id,),
            ).fetchone()

            if media_row is None:
                raise KeyError(
                    "MediaKnowledge não encontrado: "
                    f"{media_knowledge_id}"
                )

            media_source_path = str(media_row["source_path"])

            if analysis.source_path != media_source_path:
                raise ValueError(
                    "SpeechAnalysis source_path não corresponde ao "
                    "MediaKnowledge associado: "
                    f"{analysis.source_path!r} != "
                    f"{media_source_path!r}"
                )

            cursor = connection.execute(
                """
                INSERT INTO speech_analysis (
                    media_knowledge_id,
                    source_path,
                    source_language,
                    language_probability,
                    analysis_version,
                    provider,
                    model,
                    model_version,
                    payload
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    media_knowledge_id,
                    analysis.source_path,
                    analysis.source_language,
                    analysis.language_probability,
                    analysis.analysis_version,
                    analysis.engine.provider,
                    analysis.engine.model,
                    analysis.engine.version,
                    payload,
                ),
            )
            connection.commit()
            return int(cursor.lastrowid)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
    def get_payload(
        self,
        analysis_id: int,
    ) -> dict[str, Any]:
        """Retorna o payload bruto persistido pelo ID da análise."""

        if not isinstance(analysis_id, int) or analysis_id <= 0:
            raise ValueError(
                "analysis_id must be a positive integer"
            )

        connection = get_connection()
        try:
            row = connection.execute(
                """
                SELECT payload
                FROM speech_analysis
                WHERE id = ?
                """,
                (analysis_id,),
            ).fetchone()

            if row is None:
                raise KeyError(
                    f"SpeechAnalysis não encontrado: {analysis_id}"
                )

            return json.loads(row["payload"])
        finally:
            connection.close()

    def get_by_media_knowledge(
        self,
        media_knowledge_id: int,
    ) -> list[dict[str, Any]]:
        """Retorna as análises associadas a um MediaKnowledge."""

        if (
            not isinstance(media_knowledge_id, int)
            or media_knowledge_id <= 0
        ):
            raise ValueError(
                "media_knowledge_id must be a positive integer"
            )

        connection = get_connection()
        try:
            rows = connection.execute(
                """
                SELECT
                    id,
                    media_knowledge_id,
                    source_path,
                    source_language,
                    language_probability,
                    analysis_version,
                    provider,
                    model,
                    model_version,
                    created_at,
                    updated_at
                FROM speech_analysis
                WHERE media_knowledge_id = ?
                ORDER BY id
                """,
                (media_knowledge_id,),
            ).fetchall()

            return [dict(row) for row in rows]
        finally:
            connection.close()
