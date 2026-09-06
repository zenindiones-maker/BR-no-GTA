from __future__ import annotations

import json
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
