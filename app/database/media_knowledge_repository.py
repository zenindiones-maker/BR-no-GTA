from __future__ import annotations

import hashlib
import json
from typing import Any

from app.database.connection import get_connection
from app.services.media_analysis.models import MediaKnowledge
from app.services.media_analysis.serialization import (
    deserialize_media_knowledge,
    serialize_media_knowledge,
)


MEDIA_POOL_METADATA_KEY = "media_pool"
MEDIA_POOL_SCHEMA_VERSION = "1"


def _canonical_json_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize tuples/dataclasses-derived containers to their persisted JSON shape."""
    return json.loads(
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )


class MediaKnowledgeRepository:
    """Persistência dos resultados de análise multimídia e pools imutáveis."""

    def save(self, knowledge: MediaKnowledge) -> int:
        """Persiste um MediaKnowledge e retorna seu ID."""
        payload = json.dumps(
            serialize_media_knowledge(knowledge),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        analysis_version = str(knowledge.metadata.get("analysis_version", "unknown"))
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
                (knowledge.source_path, analysis_version, payload),
            )
            connection.commit()
            return int(cursor.lastrowid)
        finally:
            connection.close()

    def get_payload(self, knowledge_id: int) -> dict:
        """Retorna o payload bruto persistido."""
        connection = get_connection()
        try:
            row = connection.execute(
                "SELECT payload FROM media_knowledge WHERE id = ?",
                (knowledge_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"MediaKnowledge não encontrado: {knowledge_id}")
            return json.loads(row["payload"])
        finally:
            connection.close()

    def list_records(self) -> list[dict[str, Any]]:
        """Lista snapshots imutáveis com payload para readiness/import reconciliation."""
        connection = get_connection()
        try:
            rows = connection.execute(
                """
                SELECT id, source_path, analysis_version, payload
                FROM media_knowledge
                ORDER BY id ASC
                """
            ).fetchall()
            return [
                {
                    "id": int(row["id"]),
                    "source_path": row["source_path"],
                    "analysis_version": row["analysis_version"],
                    "payload": json.loads(row["payload"]),
                }
                for row in rows
            ]
        finally:
            connection.close()

    def find_exact_payload(self, payload: dict[str, Any]) -> int | None:
        """Resolve idempotência sem atualizar snapshots existentes."""
        if not isinstance(payload, dict) or not payload:
            raise ValueError("MediaKnowledge payload precisa ser um objeto não vazio.")
        normalized = _canonical_json_payload(payload)
        source_path = normalized.get("source_path")
        if not isinstance(source_path, str) or not source_path.strip():
            raise ValueError("MediaKnowledge payload precisa possuir source_path.")
        connection = get_connection()
        try:
            rows = connection.execute(
                """
                SELECT id, payload
                FROM media_knowledge
                WHERE source_path = ?
                ORDER BY id DESC
                """,
                (source_path.strip(),),
            ).fetchall()
            for row in rows:
                if json.loads(row["payload"]) == normalized:
                    return int(row["id"])
            return None
        finally:
            connection.close()

    def save_payload_if_absent(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Valida, desserializa e persiste um artifact somente se ele for novo."""
        normalized = _canonical_json_payload(payload)
        existing_id = self.find_exact_payload(normalized)
        if existing_id is not None:
            return {"id": existing_id, "created": False}
        knowledge = deserialize_media_knowledge(normalized)
        knowledge_id = self.save(knowledge)
        return {"id": knowledge_id, "created": True}

    def ensure_pool(
        self,
        *,
        knowledge_ids: list[int],
        pool_name: str = "run001-ab",
    ) -> dict[str, Any]:
        """Cria/reusa um snapshot pool imutável que o Harness pode autorizar por um único ID."""
        if not isinstance(pool_name, str) or not pool_name.strip():
            raise ValueError("pool_name deve ser uma string não vazia.")
        normalized: list[int] = []
        for value in knowledge_ids:
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError("knowledge_ids deve conter apenas inteiros positivos.")
            if value not in normalized:
                normalized.append(value)
        if not normalized:
            raise ValueError("knowledge_ids não pode ser vazio.")

        for knowledge_id in normalized:
            payload = self.get_payload(knowledge_id)
            metadata = payload.get("metadata") or {}
            if isinstance(metadata, dict) and metadata.get(MEDIA_POOL_METADATA_KEY) is not None:
                raise ValueError("MediaKnowledge pools não podem ser aninhados.")

        identity = ",".join(str(value) for value in normalized)
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
        pool = MediaKnowledge(
            source_path=f"pool://media-knowledge/{pool_name.strip()}/{digest}",
            metadata={
                "analysis_version": "pool-1",
                "source_storage": "logical-pool",
                MEDIA_POOL_METADATA_KEY: {
                    "schema_version": MEDIA_POOL_SCHEMA_VERSION,
                    "knowledge_ids": normalized,
                },
            },
        )
        payload = _canonical_json_payload(serialize_media_knowledge(pool))
        result = self.save_payload_if_absent(payload)
        return {
            **result,
            "knowledge_ids": normalized,
            "source_path": pool.source_path,
        }
