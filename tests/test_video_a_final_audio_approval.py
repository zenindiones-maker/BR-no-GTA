from __future__ import annotations

import json
from pathlib import Path

from app.services.current_audio_contract_service import current_audio_contract

ROOT = Path(__file__).resolve().parents[1]


def test_legacy_g_brand_approval_cannot_activate_current_owner_voice():
    assert not (ROOT / ".run001" / "video-a-final-audio-approval.json").exists()
    contract = current_audio_contract()
    enrollment = json.loads((ROOT / "config" / "voice_owner_enrollment_v1.json").read_text(encoding="utf-8"))
    assert contract["VOICE_IDENTITY_ID"] == "BR_OWNER_V1"
    assert contract["OWNER_REFERENCE_SOURCE"] == "TELEGRAM"
    assert contract["OWNER_REFERENCE_COUNT"] == 0
    assert contract["OWNER_REFERENCE_READY"] is False
    assert enrollment["runtime_activation_status"] == "BLOCKED_HUMAN_VOICE_REVIEW"
    assert enrollment["promotion_allowed"] is False
    assert enrollment["latest_human_voice_review"] == "REJECTED"
    assert enrollment["latest_voice_identity_match"] == "FAIL"
    assert enrollment["latest_ptbr_accent_review"] == "FAIL"
    assert enrollment["generic_voice_fallback"] is False
    assert enrollment["provider_preset_voice_allowed"] is False
    assert enrollment["provider_default_voice_allowed"] is False
