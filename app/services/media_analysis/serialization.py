from __future__ import annotations

from dataclasses import asdict
from typing import Any

from app.services.media_analysis.models import (
    AudioFeature,
    Beat,
    MediaKnowledge,
    MediaProbe,
    MediaStream,
    MotionFeature,
    SceneKnowledge,
    TranscriptSegment,
    TranscriptWord,
    VisualSample,
)


def serialize_media_knowledge(
    knowledge: MediaKnowledge,
) -> dict[str, Any]:
    """Converte MediaKnowledge para uma estrutura serializável."""
    return asdict(knowledge)


def deserialize_media_knowledge(
    payload: dict[str, Any],
) -> MediaKnowledge:
    """
    Reconstrói MediaKnowledge a partir do artifact JSON.

    O artifact remoto pode conter VisualSample.path=None porque
    os JPGs são temporários no GitHub Actions. Nesse caso,
    frame_ref preserva a identidade lógica da amostra.
    """
    if not isinstance(payload, dict):
        raise ValueError("MediaKnowledge payload precisa ser um objeto.")

    source_path = payload.get("source_path")
    if not isinstance(source_path, str) or not source_path.strip():
        raise ValueError("MediaKnowledge precisa possuir source_path.")

    probe_payload = payload.get("probe")
    probe = None

    if probe_payload is not None:
        if not isinstance(probe_payload, dict):
            raise ValueError("probe precisa ser um objeto.")

        streams_payload = probe_payload.get("streams", [])
        if not isinstance(streams_payload, (list, tuple)):
            raise ValueError(
                "probe.streams precisa ser uma lista ou tupla."
            )

        streams = tuple(
            MediaStream(
                index=int(stream.get("index", 0)),
                codec_type=str(stream.get("codec_type", "")),
                codec_name=(
                    str(stream["codec_name"])
                    if stream.get("codec_name") is not None
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
                fps=(
                    float(stream["fps"])
                    if stream.get("fps") is not None
                    else None
                ),
                sample_rate=(
                    int(stream["sample_rate"])
                    if stream.get("sample_rate") is not None
                    else None
                ),
                channels=(
                    int(stream["channels"])
                    if stream.get("channels") is not None
                    else None
                ),
            )
            for stream in streams_payload
            if isinstance(stream, dict)
        )

        probe = MediaProbe(
            format_name=(
                str(probe_payload["format_name"])
                if probe_payload.get("format_name") is not None
                else None
            ),
            duration_seconds=(
                float(probe_payload["duration_seconds"])
                if probe_payload.get("duration_seconds") is not None
                else None
            ),
            size_bytes=(
                int(probe_payload["size_bytes"])
                if probe_payload.get("size_bytes") is not None
                else None
            ),
            streams=streams,
        )

    def _list(name: str) -> list[dict[str, Any]]:
        value = payload.get(name, [])
        if value is None:
            return []
        if not isinstance(value, (list, tuple)):
            raise ValueError(
                f"{name} precisa ser uma lista ou tupla."
            )
        return list(value)

    scenes = tuple(
        SceneKnowledge(
            index=int(item["index"]),
            start_seconds=float(item["start_seconds"]),
            end_seconds=float(item["end_seconds"]),
            duration_seconds=float(item["duration_seconds"]),
            detection_method=str(item["detection_method"]),
        )
        for item in _list("scenes")
    )

    transcript = tuple(
        TranscriptSegment(
            start_seconds=float(item["start_seconds"]),
            end_seconds=float(item["end_seconds"]),
            text=str(item["text"]),
            words=tuple(
                TranscriptWord(
                    word=str(word["word"]),
                    start_seconds=float(word["start_seconds"]),
                    end_seconds=float(word["end_seconds"]),
                    confidence=(
                        float(word["confidence"])
                        if word.get("confidence") is not None
                        else None
                    ),
                )
                for word in item.get("words", [])
            ),
        )
        for item in _list("transcript")
    )

    audio_features = tuple(
        AudioFeature(
            start_seconds=float(item["start_seconds"]),
            end_seconds=float(item["end_seconds"]),
            rms=(
                float(item["rms"])
                if item.get("rms") is not None
                else None
            ),
            peak=(
                float(item["peak"])
                if item.get("peak") is not None
                else None
            ),
            silence=bool(item.get("silence", False)),
        )
        for item in _list("audio_features")
    )

    beats = tuple(
        Beat(
            time_seconds=float(item["time_seconds"]),
            strength=(
                float(item["strength"])
                if item.get("strength") is not None
                else None
            ),
        )
        for item in _list("beats")
    )

    visual_samples = tuple(
        VisualSample(
            time_seconds=float(item["time_seconds"]),
            path=(
                str(item["path"])
                if item.get("path") is not None
                else None
            ),
            width=(
                int(item["width"])
                if item.get("width") is not None
                else None
            ),
            height=(
                int(item["height"])
                if item.get("height") is not None
                else None
            ),
            frame_ref=(
                str(item["frame_ref"])
                if item.get("frame_ref") is not None
                else None
            ),
        )
        for item in _list("visual_samples")
    )

    motion_features = tuple(
        MotionFeature(
            start_seconds=float(item["start_seconds"]),
            end_seconds=float(item["end_seconds"]),
            motion_score=float(item["motion_score"]),
        )
        for item in _list("motion_features")
    )

    metadata = payload.get("metadata", {})
    if not isinstance(metadata, dict):
        raise ValueError("metadata precisa ser um objeto.")

    return MediaKnowledge(
        source_path=source_path,
        probe=probe,
        scenes=scenes,
        transcript=transcript,
        audio_features=audio_features,
        beats=beats,
        visual_samples=visual_samples,
        motion_features=motion_features,
        metadata=dict(metadata),
    )
