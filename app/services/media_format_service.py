from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class MediaFormatError(ValueError):
    """Erro de validação de formato audiovisual."""


@dataclass(frozen=True)
class MediaFormat:
    """Especificação física de uma saída audiovisual."""

    name: str
    width: int
    height: int
    aspect_ratio: str
    orientation: str
    fps: int = 30
    container: str = "mp4"
    video_codec: str = "h264"
    audio_codec: str = "aac"

    @property
    def resolution(self) -> str:
        return f"{self.width}x{self.height}"

    @property
    def is_vertical(self) -> bool:
        return self.orientation == "vertical"

    @property
    def is_horizontal(self) -> bool:
        return self.orientation == "horizontal"


LANDSCAPE_16_9 = MediaFormat(
    name="landscape_16_9",
    width=1920,
    height=1080,
    aspect_ratio="16:9",
    orientation="horizontal",
)

PORTRAIT_9_16 = MediaFormat(
    name="portrait_9_16",
    width=1080,
    height=1920,
    aspect_ratio="9:16",
    orientation="vertical",
)


MEDIA_FORMATS: dict[str, MediaFormat] = {
    LANDSCAPE_16_9.name: LANDSCAPE_16_9,
    PORTRAIT_9_16.name: PORTRAIT_9_16,
}


FORMAT_ALIASES: dict[str, str] = {
    "16:9": "landscape_16_9",
    "9:16": "portrait_9_16",
    "landscape": "landscape_16_9",
    "portrait": "portrait_9_16",
    "horizontal": "landscape_16_9",
    "vertical": "portrait_9_16",
}


def get_media_format(name: str) -> MediaFormat:
    """Retorna um formato audiovisual conhecido."""
    if not isinstance(name, str) or not name.strip():
        raise MediaFormatError(
            "O nome do formato audiovisual é obrigatório."
        )

    normalized = name.strip().lower()
    normalized = FORMAT_ALIASES.get(normalized, normalized)

    media_format = MEDIA_FORMATS.get(normalized)

    if media_format is None:
        raise MediaFormatError(
            f"Formato audiovisual não suportado: {name}"
        )

    return media_format


def list_media_formats() -> list[MediaFormat]:
    """Lista os formatos audiovisuais suportados."""
    return list(MEDIA_FORMATS.values())


def build_render_config(
    format_name: str,
    *,
    fps: int | None = None,
    container: str | None = None,
    video_codec: str | None = None,
    audio_codec: str | None = None,
) -> dict[str, Any]:
    """
    Constrói uma configuração de renderização a partir de um formato.

    A configuração continua sendo uma especificação declarativa.
    Nenhum renderizador é executado aqui.
    """
    media_format = get_media_format(format_name)

    selected_fps = media_format.fps if fps is None else fps
    if not isinstance(selected_fps, int) or selected_fps <= 0:
        raise MediaFormatError("FPS deve ser um inteiro positivo.")

    return {
        "resolution": media_format.resolution,
        "width": media_format.width,
        "height": media_format.height,
        "fps": selected_fps,
        "aspect_ratio": media_format.aspect_ratio,
        "orientation": media_format.orientation,
        "container": (
            media_format.container
            if container is None
            else container
        ),
        "video_codec": (
            media_format.video_codec
            if video_codec is None
            else video_codec
        ),
        "audio_codec": (
            media_format.audio_codec
            if audio_codec is None
            else audio_codec
        ),
    }
