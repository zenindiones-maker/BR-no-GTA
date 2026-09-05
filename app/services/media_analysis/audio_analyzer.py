from __future__ import annotations

import math
from pathlib import Path

from app.services.media_analysis.models import AudioFeature, Beat


class AudioAnalysisError(RuntimeError):
    """Erro durante a análise de áudio da mídia."""


def analyze_audio(
    source_path: str | Path,
    *,
    hop_length: int = 512,
    frame_length: int = 2048,
    silence_threshold_db: float = -45.0,
) -> tuple[tuple[AudioFeature, ...], tuple[Beat, ...]]:
    path = Path(source_path)

    if not path.is_file():
        raise AudioAnalysisError(
            f"Mídia não encontrada: {path}"
        )

    try:
        import librosa

        audio, sample_rate = librosa.load(
            path,
            sr=None,
            mono=True,
        )

        if len(audio) == 0:
            return (), ()

        rms_values = librosa.feature.rms(
            y=audio,
            frame_length=frame_length,
            hop_length=hop_length,
        )[0]

        times = librosa.frames_to_time(
            range(len(rms_values)),
            sr=sample_rate,
            hop_length=hop_length,
        )

        audio_features = []

        for index, timestamp in enumerate(times):
            start = float(timestamp)

            if index + 1 < len(times):
                end = float(times[index + 1])
            else:
                end = float(
                    max(
                        start,
                        len(audio) / sample_rate,
                    )
                )

            rms_value = float(rms_values[index])

            rms_db = (
                20.0
                * math.log10(
                    max(rms_value, 1e-10)
                )
            )

            peak_value = max(
                abs(float(sample))
                for sample in audio[
                    int(start * sample_rate):
                    max(
                        int(end * sample_rate),
                        int(start * sample_rate) + 1,
                    )
                ]
            )

            audio_features.append(
                AudioFeature(
                    start_seconds=start,
                    end_seconds=end,
                    rms=rms_value,
                    peak=peak_value,
                    silence=(
                        rms_db <= silence_threshold_db
                    ),
                )
            )

        tempo, beat_frames = librosa.beat.beat_track(
            y=audio,
            sr=sample_rate,
            hop_length=hop_length,
        )

        del tempo

        beat_times = librosa.frames_to_time(
            beat_frames,
            sr=sample_rate,
            hop_length=hop_length,
        )

        strengths = librosa.onset.onset_strength(
            y=audio,
            sr=sample_rate,
            hop_length=hop_length,
        )

        beats = tuple(
            Beat(
                time_seconds=float(timestamp),
                strength=(
                    float(strengths[frame])
                    if frame < len(strengths)
                    else None
                ),
            )
            for frame, timestamp in zip(
                beat_frames,
                beat_times,
            )
        )

        return tuple(audio_features), beats

    except ImportError as exc:
        raise AudioAnalysisError(
            "librosa não está instalada no ambiente de análise."
        ) from exc

    except Exception as exc:
        raise AudioAnalysisError(
            f"Falha na análise de áudio: {path}"
        ) from exc
