from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CaptionDecision:
    text: str
    start_seconds: float
    duration_seconds: float
    highlighted_words: tuple[str, ...]
    position: str
    font_size: int
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "start_seconds": self.start_seconds,
            "duration_seconds": self.duration_seconds,
            "highlighted_words": list(self.highlighted_words),
            "position": self.position,
            "font_size": self.font_size,
            "reason": self.reason,
        }


def build_caption_plan(
    *,
    text: str,
    start_seconds: float,
    duration_seconds: float,
    font_size: int = 52,
    position: str = "safe_center",
    highlighted_words: list[str] | None = None,
) -> CaptionDecision | None:
    text = str(text or "").strip()

    if not text:
        return None

    words = tuple(
        word
        for word in (highlighted_words or [])
        if isinstance(word, str) and word.strip()
    )

    return CaptionDecision(
        text=text,
        start_seconds=float(start_seconds),
        duration_seconds=float(duration_seconds),
        highlighted_words=words,
        position=position,
        font_size=int(font_size),
        reason="legenda dirigida por narrativa e área segura",
    )
