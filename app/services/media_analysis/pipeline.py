from __future__ import annotations

from pathlib import Path

from app.services.media_analysis.audio_analyzer import (
    analyze_audio,
)
from app.services.media_analysis.ffprobe_analyzer import (
    probe_media,
)
from app.services.media_analysis.models import (
    MediaKnowledge,
    SceneKnowledge,
)
from app.services.media_analysis.scene_analyzer import (
    detect_scenes,
)
from app.services.media_analysis.visual_analyzer import (
    analyze_visual,
)


class MediaAnalysisError(RuntimeError):
    """Erro na construção do conhecimento da mídia."""


def analyze_media(
    source_path: str | Path,
) -> MediaKnowledge:
    """
    Constrói conhecimento técnico sobre uma mídia.

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

    scenes = detect_scenes(path)

    scene_knowledge = tuple(
        SceneKnowledge(
            index=index,
            start_seconds=scene.start_seconds,
            end_seconds=scene.end_seconds,
            duration_seconds=(
                scene.end_seconds - scene.start_seconds
            ),
            detection_method="pyscenedetect",
        )
        for index, scene in enumerate(scenes, start=1)
    )

    audio_features, beats = analyze_audio(path)
    visual_samples, motion_features = analyze_visual(path)

    return MediaKnowledge(
        source_path=str(path),
        probe=probe,
        scenes=scene_knowledge,
        audio_features=audio_features,
        beats=beats,
        visual_samples=visual_samples,
        motion_features=motion_features,
        metadata={
            "analysis_version": "3",
            "probe_available": True,
            "scenes_available": True,
            "scene_count": len(scene_knowledge),
            "transcript_available": False,
            "audio_analysis_available": True,
            "beats_available": True,
            "visual_samples_available": True,
            "motion_analysis_available": True,
            "visual_sample_count": len(visual_samples),
            "motion_feature_count": len(motion_features),
            "audio_feature_count": len(audio_features),
            "beat_count": len(beats),
        },
    )
