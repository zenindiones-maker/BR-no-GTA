from __future__ import annotations

import json
import subprocess
from pathlib import Path

from app.services.media_analysis.models import (
    MediaProbe,
    MediaStream,
)


class MediaProbeError(RuntimeError):
    """Erro durante a inspeção técnica da mídia."""


def _parse_fps(value: object) -> float | None:
    if not isinstance(value, str) or not value.strip():
        return None

    try:
        if "/" in value:
            numerator, denominator = value.split("/", 1)
            return float(numerator) / float(denominator)

        return float(value)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def probe_media(
    source_path: str | Path,
) -> MediaProbe:
    path = Path(source_path)

    if not path.is_file():
        raise MediaProbeError(
            f"Mídia não encontrada: {path}"
        )

    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_format",
        "-show_streams",
        "-of",
        "json",
        str(path),
    ]

    try:
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise MediaProbeError(
            "ffprobe não está instalado."
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise MediaProbeError(
            "ffprobe falhou: "
            f"{exc.stderr.strip()}"
        ) from exc

    try:
        payload = json.loads(
            completed.stdout
        )
    except json.JSONDecodeError as exc:
        raise MediaProbeError(
            "ffprobe retornou JSON inválido."
        ) from exc

    streams_payload = payload.get(
        "streams",
        []
    )

    format_payload = payload.get(
        "format",
        {}
    )

    if not streams_payload:
        raise MediaProbeError(
            "Nenhum stream encontrado."
        )

    streams: list[MediaStream] = []

    for stream in streams_payload:
        codec_type = stream.get(
            "codec_type",
            "unknown",
        )

        streams.append(
            MediaStream(
                index=int(
                    stream.get("index", 0)
                ),
                codec_type=str(codec_type),
                codec_name=(
                    str(stream["codec_name"])
                    if stream.get("codec_name")
                    else None
                ),
                width=(
                    int(stream["width"])
                    if stream.get("width") is not None
                    else None
                ),
                height=(
                    int(stream["height"])
                    if stream.get("height") is not None
                    else None
                ),
                fps=_parse_fps(
                    stream.get("r_frame_rate")
                ),
                sample_rate=(
                    int(stream["sample_rate"])
                    if stream.get("sample_rate")
                    else None
                ),
                channels=(
                    int(stream["channels"])
                    if stream.get("channels") is not None
                    else None
                ),
            )
        )

    duration_raw = format_payload.get(
        "duration"
    )

    size_raw = format_payload.get(
        "size"
    )

    try:
        duration = (
            float(duration_raw)
            if duration_raw is not None
            else None
        )
    except (TypeError, ValueError):
        duration = None

    try:
        size = (
            int(float(size_raw))
            if size_raw is not None
            else None
        )
    except (TypeError, ValueError):
        size = None

    return MediaProbe(
        format_name=(
            str(format_payload["format_name"])
            if format_payload.get("format_name")
            else None
        ),
        duration_seconds=duration,
        size_bytes=size,
        streams=tuple(streams),
    )
