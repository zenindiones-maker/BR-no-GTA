from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from app.services.media_analysis.models import (
    AudioFeature,
    Beat,
    MediaKnowledge,
    MediaProbe,
    MotionFeature,
    SceneKnowledge,
    TranscriptSegment,
    VisualSample,
)
from app.services.media_analysis.serialization import serialize_media_knowledge

MEDIA_KNOWLEDGE_FILENAME = "media_knowledge.json"
MEDIA_SOURCE_DIRNAME = "media"
MEDIA_SOURCE_FILENAME = "source.mp4"
MEDIA_MANIFEST_FILENAME = "media-worker-manifest.json"


def write_media_knowledge_artifact(
    knowledge: MediaKnowledge,
    output_dir: str | Path,
) -> Path:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)

    output_path = directory / MEDIA_KNOWLEDGE_FILENAME
    payload = serialize_media_knowledge(knowledge)

    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return output_path

def package_media_worker_artifact(
    knowledge: MediaKnowledge,
    source_path: str | Path,
    output_dir: str | Path,
) -> dict[str, Path]:
    """Empacota conhecimento e mídia para transporte entre workers."""
    source = Path(source_path)
    if not source.is_file():
        raise FileNotFoundError(
            f"Mídia de origem não encontrada: {source}"
        )

    if str(Path(knowledge.source_path)) != str(source):
        raise ValueError(
            "O source_path do MediaKnowledge não corresponde "
            "à mídia fornecida."
        )

    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)

    media_dir = directory / MEDIA_SOURCE_DIRNAME
    media_dir.mkdir(parents=True, exist_ok=True)

    source_output = media_dir / MEDIA_SOURCE_FILENAME
    shutil.copy2(source, source_output)

    knowledge_output = write_media_knowledge_artifact(
        knowledge,
        directory,
    )

    manifest_output = directory / MEDIA_MANIFEST_FILENAME
    manifest_output.write_text(
        json.dumps(
            {
                "artifact_type": "media-worker",
                "source_file": (
                    f"{MEDIA_SOURCE_DIRNAME}/{MEDIA_SOURCE_FILENAME}"
                ),
                "knowledge_file": MEDIA_KNOWLEDGE_FILENAME,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    return {
        "source": source_output,
        "knowledge": knowledge_output,
        "manifest": manifest_output,
    }


def read_media_knowledge_artifact(
    artifact_path: str | Path,
) -> dict[str, Any]:
    path = Path(artifact_path)

    if not path.is_file():
        raise FileNotFoundError(
            f"Artifact MediaKnowledge não encontrado: {path}"
        )

    payload = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(payload, dict):
        raise ValueError(
            "O artifact MediaKnowledge precisa conter um objeto JSON."
        )

    return payload
