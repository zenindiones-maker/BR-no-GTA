from __future__ import annotations

import copy

import pytest

from app.services.channel_spoken_branding_service import (
    CLOSING_LINE,
    OFFICIAL_INTRO_ASSET_ID,
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
            "human_quality_baseline":"Voice B",
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
    assert contract["official_voice_profile"]=="Voice B"
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
    ("voice_short_name","pt-BR-AntonioNeural"),
    ("intro_asset_id",99),
])
def test_contract_fails_closed_on_brand_mutation(field,value):
    contract=build_spoken_branding_contract(theme=THEME)
    contract[field]=value
    with pytest.raises(ValueError,match="contract mismatch"):
        validate_spoken_branding_contract(contract)


def test_job_rejects_voice_b_substitution_and_intro_omission():
    job=_job()
    assert validate_job_spoken_branding(job)["opening_theme"]==THEME

    changed=copy.deepcopy(job)
    changed["narration"]["voice"]="pt-BR-AntonioNeural"
    with pytest.raises(ValueError,match="Voice B"):
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


def test_take_profiles_lock_human_approved_fluid2_opening_and_g_final_end():
    contract=build_spoken_branding_contract(theme=THEME)
    assert [x["take_id"] for x in contract["take_profiles"]]==["take-1","take-2","take-3"]
    fluid2=next(x for x in contract["take_profiles"] if x["take_id"]=="take-2")
    assert fluid2["rate"]=="+3%"
    assert fluid2["pitch"]=="+1Hz"
    assert fluid2["role"]=="human-approved-fluid2-prosody"
    assert contract["selected_take_id"]==SELECTED_OPENING_TAKE_ID=="take-2"
    assert contract["selected_opening_take_id"]=="take-2"
    assert contract["selected_closing_fallback_take_id"]==SELECTED_CLOSING_TAKE_ID=="take-1"
    assert contract["human_approved_opening_reference"]=="I-opening-fluid-2.mp3"
    assert contract["human_approved_final_end_sample_id"]=="G-brand-mixed"
    assert "no automatic" in contract["selection_rule"].lower()
    assert contract["cache_policy"]["closing_fixed_reusable"] is True
