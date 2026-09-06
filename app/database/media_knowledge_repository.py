from __future__ import annotations

import json
from app.database.connection import get_connection
from app.services.media_analysis.models import (
    MediaKnowledge,
)
from app.services.media_analysis.serialization import (
    serialize_media_knowledge,
)


class MediaKnowledgeRepository:
    """Persistência dos resultados de análise multimídia."""

    def save(
        self,
        knowledge: MediaKnowledge,
    ) -> int:
        """Persiste um MediaKnowledge e retorna seu ID."""

        payload = json.dumps(
            serialize_media_knowledge(knowledge),
            ensure_ascii=False,
            separators=(",", ":"),
        )

        analysis_version = str(
            knowledge.metadata.get(
                "analysis_version",
                "unknown",
            )
        )

        connection = get_connection()

        try:
            cursor = connection.execute(
                """
                INSERT INTO media_knowledge (
                    source_path,
                    analysis_version,
                    payload
                )
                VALUES (?, ?, ?)
                """,
                (
                    knowledge.source_path,
                    analysis_version,
                    payload,
                ),
            )

            connection.commit()

            return int(cursor.lastrowid)

        finally:
            connection.close()

    def get_payload(
        self,
        knowledge_id: int,
    ) -> dict:
        """Retorna o payload bruto persistido."""

        connection = get_connection()

        try:
            row = connection.execute(
                """
                SELECT payload
                FROM media_knowledge
                WHERE id = ?
                """,
                (knowledge_id,),
            ).fetchone()

            if row is None:
                raise KeyError(
                    f"MediaKnowledge não encontrado: {knowledge_id}"
                )

            return json.loads(row["payload"])

        finally:
            connection.close()
