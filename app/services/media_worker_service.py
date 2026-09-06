from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.database.media_knowledge_repository import (
    MediaKnowledgeRepository,
)
from app.services.media_analysis.models import MediaKnowledge
from app.services.media_analysis.pipeline import analyze_media


@dataclass(frozen=True)
class MediaWorkerResult:
    """Resultado da execução de análise do Media Worker."""

    knowledge: MediaKnowledge
    knowledge_id: int


def run_media_analysis(
    source_path: str | Path,
    repository: MediaKnowledgeRepository | None = None,
) -> MediaWorkerResult:
    """Analisa uma mídia e persiste o MediaKnowledge produzido."""

    path = Path(source_path)

    knowledge = analyze_media(path)

    repository = repository or MediaKnowledgeRepository()

    knowledge_id = repository.save(knowledge)

    return MediaWorkerResult(
        knowledge=knowledge,
        knowledge_id=knowledge_id,
    )
