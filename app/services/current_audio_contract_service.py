from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from app.services.channel_spoken_branding_service import (
    OFFICIAL_PITCH,
    OFFICIAL_RATE,
    OFFICIAL_VOICE_IDENTITY_ID,
    SELECTED_CLOSING_TAKE_ID,
    SELECTED_OPENING_TAKE_ID,
    SPOKEN_BRANDING_CONTRACT_VERSION,
)

ROOT = Path(__file__).resolve().parents[2]
OWNER_VOICE_POLICY = "OWNER_VOICE_ONLY"


class CurrentAudioContractError(RuntimeError):
    pass


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise CurrentAudioContractError(f"invalid JSON contract: {path}")
    return value


def current_audio_contract() -> dict[str, Any]:
    enrollment = _load(ROOT / "config/voice_owner_enrollment_v1.json")
    lexicon = _load(ROOT / "config/pronunciation_lexicon.json")
    if enrollment.get("voice_identity_id") != OFFICIAL_VOICE_IDENTITY_ID:
        raise CurrentAudioContractError("owner voice identity mismatch")
    if enrollment.get("official_voice") != OFFICIAL_VOICE_IDENTITY_ID:
        raise CurrentAudioContractError("official owner voice mismatch")
    if enrollment.get("voice_policy") != OWNER_VOICE_POLICY:
        raise CurrentAudioContractError("owner-only voice policy is required")
    if enrollment.get("active_voice_identities") != [OFFICIAL_VOICE_IDENTITY_ID]:
        raise CurrentAudioContractError("exactly one owner voice identity must be active")
    if enrollment.get("consent_status") != "APPROVED":
        raise CurrentAudioContractError("owner voice consent must be approved")

    entries = {
        str(item.get("identity")): item
        for item in lexicon.get("entries") or []
        if isinstance(item, dict)
    }
    gta = entries.get("gta-6") or {}
    vice = entries.get("vice-city") or {}
    lucia = entries.get("character-lucia") or {}
    materialized = int(enrollment.get("materialized_reference_count") or 0)
    reference_ready = (
        materialized > 0
        and enrollment.get("reference_materialization_status")
        == "PRIVATE_REFERENCE_MATERIALIZED"
    )

    payload = {
        "OFFICIAL_VOICE": OFFICIAL_VOICE_IDENTITY_ID,
        "VOICE_SHORT_NAME": OFFICIAL_VOICE_IDENTITY_ID,
        "VOICE_IDENTITY_ID": OFFICIAL_VOICE_IDENTITY_ID,
        "VOICE_POLICY": OWNER_VOICE_POLICY,
        "SINGLE_VOICE_ONLY": True,
        "ALTERNATIVE_VOICE_CASTING": "DISABLED",
        "ACTIVE_VOICE_IDENTITIES": [OFFICIAL_VOICE_IDENTITY_ID],
        "OWNER_REFERENCE_SOURCE": enrollment.get("reference_source"),
        "OWNER_REFERENCE_STATUS": enrollment.get("reference_materialization_status"),
        "OWNER_REFERENCE_COUNT": materialized,
        "OWNER_REFERENCE_READY": reference_ready,
        "SPOKEN_BRANDING_CONTRACT": SPOKEN_BRANDING_CONTRACT_VERSION,
        "OPENING_REFERENCE": None,
        "OPENING_TAKE": SELECTED_OPENING_TAKE_ID,
        "OPENING_RATE": OFFICIAL_RATE,
        "OPENING_PITCH": OFFICIAL_PITCH,
        "CLOSING_ASSET": None,
        "CLOSING_TAKE": SELECTED_CLOSING_TAKE_ID,
        "CLOSING_ASSET_POLICY": "SYNTHESIZE_WITH_OWNER_IDENTITY",
        "DEFAULT_NARRATION_LOCALE": lexicon.get("default_locale"),
        "ONLY_FORCED_EN_US_TERM": (lexicon.get("policy") or {}).get("only_forced_en_us_term"),
        "GTA_6_SYNTHESIS": gta.get("synthesis_text"),
        "VICE_CITY_LOCALE": vice.get("locale"),
        "VICE_CITY_TARGET_IPA": vice.get("target_ipa"),
        "PRONUNCIATION_LEXICON_VERSION": lexicon.get("version"),
        "LUCIA_SYNTHESIS_ALIAS": lucia.get("synthesis_text"),
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        **payload,
        "CURRENT_AUDIO_CONTRACT_FINGERPRINT": hashlib.sha256(
            canonical.encode("utf-8")
        ).hexdigest(),
    }
