from __future__ import annotations

from pathlib import Path

from app.services.speech.models import SpeechAnalysis
from app.services.speech.provider import SpeechProvider
from app.services.speech.qa import SpeechQAResult, validate_speech_analysis


class SpeechAnalysisError(RuntimeError):
    """Erro de análise ou validação de fala."""


def analyze_speech(
    source_path: str | Path,
    *,
    provider: SpeechProvider,
    language: str | None = None,
) -> tuple[SpeechAnalysis, SpeechQAResult]:
    path = Path(source_path)

    if not path.is_file():
        raise SpeechAnalysisError(
            f"Mídia para análise de fala não encontrada: {path}"
        )

    analysis = provider.analyze(
        path,
        language=language,
    )

    qa = validate_speech_analysis(analysis)

    if not qa.passed:
        raise SpeechAnalysisError(
            "Speech Analysis QA falhou: "
            + ", ".join(qa.issues)
        )

    return analysis, qa
