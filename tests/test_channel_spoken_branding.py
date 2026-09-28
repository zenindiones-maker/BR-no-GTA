from __future__ import annotations

import copy
import pytest

from app.services.channel_spoken_branding_service import (
    CLOSING_LINE, OFFICIAL_INTRO_ASSET_ID, OFFICIAL_PROVIDER,
    OFFICIAL_VOICE_IDENTITY_ID, OFFICIAL_VOICE_SHORT_NAME, OPENING_PREFIX,
    SELECTED_CLOSING_TAKE_ID, SELECTED_OPENING_TAKE_ID,
    build_spoken_branding_contract, validate_job_spoken_branding,
    validate_spoken_branding_contract,
)

THEME = "fatos, tecnologia e novidades de GTA 6"


def _job():
    return {
        "brand_assets": [
            {"asset_id": 1, "asset_type": "intro"},
            {"asset_id": 2, "asset_type": "watermark"},
        ],
        "spoken_branding": build_spoken_branding_contract(theme=THEME),
        "narration": {
            "voice": OFFICIAL_VOICE_IDENTITY_ID,
            "voice_identity_id": OFFICIAL_VOICE_IDENTITY_ID,
        },
        "script_sections": [{"section_id": "A01", "role": "hook"}],
    }


def test_canonical_branding_is_owner_only():
    contract = build_spoken_branding_contract(theme=THEME)
    assert contract["intro_asset_id"] == OFFICIAL_INTRO_ASSET_ID == 1
    assert contract["opening_text"] == f"{OPENING_PREFIX}{THEME}!"
    assert contract["closing_line"] == CLOSING_LINE
    assert contract["official_voice_profile"] == "BR_OWNER_V1"
    assert contract["voice_short_name"] == OFFICIAL_VOICE_SHORT_NAME == "BR_OWNER_V1"
    assert contract["provider"] == OFFICIAL_PROVIDER == "private-voice-runtime"
    assert [item["take_id"] for item in contract["take_profiles"]] == ["BR_OWNER_V1-dynamic"]
    assert contract["selected_opening_take_id"] == SELECTED_OPENING_TAKE_ID
    assert contract["selected_closing_fallback_take_id"] == SELECTED_CLOSING_TAKE_ID


def test_contract_fails_closed_on_non_owner_mutation():
    contract = build_spoken_branding_contract(theme=THEME)
    contract["voice_short_name"] = "__forbidden_alternate_voice__"
    with pytest.raises(ValueError, match="contract mismatch"):
        validate_spoken_branding_contract(contract)


def test_job_rejects_any_non_owner_voice_and_intro_omission():
    job = _job()
    assert validate_job_spoken_branding(job)["opening_theme"] == THEME
    changed = copy.deepcopy(job)
    changed["narration"]["voice"] = "__forbidden_alternate_voice__"
    changed["narration"]["voice_identity_id"] = "__forbidden_alternate_identity__"
    with pytest.raises(ValueError, match="BR_OWNER_V1"):
        validate_job_spoken_branding(changed)
    changed = copy.deepcopy(job)
    changed["brand_assets"][0]["asset_id"] = 7
    with pytest.raises(ValueError, match="ASSET_ID=1"):
        validate_job_spoken_branding(changed)


def test_editorial_hook_remains_required():
    job = _job()
    job["script_sections"][0]["role"] = "body"
    with pytest.raises(ValueError, match="editorial hook"):
        validate_job_spoken_branding(job)
