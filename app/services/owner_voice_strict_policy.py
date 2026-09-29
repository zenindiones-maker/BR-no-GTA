from __future__ import annotations

from typing import Any, Mapping

from app.services.voice_plane_contracts import VoiceSynthesisRequest


OWNER_VOICE_IDENTITY_ID = "BR_OWNER_V1"
OWNER_REFERENCE_SOURCE = "TELEGRAM"
OWNER_LANGUAGE = "pt-BR"
OWNER_ACCENT_LOCALE = "pt-BR"
OWNER_IDENTITY_BINDING_MODE = "TELEGRAM_REFERENCE_CLONE"
OWNER_GENERIC_FALLBACK_ALLOWED = False
OWNER_PROVIDER_PRESET_VOICE_ALLOWED = False
OWNER_ALTERNATE_VOICE_IDENTITIES_ALLOWED = False


class OwnerVoicePolicyError(ValueError):
    pass


def _locale(value: Any) -> str:
    return str(value or "").strip().lower().replace("_", "-")


def validate_owner_synthesis_request(request: VoiceSynthesisRequest) -> None:
    if request.voice_identity_id != OWNER_VOICE_IDENTITY_ID:
        raise OwnerVoicePolicyError("OWNER_VOICE_IDENTITY_REQUIRED")
    if _locale(request.language) != "pt-br":
        raise OwnerVoicePolicyError("OWNER_VOICE_PTBR_REQUIRED")


def validate_owner_identity_profile(profile: Mapping[str, Any]) -> None:
    if str(profile.get("voice_identity_id") or "") != OWNER_VOICE_IDENTITY_ID:
        raise OwnerVoicePolicyError("OWNER_VOICE_IDENTITY_REQUIRED")
    if _locale(profile.get("language")) != "pt-br":
        raise OwnerVoicePolicyError("OWNER_PROFILE_PTBR_REQUIRED")
    if _locale(profile.get("accent_locale")) != "pt-br":
        raise OwnerVoicePolicyError("OWNER_PROFILE_BRAZILIAN_ACCENT_REQUIRED")
    if str(profile.get("reference_source") or "") != OWNER_REFERENCE_SOURCE:
        raise OwnerVoicePolicyError("OWNER_PROFILE_TELEGRAM_REFERENCE_REQUIRED")
    if str(profile.get("voice_selection_mode") or "") != OWNER_IDENTITY_BINDING_MODE:
        raise OwnerVoicePolicyError("OWNER_PROFILE_TELEGRAM_CLONE_REQUIRED")
    if profile.get("preset_voice_used") is not False:
        raise OwnerVoicePolicyError("OWNER_PROVIDER_PRESET_VOICE_FORBIDDEN")
    if profile.get("generic_voice_fallback") is not False:
        raise OwnerVoicePolicyError("OWNER_GENERIC_VOICE_FALLBACK_FORBIDDEN")

    refs = tuple(str(item) for item in (profile.get("source_audio_refs") or ()))
    if not refs or any(
        not ref.startswith(f"private://voice/{OWNER_VOICE_IDENTITY_ID}/")
        for ref in refs
    ):
        raise OwnerVoicePolicyError("OWNER_PRIVATE_TELEGRAM_REFERENCE_REQUIRED")


def owner_voice_runtime_policy() -> dict[str, Any]:
    return {
        "voice_identity_id": OWNER_VOICE_IDENTITY_ID,
        "language": OWNER_LANGUAGE,
        "accent_locale": OWNER_ACCENT_LOCALE,
        "reference_source": OWNER_REFERENCE_SOURCE,
        "identity_binding_mode": OWNER_IDENTITY_BINDING_MODE,
        "provider_preset_voice_allowed": OWNER_PROVIDER_PRESET_VOICE_ALLOWED,
        "generic_voice_fallback": OWNER_GENERIC_FALLBACK_ALLOWED,
        "alternate_voice_identities_allowed": OWNER_ALTERNATE_VOICE_IDENTITIES_ALLOWED,
        "accent_acceptance": "HUMAN_CERTIFIED_BRAZILIAN_PORTUGUESE_REQUIRED",
    }


def validate_owner_runtime_receipt(receipt: Mapping[str, Any]) -> None:
    if _locale(receipt.get("accent_locale")) != "pt-br":
        raise OwnerVoicePolicyError("OWNER_RECEIPT_PTBR_ACCENT_MISSING")
    if str(receipt.get("reference_source") or "") != OWNER_REFERENCE_SOURCE:
        raise OwnerVoicePolicyError("OWNER_RECEIPT_TELEGRAM_REFERENCE_MISSING")
    if str(receipt.get("identity_binding_mode") or "") != OWNER_IDENTITY_BINDING_MODE:
        raise OwnerVoicePolicyError("OWNER_RECEIPT_TELEGRAM_CLONE_MISSING")

    preset = receipt.get("preset_voice_used")
    if preset not in (False, "false", "False", 0, "0"):
        raise OwnerVoicePolicyError("OWNER_RECEIPT_PRESET_VOICE_FORBIDDEN")
    fallback = receipt.get("generic_voice_fallback")
    if fallback not in (False, "false", "False", 0, "0"):
        raise OwnerVoicePolicyError("OWNER_RECEIPT_GENERIC_FALLBACK_FORBIDDEN")
