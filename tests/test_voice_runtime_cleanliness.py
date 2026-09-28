from __future__ import annotations

import json
from pathlib import Path

from app.services.channel_spoken_branding_service import (
    OFFICIAL_VOICE_BLIND_ID,
    OFFICIAL_VOICE_SHORT_NAME,
    build_spoken_branding_contract,
)


ROOT = Path(__file__).resolve().parents[1]


def test_runtime_has_one_canonical_owner_voice_and_legacy_profile_is_historical_only():
    enrollment = json.loads(
        (ROOT / "config" / "voice_owner_enrollment_v1.json").read_text(encoding="utf-8")
    )
    legacy = json.loads(
        (ROOT / ".run001" / "official-narration-profile.json").read_text(encoding="utf-8")
    )

    assert OFFICIAL_VOICE_BLIND_ID == "BR_OWNER_V1"
    assert OFFICIAL_VOICE_SHORT_NAME == "BR_OWNER_V1"
    assert enrollment["official_voice"] == "BR_OWNER_V1"
    assert enrollment["legacy_voice_b_runtime_enabled"] is False
    assert enrollment["legacy_voice_b_fallback_allowed"] is False
    assert legacy["voice"]["blind_id"] == "Voice B"
    assert legacy["provider"] == "edge-tts"
    assert legacy["version"] == "official-narration-profile/v2"

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


def test_production_branding_contains_only_owner_voice_runtime_identity():
    contract = build_spoken_branding_contract(
        theme="fatos, vazamentos, tecnologia e rumores de GTA 6"
    )

    assert contract["voice_short_name"] == OFFICIAL_VOICE_SHORT_NAME == "BR_OWNER_V1"
    assert contract["production_opening_take_ids"] == ["BR_OWNER_V1-dynamic"]
    assert contract["production_closing_policy"] == "owner-voice-dynamic-private-runtime"
    assert contract["human_approved_opening_reference"] is None
    assert contract["human_approved_final_end_sample_id"] is None
    assert len(contract["take_profiles"]) == 1
    assert contract["take_profiles"][0]["take_id"] == "BR_OWNER_V1-dynamic"
    assert contract["take_profiles"][0]["runtime_enabled"] is True


def test_brand_audio_runtime_has_no_legacy_voice_b_or_edge_synthesis_path():
    source = (ROOT / "app" / "services" / "brand_audio_service.py").read_text(
        encoding="utf-8"
    )
    assert 'BUNDLE_VERSION="brand-audio-bundle/v4"' in source
    assert "_materialize_approved_closing" not in source
    assert '"G-brand-mixed"' not in source
    assert "synthesize_edge_plan" not in source
    assert "edge_tts" not in source
    assert "OWNER_VOICE_RUNTIME_REQUIRED" in source
    assert "BR_OWNER_V1" in source

def test_historical_pronunciation_script_fails_closed_under_owner_only_policy():
    source = (ROOT / "scripts" / "pronunciation_proof.py").read_text(encoding="utf-8")
    assert "LEGACY_VOICE_B_PRONUNCIATION_RUNTIME_DISABLED" in source


def test_legacy_voice_b_pronunciation_workflow_is_not_an_active_synthesis_surface():
    from pathlib import Path
    workflow = Path(".github/workflows/pronunciation-proof.yml").read_text(encoding="utf-8")
    assert "Generate real Voice B pronunciation proof" not in workflow
    assert "edge-tts==7.2.8" not in workflow
    assert "pt-BR-ThalitaMultilingualNeural" not in workflow
    assert "BR_OWNER_V1" in workflow
    assert "legacy_voice_b_fallback_allowed" in workflow
