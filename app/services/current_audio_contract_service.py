from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from app.services.channel_spoken_branding_service import (
    HUMAN_APPROVED_FINAL_END_SAMPLE_ID,
    HUMAN_APPROVED_OPENING_REFERENCE,
    OFFICIAL_VOICE_BLIND_ID,
    OFFICIAL_VOICE_SHORT_NAME,
    PRODUCTION_CLOSING_POLICY,
    SELECTED_OPENING_TAKE_ID,
    SPOKEN_BRANDING_CONTRACT_VERSION,
    TAKE_PROFILES,
)

ROOT = Path(__file__).resolve().parents[2]
EXPECTED_APPROVED_G_SHA256 = "9e2e7a2d9717f460dd45cf0d07e96a4596e4f61372c6d87028b8809a052c59ca"


class CurrentAudioContractError(RuntimeError):
    pass


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise CurrentAudioContractError(f"invalid JSON contract: {path}")
    return value


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def current_audio_contract() -> dict[str, Any]:
    profile = _load(ROOT / ".run001/official-narration-profile.json")
    lexicon = _load(ROOT / "config/pronunciation_lexicon.json")
    approval = _load(ROOT / "assets/branding/audio/human-approval-manifest.json")
    approved_g = ROOT / "assets/branding/audio/g-brand-mixed-approved-20260919.mp3"
    closing = ROOT / "assets/branding/audio/closing-from-g-approved-20260919.flac"

    approved_g_sha = _sha256(approved_g)
    closing_sha = _sha256(closing)
    if approved_g_sha != EXPECTED_APPROVED_G_SHA256:
        raise CurrentAudioContractError("human-approved G closing asset hash mismatch")
    approved = approval.get("approved_reference") or {}
    canonical_closing = approval.get("canonical_closing_asset") or {}
    if approved.get("sha256") != approved_g_sha:
        raise CurrentAudioContractError("approval manifest G closing hash mismatch")
    if canonical_closing.get("sha256") != closing_sha:
        raise CurrentAudioContractError("derived closing asset hash mismatch")

    entries = {
        str(item.get("identity")): item
        for item in lexicon.get("entries") or []
        if isinstance(item, dict)
    }
    gta = entries.get("gta-6") or {}
    vice = entries.get("vice-city") or {}
    lucia = entries.get("character-lucia") or {}
    runtime = profile.get("runtime_voice_policy") or {}
    take = next(
        (item for item in TAKE_PROFILES if item.get("take_id") == SELECTED_OPENING_TAKE_ID),
        None,
    )
    if not take:
        raise CurrentAudioContractError("approved Fluid 2 opening profile missing")

    payload = {
        "OFFICIAL_VOICE": OFFICIAL_VOICE_BLIND_ID,
        "VOICE_SHORT_NAME": OFFICIAL_VOICE_SHORT_NAME,
        "SINGLE_VOICE_ONLY": runtime.get("single_voice_only") is True,
        "ALTERNATIVE_VOICE_CASTING": (
            "DISABLED" if runtime.get("alternative_voice_casting_enabled") is False else "ENABLED"
        ),
        "SPOKEN_BRANDING_CONTRACT": SPOKEN_BRANDING_CONTRACT_VERSION,
        "OPENING_REFERENCE": HUMAN_APPROVED_OPENING_REFERENCE,
        "OPENING_TAKE": SELECTED_OPENING_TAKE_ID,
        "OPENING_RATE": take.get("rate"),
        "OPENING_PITCH": take.get("pitch"),
        "CLOSING_ASSET": HUMAN_APPROVED_FINAL_END_SAMPLE_ID,
        "CLOSING_ASSET_POLICY": "IMMUTABLE_HUMAN_APPROVED",
        "CLOSING_POLICY_INTERNAL": PRODUCTION_CLOSING_POLICY,
        "APPROVED_G_SHA256": approved_g_sha,
        "DERIVED_CLOSING_SHA256": closing_sha,
        "DEFAULT_NARRATION_LOCALE": lexicon.get("default_locale"),
        "ONLY_FORCED_EN_US_TERM": (lexicon.get("policy") or {}).get("only_forced_en_us_term"),
        "GTA_6_SYNTHESIS": gta.get("synthesis_text"),
        "VICE_CITY_LOCALE": vice.get("locale"),
        "VICE_CITY_TARGET_IPA": vice.get("target_ipa"),
        "PRONUNCIATION_LEXICON_VERSION": lexicon.get("version"),
        "LUCIA_SYNTHESIS_ALIAS": lucia.get("synthesis_text"),
        "OFFICIAL_NARRATION_PROFILE_ID": profile.get("profile_id"),
    }
    expected = {
        "OFFICIAL_VOICE": "Voice B",
        "VOICE_SHORT_NAME": "pt-BR-ThalitaMultilingualNeural",
        "SINGLE_VOICE_ONLY": True,
        "ALTERNATIVE_VOICE_CASTING": "DISABLED",
        "SPOKEN_BRANDING_CONTRACT": "br-no-gta-spoken-branding/v3",
        "OPENING_REFERENCE": "I-opening-fluid-2.mp3",
        "OPENING_TAKE": "take-2",
        "OPENING_RATE": "+3%",
        "OPENING_PITCH": "+1Hz",
        "CLOSING_ASSET": "G-brand-mixed",
        "CLOSING_ASSET_POLICY": "IMMUTABLE_HUMAN_APPROVED",
        "DEFAULT_NARRATION_LOCALE": "pt-BR",
        "ONLY_FORCED_EN_US_TERM": "Vice City",
        "GTA_6_SYNTHESIS": "gê tê á seis",
        "VICE_CITY_LOCALE": "en-US",
        "VICE_CITY_TARGET_IPA": "vaɪs ˈsɪti",
        "PRONUNCIATION_LEXICON_VERSION": "2026.09.20.3-human-lucia",
        "LUCIA_SYNTHESIS_ALIAS": "Lucía",
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            raise CurrentAudioContractError(
                f"current audio contract mismatch for {key}: {payload.get(key)!r}"
            )
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        **payload,
        "CURRENT_AUDIO_CONTRACT_FINGERPRINT": hashlib.sha256(
            canonical.encode("utf-8")
        ).hexdigest(),
    }
