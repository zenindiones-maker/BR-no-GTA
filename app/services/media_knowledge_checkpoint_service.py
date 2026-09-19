from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from app.database.media_knowledge_repository import MediaKnowledgeRepository
from app.services.media_worker_artifact_import_service import validate_media_worker_artifact


class MediaKnowledgeCheckpointMiss(RuntimeError):
    """Content-addressed MediaKnowledge checkpoint cannot be reused safely."""


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fingerprint(
    *,
    source_sha256: str,
    analyzer_version: str,
    schema_version: str,
    analysis_profile: str,
) -> str:
    payload = {
        "source_sha256": source_sha256,
        "analyzer_version": analyzer_version,
        "schema_version": schema_version,
        "analysis_profile": analysis_profile,
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


def import_content_addressed_media_knowledge(
    *,
    descriptor_path: str | Path,
    artifact_dir: str | Path,
) -> dict[str, Any]:
    """Reuse a previously validated MediaKnowledge artifact without heavy reanalysis.

    The controller may import only when source bytes identity, analyzer version,
    artifact schema, analysis profile and exact artifact hashes all match the
    persisted descriptor. A miss is fail-closed and must be handled by the
    dedicated media worker, never by silently re-running heavy analysis here.
    """
    descriptor_path = Path(descriptor_path)
    artifact_dir = Path(artifact_dir)
    descriptor = _load_json(descriptor_path)
    if descriptor.get("schema_version") != "media-knowledge-checkpoint/v1":
        raise MediaKnowledgeCheckpointMiss("unsupported MediaKnowledge checkpoint descriptor")
    if descriptor.get("status") != "PASS":
        raise MediaKnowledgeCheckpointMiss("MediaKnowledge checkpoint is not PASS")

    source = descriptor.get("source")
    analysis = descriptor.get("analysis")
    if not isinstance(source, dict) or not isinstance(analysis, dict):
        raise MediaKnowledgeCheckpointMiss("checkpoint source/analysis identity missing")

    media_path = artifact_dir / "media_knowledge.json"
    manifest_path = artifact_dir / "manifest.json"
    if _sha256(media_path) != str(analysis.get("media_knowledge_sha256") or ""):
        raise MediaKnowledgeCheckpointMiss("media_knowledge.json content hash mismatch")
    if _sha256(manifest_path) != str(analysis.get("manifest_sha256") or ""):
        raise MediaKnowledgeCheckpointMiss("MediaKnowledge manifest content hash mismatch")

    validated = validate_media_worker_artifact(artifact_dir)
    manifest = validated["manifest"]
    knowledge = dict(validated["knowledge"])
    metadata = dict(knowledge.get("metadata") or {})

    source_sha = str(source.get("source_sha256") or "").strip().lower()
    analyzer_version = str(metadata.get("analysis_version") or "")
    schema_version = str(manifest.get("artifact_schema_version") or "")
    analysis_profile = str(analysis.get("analysis_profile") or "")
    expected_fingerprint = str(analysis.get("content_fingerprint") or "")
    observed_fingerprint = _fingerprint(
        source_sha256=source_sha,
        analyzer_version=analyzer_version,
        schema_version=schema_version,
        analysis_profile=analysis_profile,
    )

    identity_checks = {
        "source_sha256": len(source_sha) == 64,
        "source_url": manifest.get("source_url") == source.get("source_url"),
        "source_name": manifest.get("source_name") == source.get("source_name"),
        "analyzer_version": analyzer_version == str(analysis.get("analyzer_version") or ""),
        "schema_version": schema_version == str(analysis.get("artifact_schema_version") or ""),
        "analysis_profile": bool(analysis_profile),
        "content_fingerprint": observed_fingerprint == expected_fingerprint,
    }
    failed = [name for name, passed in identity_checks.items() if not passed]
    if failed:
        raise MediaKnowledgeCheckpointMiss(
            "MediaKnowledge content-addressed identity mismatch: " + ",".join(failed)
        )

    metadata.update(
        {
            "source_sha256": source_sha,
            "analyzer_version": analyzer_version,
            "schema_version": schema_version,
            "analysis_profile": analysis_profile,
            "content_fingerprint": observed_fingerprint,
            "content_addressed_reuse": True,
            "analysis_source_run_id": analysis.get("analysis_run_id"),
            "analysis_source_artifact_id": analysis.get("analysis_artifact_id"),
        }
    )
    knowledge["metadata"] = metadata

    persisted = MediaKnowledgeRepository().save_payload_if_absent(knowledge)
    return {
        "status": "imported" if persisted["created"] else "already_present",
        "knowledge_id": persisted["id"],
        "created": persisted["created"],
        "cache_hit": True,
        "analysis_executed": False,
        "content_fingerprint": observed_fingerprint,
        "source_sha256": source_sha,
        "analyzer_version": analyzer_version,
        "schema_version": schema_version,
        "analysis_profile": analysis_profile,
        "source_url": manifest.get("source_url"),
        "source_name": manifest.get("source_name"),
        "identity_checks": identity_checks,
    }
