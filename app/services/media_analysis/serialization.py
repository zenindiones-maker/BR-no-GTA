from __future__ import annotations

from dataclasses import asdict

from app.services.media_analysis.models import (
    MediaKnowledge,
)


def serialize_media_knowledge(
    knowledge: MediaKnowledge,
) -> dict:
    """Converte MediaKnowledge para uma estrutura serializável."""

    return asdict(knowledge)
