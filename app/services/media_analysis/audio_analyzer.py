from __future__ import annotations

import math
from pathlib import Path

from app.services.media_analysis.models import AudioFeature, Beat


class AudioAnalysisError(RuntimeError):
    """Erro durante a análise de áudio da mídia."""


def _decode_audio(
    source_path: Path,
):
    try:
        import av
    except ImportError as exc:
        raise AudioAnalysisError(
            "PyAV não está instalado no ambiente de análise."
        ) from exc

    try:
        import numpy as np
    except ImportError as exc:
        raise AudioAnalysisError(
            "NumPy não está instalado no ambiente de análise."
        ) from exc

    try:
        with av.open(source_path) as container:
            audio_stream = next(
                iter(container.streams.audio),
                None,
            )

            if audio_stream is None:
                return np.empty(0, dtype=np.float32), None

            sample_rate = (
                audio_stream.codec_context.sample_rate
                or audio_stream.rate
            )

            if not sample_rate:
                raise AudioAnalysisError(
                    f"Stream de áudio sem sample rate: {source_path}"
                )

            resampler = av.audio.resampler.AudioResampler(
                format="fltp",
                layout="mono",
                rate=int(sample_rate),
            )

            chunks = []

            audio_stream_index = next(
                index
                for index, stream in enumerate(container.streams.audio)
                if stream is audio_stream
            )

            for frame in container.decode(
                audio=audio_stream_index,
            ):
                for resampled_frame in resampler.resample(frame):
                    array = resampled_frame.to_ndarray()

                    chunks.append(
                        np.asarray(
                            array,
                            dtype=np.float32,
                        ).reshape(-1)
                    )

            for resampled_frame in resampler.resample(None):
                array = resampled_frame.to_ndarray()

                chunks.append(
                    np.asarray(
                        array,
                        dtype=np.float32,
                    ).reshape(-1)
                )

            if not chunks:
                return (
                    np.empty(0, dtype=np.float32),
                    int(sample_rate),
                )

            audio = np.concatenate(chunks)

            return audio, int(sample_rate)

    except AudioAnalysisError:
        raise
    except Exception as exc:
        raise AudioAnalysisError(
            f"Falha na decodificação de áudio: {source_path}"
        ) from exc


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
    except ImportError as exc:
        raise AudioAnalysisError(
            "librosa não está instalada no ambiente de análise."
        ) from exc

    try:
        audio, sample_rate = _decode_audio(path)

        if len(audio) == 0 or sample_rate is None:
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

            start_sample = int(start * sample_rate)
            end_sample = max(
                int(end * sample_rate),
                start_sample + 1,
            )

            segment = audio[
                start_sample:end_sample
            ]

            peak_value = max(
                abs(float(sample))
                for sample in segment
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

    except AudioAnalysisError:
        raise
    except Exception as exc:
        raise AudioAnalysisError(
            f"Falha na análise de áudio: {path}"
        ) from exc
