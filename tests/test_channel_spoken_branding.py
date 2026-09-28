from __future__ import annotations

import copy

import pytest

from app.services.channel_spoken_branding_service import (
    CLOSING_LINE,
    OFFICIAL_INTRO_ASSET_ID,
    ALLOW_LEGACY_VOICE_B_FALLBACK,
    LEGACY_CONTROL_VOICE_BLIND_ID,
    OFFICIAL_VOICE_IDENTITY_ID,
    OFFICIAL_VOICE_SHORT_NAME,
    OPENING_PREFIX,
    SELECTED_CLOSING_TAKE_ID,
    SELECTED_OPENING_TAKE_ID,
    build_spoken_branding_contract,
    validate_job_spoken_branding,
    validate_spoken_branding_contract,
)


THEME="fatos, vazamentos, tecnologia e rumores de GTA 6"


def _job():
    return {
        "brand_assets":[
            {"asset_id":1,"asset_type":"intro"},
            {"asset_id":2,"asset_type":"watermark"},
        ],
        "spoken_branding":build_spoken_branding_contract(theme=THEME),
        "narration":{
            "voice":OFFICIAL_VOICE_SHORT_NAME,
            "voice_identity_id":OFFICIAL_VOICE_IDENTITY_ID,
        },
        "script_sections":[{"section_id":"A01","role":"hook"}],
    }


def test_canonical_opening_and_closing_are_exact():
    contract=build_spoken_branding_contract(theme=THEME)
    assert contract["intro_asset_id"]==OFFICIAL_INTRO_ASSET_ID==1
    assert contract["opening_text"]==f"{OPENING_PREFIX}{THEME}!"
    assert contract["closing_line"]==CLOSING_LINE=="E BR não dorme em Vice City"
    assert contract["timeline_order"][:3]==[
        "official_intro","spoken_channel_opening","editorial_hook"
    ]
    assert contract["timeline_order"][-1]=="spoken_channel_closing"
    assert contract["official_voice_profile"]=="BR_OWNER_V1"
    assert contract["provider"]=="private-voice-runtime"
    assert ALLOW_LEGACY_VOICE_B_FALLBACK is False
    assert LEGACY_CONTROL_VOICE_BLIND_ID=="Voice B"
    assert contract["voice_short_name"]==OFFICIAL_VOICE_SHORT_NAME


def test_only_theme_is_variable_in_opening_template():
    a=build_spoken_branding_contract(theme="tema A")
    b=build_spoken_branding_contract(theme="tema B")
    assert a["opening_fixed_prefix"]==b["opening_fixed_prefix"]==OPENING_PREFIX
    assert a["closing_line"]==b["closing_line"]==CLOSING_LINE
    assert a["opening_text"]==f"{OPENING_PREFIX}tema A!"
    assert b["opening_text"]==f"{OPENING_PREFIX}tema B!"


@pytest.mark.parametrize("field,value",[
    ("opening_text","Olá pessoal, hoje vamos falar de GTA!"),
    ("closing_line","Até o próximo vídeo"),
    ("voice_short_name","__forbidden_alternate_voice__"),
    ("intro_asset_id",99),
])
def test_contract_fails_closed_on_brand_mutation(field,value):
    contract=build_spoken_branding_contract(theme=THEME)
    contract[field]=value
    with pytest.raises(ValueError,match="contract mismatch"):
        validate_spoken_branding_contract(contract)


def test_job_rejects_legacy_voice_b_and_intro_omission():
    job=_job()
    assert validate_job_spoken_branding(job)["opening_theme"]==THEME

    changed=copy.deepcopy(job)
    changed["narration"]["voice"]="pt-BR-ThalitaMultilingualNeural"
    changed["narration"]["voice_identity_id"]="Voice B"
    with pytest.raises(ValueError,match="legacy Voice B|BR_OWNER_V1"):
        validate_job_spoken_branding(changed)

    changed=copy.deepcopy(job)
    changed["brand_assets"][0]["asset_id"]=7
    with pytest.raises(ValueError,match="ASSET_ID=1"):
        validate_job_spoken_branding(changed)


def test_editorial_hook_is_distinct_and_required_after_brand_opening():
    job=_job()
    job["script_sections"][0]["role"]="body"
    with pytest.raises(ValueError,match="editorial hook"):
        validate_job_spoken_branding(job)


def test_take_profiles_use_owner_voice_and_do_not_reuse_legacy_audio():
    contract=build_spoken_branding_contract(theme=THEME)
    assert [x["take_id"] for x in contract["take_profiles"]]==["BR_OWNER_V1-dynamic"]
    owner=contract["take_profiles"][0]
    assert owner["runtime_enabled"] is True
    assert owner["role"]=="owner-voice-canonical"
    assert contract["selected_take_id"]==SELECTED_OPENING_TAKE_ID=="BR_OWNER_V1-dynamic"
    assert contract["selected_opening_take_id"]=="BR_OWNER_V1-dynamic"
    assert contract["selected_closing_fallback_take_id"]==SELECTED_CLOSING_TAKE_ID=="BR_OWNER_V1-dynamic"
    assert contract["human_approved_opening_reference"] is None
    assert contract["human_approved_final_end_sample_id"] is None
    assert contract["production_opening_take_ids"]==["BR_OWNER_V1-dynamic"]
    assert contract["production_closing_policy"]=="owner-voice-dynamic-private-runtime"
    rule=contract["selection_rule"].lower()
    assert "br_owner_v1" in rule
    assert "voice b" in rule
    assert "cannot be selected" in rule
    assert contract["cache_policy"]["closing_fixed_reusable"] is True
