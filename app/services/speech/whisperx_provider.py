from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from app.services.speech.models import (
    SpeechAnalysis,
    SpeechEngine,
    SpeechQuality,
    SpeechSegment,
    SpeechSpeaker,
    SpeechWord,
)


class WhisperXProvider:
    """
    Provider real de análise de fala usando WhisperX.

    Responsabilidades:
    - ASR
    - detecção de idioma
    - word timestamps via alignment
    - diarização quando HF_TOKEN estiver disponível
    - normalização para o contrato SpeechAnalysis

    O provider não conhece banco, VEDIT, YouTube ou GitHub Actions.
    """

    def __init__(
        self,
        *,
        model: str | None = None,
        device: str | None = None,
        compute_type: str | None = None,
        batch_size: int | None = None,
        hf_token: str | None = None,
    ) -> None:
        self._model_name = (
            model
            or os.getenv("SPEECH_MODEL")
            or "large-v2"
        )

        self._device = (
            device
            or os.getenv("SPEECH_DEVICE")
            or self._detect_device()
        )

        self._compute_type = (
            compute_type
            or os.getenv("SPEECH_COMPUTE_TYPE")
            or self._default_compute_type(self._device)
        )

        self._batch_size = (
            self._env_int("SPEECH_BATCH_SIZE", default=8)
            if batch_size is None
            else batch_size
        )

        if self._batch_size <= 0:
            raise ValueError("SPEECH_BATCH_SIZE deve ser >= 1.")

        self._hf_token = (
            hf_token
            if hf_token is not None
            else os.getenv("HF_TOKEN")
        )

    @property
    def provider_name(self) -> str:
        return "whisperx"

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def model_version(self) -> str | None:
        try:
            from importlib.metadata import version

            package_version = version("whisperx")
            if package_version:
                return package_version
        except Exception:
            pass

        try:
            import whisperx

            module_version = getattr(whisperx, "__version__", None)
            if isinstance(module_version, str) and module_version.strip():
                return module_version.strip()
        except Exception:
            pass

        return None

    @property
    def device(self) -> str:
        return self._device

    @property
    def compute_type(self) -> str:
        return self._compute_type

    @property
    def batch_size(self) -> int:
        return self._batch_size

    @staticmethod
    def _env_int(name: str, *, default: int) -> int:
        value = os.getenv(name)

        if value is None or not value.strip():
            return default

        parsed = int(value)

        if parsed <= 0:
            raise ValueError(f"{name} precisa ser > 0.")

        return parsed

    @staticmethod
    def _detect_device() -> str:
        try:
            import torch

            return "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:
            return "cpu"

    @staticmethod
    def _default_compute_type(device: str) -> str:
        return "float16" if device == "cuda" else "int8"

    @staticmethod
    def _probe_duration(source_path: Path) -> float:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(source_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        value = float(result.stdout.strip())

        if value <= 0:
            raise ValueError(
                f"Duração inválida detectada por ffprobe: {value}"
            )

        return value

    @staticmethod
    def _safe_float(
        value: Any,
        *,
        default: float | None = None,
    ) -> float | None:
        if isinstance(value, bool):
            return default

        if isinstance(value, (int, float)):
            return float(value)

        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @classmethod
    def _word_confidence(cls, word: dict[str, Any]) -> float | None:
        for key in (
            "confidence",
            "score",
            "probability",
        ):
            value = cls._safe_float(word.get(key))

            if value is not None and 0.0 <= value <= 1.0:
                return value

        return None

    @classmethod
    def _segment_confidence(
        cls,
        segment: dict[str, Any],
        words: list[SpeechWord],
    ) -> float | None:
        for key in (
            "confidence",
            "score",
        ):
            value = cls._safe_float(segment.get(key))

            if value is not None and 0.0 <= value <= 1.0:
                return value

        confidences = [
            word.confidence
            for word in words
            if word.confidence is not None
        ]

        if not confidences:
            return None

        return sum(confidences) / len(confidences)

    @staticmethod
    def _timestamp_confidence(
        segments: list[SpeechSegment],
        *,
        alignment_completed: bool,
    ) -> float:
        """
        Representa a integridade dos word timestamps após forced alignment.

        O valor só pode ser positivo quando o alignment realmente foi
        concluído e todos os segmentos possuem palavras com timestamps
        válidos.
        """
        if not alignment_completed or not segments:
            return 0.0

        aligned_segments = 0

        for segment in segments:
            if not segment.words:
                continue

            valid_words = all(
                word.start_seconds >= 0
                and word.end_seconds > word.start_seconds
                for word in segment.words
            )

            if valid_words:
                aligned_segments += 1

        return 1.0 if aligned_segments == len(segments) else 0.0

    @classmethod
    def _transcription_confidence(
        cls,
        raw_segments: list[dict[str, Any]],
        segments: list[SpeechSegment],
    ) -> float:
        word_confidences: list[float] = []

        for raw, normalized in zip(raw_segments, segments):
            raw_confidence = None

            for key in ("confidence", "score"):
                value = cls._safe_float(raw.get(key))
                if value is not None and 0.0 <= value <= 1.0:
                    raw_confidence = value
                    break

            if raw_confidence is not None and not normalized.words:
                word_confidences.append(raw_confidence)
                continue

            word_confidences.extend(
                word.confidence
                for word in normalized.words
                if word.confidence is not None
            )

        if not word_confidences:
            return 0.0

        return sum(word_confidences) / len(word_confidences)

    @staticmethod
    def _extract_language_probability(
        result: dict[str, Any],
    ) -> float:
        for key in (
            "language_probability",
            "language_prob",
        ):
            value = result.get(key)

            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return max(0.0, min(1.0, float(value)))

        return 0.0

    @staticmethod
    def _extract_speaker(segment: dict[str, Any]) -> str | None:
        speaker = segment.get("speaker")

        if speaker is None:
            speaker = segment.get("speaker_id")

        if speaker is None:
            return None

        speaker = str(speaker).strip()

        return speaker or None

    @classmethod
    def _normalize_words(
        cls,
        segment: dict[str, Any],
    ) -> tuple[SpeechWord, ...]:
        words_payload = segment.get("words") or []

        if not isinstance(words_payload, list):
            return ()

        normalized: list[SpeechWord] = []

        for word in words_payload:
            if not isinstance(word, dict):
                continue

            text = str(word.get("word") or word.get("text") or "").strip()

            if not text:
                continue

            start = cls._safe_float(word.get("start"))
            end = cls._safe_float(word.get("end"))

            if start is None or end is None:
                continue

            if start < 0 or end <= start:
                continue

            normalized.append(
                SpeechWord(
                    text=text,
                    start_seconds=start,
                    end_seconds=end,
                    confidence=cls._word_confidence(word),
                )
            )

        return tuple(normalized)

    @classmethod
    def _normalize_segments(
        cls,
        raw_segments: list[dict[str, Any]],
    ) -> tuple[SpeechSegment, ...]:
        normalized: list[SpeechSegment] = []

        for index, segment in enumerate(raw_segments):
            if not isinstance(segment, dict):
                continue

            text = str(segment.get("text") or "").strip()

            if not text:
                continue

            start = cls._safe_float(segment.get("start"))
            end = cls._safe_float(segment.get("end"))

            if start is None or end is None:
                continue

            if start < 0 or end <= start:
                continue

            words = cls._normalize_words(segment)

            normalized.append(
                SpeechSegment(
                    segment_id=f"segment-{index:06d}",
                    start_seconds=start,
                    end_seconds=end,
                    text=text,
                    speaker_id=cls._extract_speaker(segment),
                    words=words,
                )
            )

        return tuple(normalized)

    @staticmethod
    def _build_speakers(
        segments: tuple[SpeechSegment, ...],
    ) -> tuple[SpeechSpeaker, ...]:
        references: dict[str, list[str]] = {}

        for segment in segments:
            if segment.speaker_id is None:
                continue

            references.setdefault(
                segment.speaker_id,
                [],
            ).append(segment.segment_id)

        return tuple(
            SpeechSpeaker(
                speaker_id=speaker_id,
                label=None,
                segments=tuple(segment_ids),
                confidence=None,
            )
            for speaker_id, segment_ids in sorted(
                references.items()
            )
        )

    @staticmethod
    def _calculate_speech_seconds(
        segments: tuple[SpeechSegment, ...],
    ) -> float:
        """
        Soma união temporal dos segmentos.

        Segmentos sobrepostos entre speakers não são somados duas vezes.
        """

        intervals = sorted(
            (
                segment.start_seconds,
                segment.end_seconds,
            )
            for segment in segments
        )

        if not intervals:
            return 0.0

        total = 0.0
        current_start, current_end = intervals[0]

        for start, end in intervals[1:]:
            if start <= current_end:
                current_end = max(current_end, end)
                continue

            total += current_end - current_start
            current_start = start
            current_end = end

        total += current_end - current_start

        return total

    @staticmethod
    def _calculate_wpm(
        segments: tuple[SpeechSegment, ...],
        speech_seconds: float,
    ) -> float:
        if speech_seconds <= 0:
            return 0.0

        word_count = sum(
            len(segment.words)
            for segment in segments
        )

        if word_count == 0:
            word_count = sum(
                len(segment.text.split())
                for segment in segments
            )

        if word_count == 0:
            return 0.0

        return word_count / (speech_seconds / 60.0)

    def _load_whisperx(self):
        try:
            import whisperx
        except ImportError as exc:
            raise RuntimeError(
                "WhisperX não está instalado. "
                "Instale requirements/media.txt no worker."
            ) from exc

        return whisperx

    def _run_alignment(
        self,
        whisperx: Any,
        result: dict[str, Any],
        audio: Any,
        language: str,
    ) -> dict[str, Any]:
        model_a, metadata = whisperx.load_align_model(
            language_code=language,
            device=self._device,
        )

        return whisperx.align(
            result["segments"],
            model_a,
            metadata,
            audio,
            self._device,
            return_char_alignments=False,
        )

    def _run_diarization(
        self,
        whisperx: Any,
        audio: Any,
    ) -> Any | None:
        if not self._hf_token:
            return None

        try:
            from whisperx.diarize import DiarizationPipeline
        except ImportError as exc:
            raise RuntimeError(
                "WhisperX instalado não expõe o módulo whisperx.diarize."
            ) from exc

        pipeline = DiarizationPipeline(
            token=self._hf_token,
            device=self._device,
        )

        return pipeline(audio)

    def analyze(
        self,
        source_path: str | Path,
        *,
        language: str | None = None,
    ) -> SpeechAnalysis:
        path = Path(source_path)

        if not path.is_file():
            raise FileNotFoundError(
                f"Mídia para WhisperX não encontrada: {path}"
            )

        whisperx = self._load_whisperx()

        duration_seconds = self._probe_duration(path)

        audio = whisperx.load_audio(str(path))

        model = whisperx.load_model(
            self._model_name,
            self._device,
            compute_type=self._compute_type,
        )

        result = model.transcribe(
            audio,
            batch_size=self._batch_size,
            language=language,
        )

        detected_language = str(
            result.get("language")
            or language
            or ""
        ).strip()

        if not detected_language:
            raise RuntimeError(
                "WhisperX não determinou o idioma; "
                "forced alignment não pode prosseguir sem language code."
            )

        alignment_completed = False

        try:
            aligned_result = self._run_alignment(
                whisperx,
                result,
                audio,
                detected_language,
            )
            alignment_completed = True
        except Exception as exc:
            raise RuntimeError(
                "WhisperX forced alignment falhou; "
                "a análise não pode prosseguir sem word timestamps confiáveis."
            ) from exc

        diarize_segments = self._run_diarization(
            whisperx,
            audio,
        )

        if diarize_segments is not None:
            aligned_result = whisperx.assign_word_speakers(
                diarize_segments,
                aligned_result,
            )

        raw_segments = aligned_result.get("segments") or []

        if not isinstance(raw_segments, list):
            raise RuntimeError(
                "WhisperX retornou segments em formato inválido."
            )

        segments = self._normalize_segments(
            raw_segments,
        )

        if not segments:
            raise RuntimeError(
                "WhisperX não produziu segmentos de fala."
            )

        speakers = self._build_speakers(segments)

        speech_seconds = self._calculate_speech_seconds(
            segments,
        )

        words_per_minute = self._calculate_wpm(
            segments,
            speech_seconds,
        )

        transcription_confidence = self._transcription_confidence(
            raw_segments,
            list(segments),
        )

        timestamp_confidence = self._timestamp_confidence(
            list(segments),
            alignment_completed=alignment_completed,
        )

        speaker_confidence = None

        quality = SpeechQuality(
            transcription_confidence=transcription_confidence,
            timestamp_confidence=timestamp_confidence,
            speaker_confidence=speaker_confidence,
        )

        engine = SpeechEngine(
            provider=self.provider_name,
            model=self.model_name,
            version=self.model_version,
        )

        return SpeechAnalysis(
            source_path=str(path),
            duration_seconds=duration_seconds,
            source_language=detected_language,
            language_probability=self._extract_language_probability(
                result,
            ),
            segments=segments,
            speakers=speakers,
            speech_seconds=speech_seconds,
            words_per_minute=words_per_minute,
            quality=quality,
            engine=engine,
        )
