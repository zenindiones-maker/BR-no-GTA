from __future__ import annotations

import json
from pathlib import Path

from app.services.channel_spoken_branding_service import (
    OFFICIAL_VOICE_BLIND_ID,
    OFFICIAL_VOICE_SHORT_NAME,
    build_spoken_branding_contract,
)


ROOT = Path(__file__).resolve().parents[1]


def test_runtime_has_one_canonical_voice_and_no_casting_surface():
    profile = json.loads(
        (ROOT / ".run001" / "official-narration-profile.json").read_text(encoding="utf-8")
    )
    policy = profile["runtime_voice_policy"]

    assert OFFICIAL_VOICE_BLIND_ID == "Voice B"
    assert OFFICIAL_VOICE_SHORT_NAME == "pt-BR-ThalitaMultilingualNeural"
    assert policy["single_voice_only"] is True
    assert policy["allowed_short_names"] == [OFFICIAL_VOICE_SHORT_NAME]
    assert policy["alternative_voice_casting_enabled"] is False
    assert policy["automatic_voice_substitution_allowed"] is False

    forbidden_paths = [
        ROOT / "app" / "services" / "voice_casting_service.py",
        ROOT / "app" / "services" / "voice_casting_round2_service.py",
        ROOT / ".github" / "workflows" / "ptbr-voice-casting-round1.yml",
        ROOT / ".github" / "workflows" / "ptbr-voice-casting-round2.yml",
        ROOT / "scripts" / "ptbr_voice_casting.py",
        ROOT / "scripts" / "ptbr_voice_casting_round2.py",
        ROOT / "scripts" / "send_voice_casting_round1_telegram.py",
        ROOT / "scripts" / "send_voice_casting_round2_telegram.py",
    ]
    assert all(not path.exists() for path in forbidden_paths)

    services_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "app" / "services").glob("*.py")
    )
    assert "edge_tts.list_voices" not in services_text
    assert "collect_ptbr_edge_voice_inventory" not in services_text


def test_production_branding_contains_only_human_approved_runtime_assets():
    contract = build_spoken_branding_contract(
        theme="fatos, vazamentos, tecnologia e rumores de GTA 6"
    )

    assert contract["voice_short_name"] == OFFICIAL_VOICE_SHORT_NAME
    assert contract["production_opening_take_ids"] == ["take-2"]
    assert contract["production_closing_policy"] == "immutable-human-approved-G-brand-mixed"
    assert len(contract["take_profiles"]) == 1

    fluid2 = contract["take_profiles"][0]
    assert fluid2 == {
        "take_id": "take-2",
        "rate": "+3%",
        "pitch": "+1Hz",
        "role": "human-approved-fluid2-prosody",
        "runtime_enabled": True,
    }

    approved_close = (
        ROOT / "assets" / "branding" / "audio" / "closing-from-g-approved-20260919.flac"
    )
    assert approved_close.is_file()
    assert approved_close.stat().st_size > 0


def test_brand_audio_runtime_does_not_regenerate_review_takes():
    source = (ROOT / "app" / "services" / "brand_audio_service.py").read_text(
        encoding="utf-8"
    )
    assert 'for take in contract["take_profiles"]' not in source
    assert 'BUNDLE_VERSION="brand-audio-bundle/v3"' in source
    assert "_materialize_approved_closing" in source
    assert '"G-brand-mixed"' in source
