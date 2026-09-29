from __future__ import annotations

import pytest

from app.services.owner_voice_strict_policy import (
    OWNER_ACCENT_LOCALE,
    OWNER_IDENTITY_BINDING_MODE,
    OWNER_REFERENCE_SOURCE,
    OwnerVoicePolicyError,
    owner_voice_runtime_policy,
    validate_owner_identity_profile,
    validate_owner_runtime_receipt,
    validate_owner_synthesis_request,
)
from app.services.voice_plane_contracts import VoiceSynthesisRequest


def _request(*, language: str = "pt-BR", identity: str = "BR_OWNER_V1") -> VoiceSynthesisRequest:
    return VoiceSynthesisRequest(
        voice_identity_id=identity,
        text="Booooa meu povo, aqui é BR no GTA 6.",
        language=language,
        usage="AUDITION",
        rate=1.0,
        style="OWNER_REFERENCE",
        segment_id="strict-owner-1",
        correlation_id="strict-owner-corr-1",
    )


def _profile() -> dict:
    return {
        "voice_identity_id": "BR_OWNER_V1",
        "language": "pt-BR",
        "accent_locale": "pt-BR",
        "reference_source": "TELEGRAM",
        "voice_selection_mode": "TELEGRAM_REFERENCE_CLONE",
        "preset_voice_used": False,
        "generic_voice_fallback": False,
        "source_audio_refs": ["private://voice/BR_OWNER_V1/references/" + "a" * 64],
    }


def test_owner_voice_request_requires_exact_brazilian_portuguese_locale():
    validate_owner_synthesis_request(_request(language="pt-BR"))
    with pytest.raises(OwnerVoicePolicyError, match="PTBR_REQUIRED"):
        validate_owner_synthesis_request(_request(language="pt"))
    with pytest.raises(OwnerVoicePolicyError, match="PTBR_REQUIRED"):
        validate_owner_synthesis_request(_request(language="pt-PT"))


def test_owner_voice_request_forbids_alternate_identity():
    with pytest.raises(OwnerVoicePolicyError, match="IDENTITY_REQUIRED"):
        validate_owner_synthesis_request(_request(identity="generic-speaker"))


def test_owner_profile_must_be_telegram_bound_and_have_no_preset_voice():
    validate_owner_identity_profile(_profile())

    wrong_source = {**_profile(), "reference_source": "PROVIDER_PRESET"}
    with pytest.raises(OwnerVoicePolicyError, match="TELEGRAM_REFERENCE_REQUIRED"):
        validate_owner_identity_profile(wrong_source)

    preset = {**_profile(), "preset_voice_used": True}
    with pytest.raises(OwnerVoicePolicyError, match="PRESET_VOICE_FORBIDDEN"):
        validate_owner_identity_profile(preset)

    fallback = {**_profile(), "generic_voice_fallback": True}
    with pytest.raises(OwnerVoicePolicyError, match="GENERIC_VOICE_FALLBACK_FORBIDDEN"):
        validate_owner_identity_profile(fallback)


def test_owner_runtime_policy_is_telegram_only_ptbr():
    policy = owner_voice_runtime_policy()
    assert policy["voice_identity_id"] == "BR_OWNER_V1"
    assert policy["language"] == "pt-BR"
    assert policy["accent_locale"] == OWNER_ACCENT_LOCALE == "pt-BR"
    assert policy["reference_source"] == OWNER_REFERENCE_SOURCE == "TELEGRAM"
    assert policy["identity_binding_mode"] == OWNER_IDENTITY_BINDING_MODE
    assert policy["provider_preset_voice_allowed"] is False
    assert policy["generic_voice_fallback"] is False
    assert policy["alternate_voice_identities_allowed"] is False


def test_runtime_receipt_must_prove_telegram_clone_and_ptbr_accent():
    receipt = {
        "reference_source": "TELEGRAM",
        "accent_locale": "pt-BR",
        "identity_binding_mode": "TELEGRAM_REFERENCE_CLONE",
        "preset_voice_used": False,
        "generic_voice_fallback": False,
    }
    validate_owner_runtime_receipt(receipt)

    with pytest.raises(OwnerVoicePolicyError, match="PTBR_ACCENT_MISSING"):
        validate_owner_runtime_receipt({**receipt, "accent_locale": "pt-PT"})
    with pytest.raises(OwnerVoicePolicyError, match="PRESET_VOICE_FORBIDDEN"):
        validate_owner_runtime_receipt({**receipt, "preset_voice_used": True})
