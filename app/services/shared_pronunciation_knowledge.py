from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SHARED_PRONUNCIATION_SOURCES_PATH = (
    PROJECT_ROOT / "config" / "shared_knowledge" / "pronunciation_sources.json"
)


class SharedPronunciationKnowledgeError(ValueError):
    """Raised when canonical shared pronunciation source knowledge is missing or invalid."""


def load_shared_pronunciation_sources(
    path: Path | None = None,
) -> dict[str, Any]:
    """Load the single versioned source registry shared across BR-no-GTA workflows.

    This registry establishes provenance and pipeline requirements; it does not
    automatically approve a pronunciation or claim that source audio was analyzed.
    """
    source_path = path or SHARED_PRONUNCIATION_SOURCES_PATH
    try:
        payload = json.loads(source_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SharedPronunciationKnowledgeError(
            f"cannot load canonical pronunciation source registry: {source_path}"
        ) from exc

    if payload.get("schema") != "br-no-gta-shared-pronunciation-sources/v1":
        raise SharedPronunciationKnowledgeError("unsupported shared pronunciation source schema")
    if not str(payload.get("version") or "").strip():
        raise SharedPronunciationKnowledgeError("shared pronunciation source version is required")

    sources = payload.get("sources")
    if not isinstance(sources, list) or not sources:
        raise SharedPronunciationKnowledgeError("shared pronunciation sources must be a non-empty list")

    seen: set[str] = set()
    for source in sources:
        if not isinstance(source, dict):
            raise SharedPronunciationKnowledgeError("each shared pronunciation source must be an object")
        source_id = str(source.get("source_id") or "").strip()
        url = str(source.get("url") or "").strip()
        sha256 = str(source.get("sha256") or "").strip()
        if not source_id or not url or not sha256:
            raise SharedPronunciationKnowledgeError(
                "each source requires source_id, url, and sha256 provenance"
            )
        if source_id in seen:
            raise SharedPronunciationKnowledgeError(f"duplicate pronunciation source id: {source_id}")
        seen.add(source_id)
        if source.get("acoustic_analysis_status") != "PENDING" and not source.get("analysis_evidence"):
            raise SharedPronunciationKnowledgeError(
                f"source {source_id} claims analysis without attached analysis evidence"
            )
        if source.get("human_pronunciation_approval_status") == "APPROVED" and not source.get("human_approval_ref"):
            raise SharedPronunciationKnowledgeError(
                f"source {source_id} claims human approval without an approval reference"
            )

    pipeline = payload.get("required_pipeline")
    if not isinstance(pipeline, list) or not pipeline:
        raise SharedPronunciationKnowledgeError("required shared pronunciation pipeline is missing")

    return payload


def shared_pronunciation_source_by_id(
    source_id: str,
    *,
    path: Path | None = None,
) -> dict[str, Any]:
    """Resolve one source from the canonical registry or fail closed."""
    normalized = str(source_id or "").strip()
    if not normalized:
        raise SharedPronunciationKnowledgeError("source_id is required")
    payload = load_shared_pronunciation_sources(path)
    for source in payload["sources"]:
        if source["source_id"] == normalized:
            return dict(source)
    raise SharedPronunciationKnowledgeError(f"unknown shared pronunciation source: {normalized}")
