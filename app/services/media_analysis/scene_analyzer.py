from __future__ import annotations

from pathlib import Path

from app.services.media_analysis.models import SceneBoundary


class SceneAnalysisError(RuntimeError):
    """Erro durante a detecção de cenas."""


def _timecode_to_seconds(timecode) -> float:
    """Converte FrameTimecode do PySceneDetect para segundos."""
    try:
        return float(timecode.get_seconds())
    except AttributeError as exc:
        raise SceneAnalysisError(
            "PySceneDetect retornou um timecode inválido."
        ) from exc


def detect_scenes(
    source_path: str | Path,
    *,
    threshold: float = 27.0,
) -> tuple[SceneBoundary, ...]:
    """
    Detecta cortes/cenas usando PySceneDetect.

    Esta função somente observa a mídia.
    Nenhuma operação editorial ou de edição é executada.
    """

    path = Path(source_path)

    if not path.is_file():
        raise SceneAnalysisError(
            f"Mídia não encontrada: {path}"
        )

    try:
        from scenedetect import ContentDetector, detect
    except ImportError as exc:
        raise SceneAnalysisError(
            "PySceneDetect não está instalado."
        ) from exc

    try:
        scenes = detect(
            str(path),
            ContentDetector(
                threshold=threshold,
            ),
        )
    except Exception as exc:
        raise SceneAnalysisError(
            f"PySceneDetect falhou: {exc}"
        ) from exc

    boundaries: list[SceneBoundary] = []

    for start, end in scenes:
        start_seconds = _timecode_to_seconds(start)
        end_seconds = _timecode_to_seconds(end)

        if end_seconds <= start_seconds:
            continue

        boundaries.append(
            SceneBoundary(
                start_seconds=start_seconds,
                end_seconds=end_seconds,
            )
        )

    return tuple(boundaries)
