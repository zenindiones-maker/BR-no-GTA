from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class AIResponse:
    text: str


class AIProvider(Protocol):
    def generate(self, prompt: str) -> AIResponse:
        """Generate a response from a text prompt."""
        ...
