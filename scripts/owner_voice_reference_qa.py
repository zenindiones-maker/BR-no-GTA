from __future__ import annotations

from typing import Any, Iterable, Mapping

from app.services.owner_voice_audio_quality_service import score_owner_reference_quality
from app.services.owner_voice_clone_service import select_owner_reference

VOICE_IDENTITY_ID = "BR_OWNER_V1"
REFERENCE_SOURCE = "TELEGRAM"
EXTERNAL_LOCALE = "pt-BR"
