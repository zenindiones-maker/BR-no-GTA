from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class AIResponse:
    text: str


class AIProviderError(RuntimeError):
    """Base error for AI provider failures."""


class AIProvider(Protocol):
    def generate(self, prompt: str) -> AIResponse:
        """Generate a response from a text prompt."""
        ...
