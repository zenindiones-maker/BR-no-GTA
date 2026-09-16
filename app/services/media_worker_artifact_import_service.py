from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.database.media_knowledge_repository import MediaKnowledgeRepository
from app.services.media_analysis.serialization import deserialize_media_knowledge
from app.services.media_worker_artifact import (
    ARTIFACT_SCHEMA_VERSION,
    ARTIFACT_TYPE,
    MEDIA_KNOWLEDGE_FILENAME,
    MEDIA_MANIFEST_FILENAME,
)


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"Artifact obrigatório ausente: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} precisa conter um objeto JSON.")
    return payload


def validate_media_worker_artifact(artifact_dir: str | Path) -> dict[str, Any]:
    """Validate JSON-only Media Worker output before local persistence."""
    directory = Path(artifact_dir)
    manifest = _load_json(directory / MEDIA_MANIFEST_FILENAME)
    knowledge = _load_json(directory / MEDIA_KNOWLEDGE_FILENAME)

    if manifest.get("artifact_type") != ARTIFACT_TYPE:
        raise ValueError("Manifest não pertence ao media-worker.")
    if str(manifest.get("artifact_schema_version")) != ARTIFACT_SCHEMA_VERSION:
        raise ValueError("Manifest possui artifact_schema_version incompatível.")
    if manifest.get("source_local_file_included") is not False:
        raise ValueError("Artifact não pode transportar a mídia física para o control-plane.")
    if manifest.get("source_local_file_required") is not False:
        raise ValueError("Artifact remoto não pode exigir arquivo local de mídia.")

    files = manifest.get("files") or {}
    if not isinstance(files, dict) or files.get("media_knowledge") != MEDIA_KNOWLEDGE_FILENAME:
        raise ValueError("Manifest não referencia media_knowledge.json corretamente.")

    source_path = knowledge.get("source_path")
    if not isinstance(source_path, str) or not source_path.startswith("remote://media-worker/"):
        raise ValueError("MediaKnowledge importável precisa usar source_path remoto estável.")
    if manifest.get("source_ref") != source_path:
        raise ValueError("Manifest/source_ref não corresponde ao MediaKnowledge source_path.")

    metadata = knowledge.get("metadata") or {}
    if not isinstance(metadata, dict):
        raise ValueError("MediaKnowledge metadata inválido.")
    if metadata.get("artifact_type") != ARTIFACT_TYPE:
        raise ValueError("MediaKnowledge metadata não pertence ao media-worker.")
    if str(metadata.get("artifact_schema_version")) != ARTIFACT_SCHEMA_VERSION:
        raise ValueError("MediaKnowledge metadata possui schema incompatível.")
    if metadata.get("source_storage") != "remote":
        raise ValueError("MediaKnowledge importável precisa declarar source_storage=remote.")
    if metadata.get("source_local_file_required") is not False:
        raise ValueError("MediaKnowledge importável não pode depender de mídia local.")

    if manifest.get("source_url") != metadata.get("source_url"):
        raise ValueError("source_url diverge entre manifest e MediaKnowledge.")
    if manifest.get("source_name") != metadata.get("source_name"):
        raise ValueError("source_name diverge entre manifest e MediaKnowledge.")

    visual_samples = knowledge.get("visual_samples") or []
    if not isinstance(visual_samples, list):
        raise ValueError("visual_samples precisa ser uma lista.")
    for index, sample in enumerate(visual_samples):
        if not isinstance(sample, dict):
            raise ValueError(f"visual_samples[{index}] inválido.")
        if sample.get("path") is not None:
            raise ValueError("Artifact remoto não pode referenciar JPG local do runner.")
        frame_ref = sample.get("frame_ref")
        if not isinstance(frame_ref, str) or not frame_ref:
            raise ValueError("VisualSample remoto precisa preservar frame_ref.")

    # Full schema reconstruction catches malformed scene/probe/transcript fields.
    deserialize_media_knowledge(knowledge)
    return {"manifest": manifest, "knowledge": knowledge}


def import_media_worker_artifact(artifact_dir: str | Path) -> dict[str, Any]:
    """Idempotently reconcile a small JSON artifact into persistent MediaKnowledge."""
    validated = validate_media_worker_artifact(artifact_dir)
    repository = MediaKnowledgeRepository()
    persisted = repository.save_payload_if_absent(validated["knowledge"])
    return {
        "status": "imported" if persisted["created"] else "already_present",
        "knowledge_id": persisted["id"],
        "created": persisted["created"],
        "source_path": validated["knowledge"]["source_path"],
        "source_url": validated["manifest"].get("source_url"),
        "source_name": validated["manifest"].get("source_name"),
    }
