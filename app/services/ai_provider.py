from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class AIUsage:
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    reasoning_tokens: int | None = None


@dataclass(frozen=True)
class AIResponse:
    text: str
    provider: str | None = None
    model: str | None = None
    reasoning_content: str | None = None
    usage: AIUsage | None = None
    finish_reason: str | None = None


class AIProviderError(RuntimeError):
    """Base error for AI provider failures."""


class AIProvider(Protocol):
    def generate(self, prompt: str) -> AIResponse:
        """Generate a response from a text prompt."""
        ...
