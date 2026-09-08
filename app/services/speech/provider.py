from __future__ import annotations

from pathlib import Path
from typing import Protocol

from app.services.speech.models import SpeechAnalysis


class SpeechProvider(Protocol):
    """Contrato provider-neutral para análise de fala."""

    @property
    def provider_name(self) -> str:
        ...

    @property
    def model_name(self) -> str:
        ...

    @property
    def model_version(self) -> str | None:
        ...

    def analyze(
        self,
        source_path: str | Path,
        *,
        language: str | None = None,
    ) -> SpeechAnalysis:
        ...
