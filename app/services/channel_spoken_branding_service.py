from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re
from typing import Any

SPOKEN_BRANDING_CONTRACT_VERSION = "br-no-gta-spoken-branding/v1"
OFFICIAL_INTRO_ASSET_ID = 1
OFFICIAL_VOICE_BLIND_ID = "Voice B"
OFFICIAL_VOICE_SHORT_NAME = "pt-BR-ThalitaMultilingualNeural"
OFFICIAL_PROVIDER = "edge-tts"
OFFICIAL_PROVIDER_VERSION = "7.2.8"
OFFICIAL_LANGUAGE = "pt-BR"
OPENING_PREFIX = "Booooa meu povo, aqui é BR no GTA 6 e hoje vamos de "
CLOSING_LINE = "E BR não dorme em Vice City"
OFFICIAL_RATE = "+0%"
OFFICIAL_PITCH = "+0Hz"
SELECTED_TAKE_ID = "take-1"

OPENING_DIRECTION = {
    "personality": [
        "feminina","brasileira","jovem","confiante","energia_alta",
        "sorriso_perceptivel","espontanea","nunca_formal","nunca_robotica",
    ],
    "booooa": "alongar_aproximadamente_1s_grito_de_chamada_subida_final",
    "meu_povo": "quente_acolhedor_leve_descida",
    "aqui_e_br_no_gta_6": "orgulho_enfase_em_BR",
    "e_hoje_vamos_de": "leve_aceleracao_criar_curiosidade",
    "tema": "payoff_natural_sem_pausa_artificial_exagerada",
}
CLOSING_DIRECTION = {
    "E": "pequena_pausa",
    "body": "malicioso_confiante_recado_final_enfase_em_Vice_City",
    "ending": "leve_entonacao_ascendente",
}

TAKE_PROFILES = (
    {"take_id":"take-1","rate":"+0%","pitch":"+0Hz","role":"canonical-human-profile"},
    {"take_id":"take-2","rate":"+2%","pitch":"+2Hz","role":"prosody-variation"},
    {"take_id":"take-3","rate":"-2%","pitch":"+1Hz","role":"prosody-variation"},
)


class SpokenBrandingContractError(ValueError):
    pass


def normalize_theme(theme: str) -> str:
    if not isinstance(theme,str):
        raise SpokenBrandingContractError("spoken branding theme must be text")
    value=re.sub(r"\s+"," ",theme.strip())
    if not value:
        raise SpokenBrandingContractError("spoken branding theme is required")
    if value.endswith(("!","?",".")):
        value=value[:-1].rstrip()
    if not value or len(value)>180:
        raise SpokenBrandingContractError("spoken branding theme length is invalid")
    return value


def canonical_opening_text(theme: str) -> str:
    return f"{OPENING_PREFIX}{normalize_theme(theme)}!"


def _canonical_hash(payload: Any) -> str:
    encoded=json.dumps(payload,ensure_ascii=True,sort_keys=True,separators=(",",":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_spoken_branding_contract(*, theme: str) -> dict[str,Any]:
    theme=normalize_theme(theme)
    opening=canonical_opening_text(theme)
    contract={
        "version":SPOKEN_BRANDING_CONTRACT_VERSION,
        "authority":"deepseek_harness",
        "identity_type":"canonical_channel_branding",
        "intro_asset_id":OFFICIAL_INTRO_ASSET_ID,
        "spoken_opening_after_intro":True,
        "official_voice_profile":OFFICIAL_VOICE_BLIND_ID,
        "voice_short_name":OFFICIAL_VOICE_SHORT_NAME,
        "provider":OFFICIAL_PROVIDER,
        "provider_version":OFFICIAL_PROVIDER_VERSION,
        "language":OFFICIAL_LANGUAGE,
        "opening_template":"fixed_prefix_plus_theme",
        "opening_fixed_prefix":OPENING_PREFIX,
        "opening_theme":theme,
        "opening_text":opening,
        "closing_template":"fixed",
        "closing_line":CLOSING_LINE,
        "rate":OFFICIAL_RATE,
        "pitch":OFFICIAL_PITCH,
        "opening_direction":deepcopy(OPENING_DIRECTION),
        "closing_direction":deepcopy(CLOSING_DIRECTION),
        "take_profiles":[dict(item) for item in TAKE_PROFILES],
        "selected_take_id":SELECTED_TAKE_ID,
        "selection_rule":"canonical Voice B +0%/+0Hz take is the fail-closed baseline; prosody variants never auto-promote on technical score",
        "cache_policy":{
            "fingerprint_components":[
                "kind","text","voice_short_name","provider","provider_version",
                "language","direction","take_profile",
            ],
            "opening_invalidates_on":["theme","voice","provider_version","direction"],
            "closing_invalidates_on":["voice","provider_version","direction"],
            "closing_fixed_reusable":True,
        },
        "timeline_order":[
            "official_intro",
            "spoken_channel_opening",
            "editorial_hook",
            "editorial_content",
            "spoken_channel_closing",
        ],
    }
    contract["contract_sha256"]=_canonical_hash(contract)
    return contract


def validate_spoken_branding_contract(contract: dict[str,Any]) -> dict[str,Any]:
    if not isinstance(contract,dict):
        raise SpokenBrandingContractError("spoken branding contract is required")
    theme=normalize_theme(contract.get("opening_theme"))
    expected=build_spoken_branding_contract(theme=theme)
    immutable=(
        "version","authority","identity_type","intro_asset_id","spoken_opening_after_intro",
        "official_voice_profile","voice_short_name","provider","provider_version","language",
        "opening_template","opening_fixed_prefix","opening_text","closing_template","closing_line",
        "rate","pitch","opening_direction","closing_direction","take_profiles","selected_take_id",
        "selection_rule","cache_policy","timeline_order","contract_sha256",
    )
    for key in immutable:
        if contract.get(key)!=expected.get(key):
            raise SpokenBrandingContractError(f"spoken branding contract mismatch: {key}")
    return expected


def validate_job_spoken_branding(job: dict[str,Any]) -> dict[str,Any]:
    brand_assets=job.get("brand_assets")
    if not isinstance(brand_assets,list):
        raise SpokenBrandingContractError("brand_assets are required")
    intro=next((item for item in brand_assets if isinstance(item,dict) and item.get("asset_type")=="intro"),None)
    if not intro or intro.get("asset_id")!=OFFICIAL_INTRO_ASSET_ID:
        raise SpokenBrandingContractError("official intro ASSET_ID=1 is mandatory")
    contract=validate_spoken_branding_contract(job.get("spoken_branding"))
    narration=job.get("narration") or {}
    if narration.get("voice")!=OFFICIAL_VOICE_SHORT_NAME:
        raise SpokenBrandingContractError("Voice B official identity cannot be substituted")
    if narration.get("human_quality_baseline")!=OFFICIAL_VOICE_BLIND_ID:
        raise SpokenBrandingContractError("Voice B must remain the human quality baseline")
    sections=job.get("script_sections") or []
    if not sections or sections[0].get("role")!="hook":
        raise SpokenBrandingContractError("editorial hook must remain present after brand opening")
    return contract
