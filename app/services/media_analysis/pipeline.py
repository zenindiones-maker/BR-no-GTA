from __future__ import annotations

from pathlib import Path

from app.services.media_analysis.ffprobe_analyzer import (
    probe_media,
)
from app.services.media_analysis.models import (
    MediaKnowledge,
)


class MediaAnalysisError(RuntimeError):
    """Erro na construção do conhecimento da mídia."""


def analyze_media(
    source_path: str | Path,
) -> MediaKnowledge:
    """
    Constrói conhecimento técnico inicial sobre uma mídia.

    Esta etapa é somente análise.
    Nenhuma operação editorial é executada.
    Nenhuma operação do Vedit é executada.
    """

    path = Path(source_path)

    if not path.is_file():
        raise MediaAnalysisError(
            f"Mídia não encontrada: {path}"
        )

    probe = probe_media(path)

    return MediaKnowledge(
        source_path=str(path),
        probe=probe,
        metadata={
            "analysis_version": "1",
            "probe_available": True,
            "scenes_available": False,
            "transcript_available": False,
            "audio_analysis_available": False,
            "beats_available": False,
            "visual_samples_available": False,
        },
    )
