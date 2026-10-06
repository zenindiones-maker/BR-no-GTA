from __future__ import annotations

from typing import Any

VOICE_IDENTITY_ID="BR_OWNER_V1"
REFERENCE_SOURCE="TELEGRAM_HUMAN_OWNER"
HUMAN_IDENTITY_AUDITION="HUMAN_IDENTITY_AUDITION"
LONG_FORM_VOICE_QUALIFICATION="LONG_FORM_VOICE_QUALIFICATION"
_ALLOWED={"A","B","C"}


def build_long_form_qualification(*,human_approved: str | None) -> dict[str,Any]:
    selected=str(human_approved or "").strip().upper()
    if selected not in _ALLOWED:
        raise ValueError("HUMAN_APPROVED_CANDIDATE_REQUIRED")
    from app.services.owner_voice_human_audition_pack_service import build_audition_script
    text=build_audition_script(theme="as novidades de GTA 6")
    return {
        "stage":LONG_FORM_VOICE_QUALIFICATION,
        "human_approved":selected,
        "voice_identity_id":VOICE_IDENTITY_ID,
        "reference_source":REFERENCE_SOURCE,
        "text":text,
        "human_identity_gate":"PASSED_BY_OWNER",
        "production_activation":False,
    }
