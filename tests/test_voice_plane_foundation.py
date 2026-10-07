from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import pytest

from app.services.channel_spoken_branding_service import (
    OFFICIAL_PROVIDER,
    OFFICIAL_VOICE_BLIND_ID,
    OFFICIAL_VOICE_IDENTITY_ID,
    OFFICIAL_VOICE_SHORT_NAME,
)
from app.services.voice_plane_contracts import (
    ConsentStatus,
    VoiceEnrollmentMetrics,
    VoiceIdentityProfile,
    VoiceSynthesisRequest,
    VoiceTurnEnvelope,
    evaluate_voice_enrollment,
)
from app.services.voice_provider_service import (
    CHATTERBOX_PTBR_PROFILE,
    QWEN_OWNER_INTERACTIVE,
    QWEN_OWNER_LONG_FORM,
    PrivateVoiceRuntimeProvider,
    PrivateVoiceRuntimeResponse,
    VoiceProviderUnavailable,
    VoiceRouteRequest,
    select_voice_provider,
)
from app.services.voice_identity_store import (
    PrivateVoiceAssetRef,
    PrivateVoiceIdentityStore,
    official_voice_promotion_allowed,
)
from app.services.voice_egress_policy import apply_voice_egress_policy


ROOT = Path(__file__).resolve().parents[1]


def test_owner_voice_is_canonical_and_selected():
    assert OFFICIAL_VOICE_IDENTITY_ID == "BR_OWNER_V1"
    assert OFFICIAL_VOICE_BLIND_ID == "BR_OWNER_V1"
    assert OFFICIAL_VOICE_SHORT_NAME == "BR_OWNER_V1"
    assert OFFICIAL_PROVIDER == "private-voice-runtime"
    enrollment = json.loads(
        (ROOT / "config/voice_owner_enrollment_v1.json").read_text(encoding="utf-8")
    )
    assert enrollment["voice_identity_id"] == "BR_OWNER_V1"
    assert enrollment["consent_status"] == "APPROVED"
    assert enrollment["declared_reference_count"] == 9
    assert enrollment["reference_source"] == "TELEGRAM"
    assert enrollment["official_voice"] == "BR_OWNER_V1"
    assert enrollment["active_voice_identities"] == ["BR_OWNER_V1"]
    assert enrollment["voice_selection_basis"] == "EXPLICIT_OWNER_INSTRUCTION"
    assert official_voice_promotion_allowed(
        consent=ConsentStatus.APPROVED,
        human_ab_review=False,
        explicit_owner_selection=True,
    ) is True


def test_voice_identity_profile_requires_private_refs_and_approved_consent_for_reusable_clone():
    ref = PrivateVoiceAssetRef(
        ref="private://voice/owner/ref-001",
        sha256="a" * 64,
        media_type="audio/wav",
    )
    profile = VoiceIdentityProfile(
        voice_identity_id="owner-v1-candidate",
        owner_class="OWNER",
        language="pt-BR",
        source_audio_refs=(ref.ref,),
        source_audio_sha256s=(ref.sha256,),
        source_transcript_sha256s=("b" * 64,),
        consent_status=ConsentStatus.APPROVED,
        consent_timestamp="2026-09-28T19:00:00Z",
        clone_provider="qwen3-tts",
        clone_model="Qwen/Qwen3-TTS-12Hz-0.6B-Base",
        clone_model_revision="5d83992",
        voice_prompt_ref="private://voice/owner/prompt-001",
        voice_prompt_sha256="c" * 64,
        quality_status="CANDIDATE",
        created_at="2026-09-28T19:00:00Z",
        updated_at="2026-09-28T19:00:00Z",
    )
    assert profile.reusable_clone_allowed is True
    with pytest.raises(ValueError, match="private://"):
        PrivateVoiceAssetRef(
            ref="assets/voice/owner.wav",
            sha256="a" * 64,
            media_type="audio/wav",
        )


def test_private_identity_store_refuses_repo_local_storage(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    with pytest.raises(ValueError, match="outside repository"):
        PrivateVoiceIdentityStore(root=repo_root / "private-voice", repository_root=repo_root)


def test_enrollment_policy_requires_30_seconds_clean_single_speaker_ptbr():
    good = evaluate_voice_enrollment(
        VoiceEnrollmentMetrics(
            aggregate_clean_speech_seconds=65.0,
            detected_language="pt-BR",
            single_speaker=True,
            speech_ratio=0.88,
            silence_ratio=0.12,
            clipping_ratio=0.0,
            peak_dbfs=-1.5,
            rms_dbfs=-20.0,
            snr_db=28.0,
            transcription_confidence=0.96,
            corrupt_audio=False,
        )
    )
    assert good.status == "PASS"
    noisy = evaluate_voice_enrollment(
        VoiceEnrollmentMetrics(
            aggregate_clean_speech_seconds=12.0,
            detected_language="pt-BR",
            single_speaker=False,
            speech_ratio=0.40,
            silence_ratio=0.60,
            clipping_ratio=0.10,
            peak_dbfs=0.0,
            rms_dbfs=-45.0,
            snr_db=5.0,
            transcription_confidence=0.50,
            corrupt_audio=False,
        )
    )
    assert noisy.status == "FAIL"
    assert "INSUFFICIENT_CLEAN_SPEECH" in noisy.issues
    assert "MULTIPLE_SPEAKERS" in noisy.issues


def test_provider_profiles_pin_qwen_17b_for_owner_production_and_keep_human_accent_gate():
    assert QWEN_OWNER_INTERACTIVE.model_id == "Qwen/Qwen3-TTS-12Hz-1.7B-Base"
    assert QWEN_OWNER_INTERACTIVE.model_revision == "fd4b254389122332181a7c3db7f27e918eec64e3"
    assert QWEN_OWNER_LONG_FORM.model_id == "Qwen/Qwen3-TTS-12Hz-1.7B-Base"
    assert QWEN_OWNER_LONG_FORM.model_revision == "fd4b254389122332181a7c3db7f27e918eec64e3"
    assert QWEN_OWNER_INTERACTIVE.cost_class == "SELF_HOSTED_COMPUTE"
    assert QWEN_OWNER_LONG_FORM.cost_class == "SELF_HOSTED_COMPUTE"
    assert QWEN_OWNER_INTERACTIVE.supports_ptbr is True
    assert QWEN_OWNER_LONG_FORM.supports_ptbr is True
    assert QWEN_OWNER_INTERACTIVE.requires_owner_reference is True
    assert QWEN_OWNER_LONG_FORM.requires_owner_reference is True
    assert QWEN_OWNER_INTERACTIVE.provider_preset_voice_allowed is False
    assert QWEN_OWNER_LONG_FORM.provider_preset_voice_allowed is False
    assert QWEN_OWNER_INTERACTIVE.ptbr_accent_certified is False
    assert QWEN_OWNER_LONG_FORM.ptbr_accent_certified is False
    # Chatterbox may remain historical provenance, but is not a production route.
    assert CHATTERBOX_PTBR_PROFILE.provider_id == "chatterbox"


def test_long_form_routing_requires_owner_identity_human_certified_ptbr_and_qwen_only():
    request = VoiceRouteRequest(
        usage="LONG_FORM",
        language="pt-BR",
        voice_identity_id="BR_OWNER_V1",
        required_voice_identity_revision="rev-1",
    )
    with pytest.raises(VoiceProviderUnavailable, match="VOICE_PROVIDER_UNAVAILABLE"):
        select_voice_provider(
            request,
            candidates=(QWEN_OWNER_LONG_FORM,),
            certified_provider_ids=("qwen3-tts",),
        )

    approved_qwen = replace(QWEN_OWNER_LONG_FORM, ptbr_accent_certified=True)
    selected = select_voice_provider(
        request,
        candidates=(approved_qwen,),
        certified_provider_ids=("qwen3-tts",),
        sticky_provider_id="qwen3-tts",
        sticky_model_id=approved_qwen.model_id,
    )
    assert selected.provider_id == "qwen3-tts"
    assert selected.model_id == "Qwen/Qwen3-TTS-12Hz-1.7B-Base"

    approved_chatterbox = replace(CHATTERBOX_PTBR_PROFILE, ptbr_accent_certified=True)
    with pytest.raises(VoiceProviderUnavailable, match="VOICE_PROVIDER_UNAVAILABLE"):
        select_voice_provider(
            request,
            candidates=(approved_chatterbox,),
            certified_provider_ids=("chatterbox",),
        )


def test_synthesis_request_has_bounded_usage_and_no_raw_audio():
    request = VoiceSynthesisRequest(
        voice_identity_id="owner-v1-candidate",
        text="Resumo curto.",
        language="pt-BR",
        usage="INTERACTIVE",
        rate=1.0,
        style="ACTION_FIRST",
        segment_id="turn-1",
        correlation_id="corr-1",
    )
    payload = request.to_dict()
    assert payload["usage"] == "INTERACTIVE"
    assert "audio" not in payload
    assert "embedding" not in payload


def test_voice_egress_policy_keeps_long_technical_detail_in_text():
    decision = apply_voice_egress_policy(
        canonical_text="Production retomou. " + ("detalhe técnico " * 100),
        action_summary="Production retomou. O detalhe técnico foi enviado em texto.",
        mode="ACTION_FIRST",
    )
    assert len(decision.spoken_response_text) < len(decision.full_text)
    assert decision.full_text.startswith("Production retomou.")


def test_upstream_provenance_is_pinned_and_cloudflare_uses_agents_voice():
    config = json.loads((ROOT / "config/voice_plane_upstreams_v1.json").read_text(encoding="utf-8"))
    assert config["qwen3_tts"]["repository_sha"] == "022e286b98fbec7e1e916cb940cdf532cd9f488e"
    assert config["qwen3_tts"]["package_version"] == "0.1.1"
    assert config["chatterbox"]["repository_sha"] == "5de7a54aa4e5e2baadb0182dde554908b48b85c2"
    assert config["cloudflare_agents"]["repository_sha"] == "11f87b5332f6cf4dfff71d8249621b28f539280f"
    assert config["cloudflare_agents"]["package"] == "agents"
    assert config["cloudflare_agents"]["package_version"] == "0.24.0"
    assert config["cloudflare_agents"]["deprecated_wrapper_used"] is False
    assert config["nemotron_voicechat"]["model_id"] == "nvidia/NVIDIA-NemotronLabs-VoiceChat-11B"
    assert config["nemotron_voicechat"]["production_eligible"] is False
    assert config["symphony"]["second_scheduler"] is False


def _owner_synthesis_request():
    return VoiceSynthesisRequest(
        voice_identity_id="BR_OWNER_V1",
        text="Prova curta da voz real.",
        language="pt-BR",
        usage="AUDITION",
        rate=1.0,
        style="OWNER_REFERENCE",
        segment_id="owner-proof-1",
        correlation_id="corr-owner-proof-1",
    )


def _ready_owner_profile():
    return {
        "schema": "VoiceIdentityProfile/v1",
        "voice_identity_id": "BR_OWNER_V1",
        "owner_class": "OWNER",
        "language": "pt-BR",
        "accent_locale": "pt-BR",
        "reference_source": "TELEGRAM",
        "voice_selection_mode": "TELEGRAM_REFERENCE_CLONE",
        "preset_voice_used": False,
        "generic_voice_fallback": False,
        "source_audio_refs": ["private://voice/BR_OWNER_V1/reference-001"],
        "source_audio_sha256s": ["a" * 64],
        "source_transcript_sha256s": ["b" * 64],
        "consent_status": "APPROVED",
        "consent_timestamp": "2026-09-28T19:00:00Z",
        "clone_provider": "qwen3-tts",
        "clone_model": QWEN_OWNER_INTERACTIVE.model_id,
        "clone_model_revision": QWEN_OWNER_INTERACTIVE.model_revision,
        "voice_prompt_ref": "private://voice/BR_OWNER_V1/qwen-prompt-001",
        "voice_prompt_sha256": "c" * 64,
        "quality_status": "READY",
        "created_at": "2026-09-28T19:00:00Z",
        "updated_at": "2026-09-28T19:00:00Z",
    }


def test_private_voice_runtime_fails_closed_before_transport_without_materialized_owner(monkeypatch, tmp_path):
    monkeypatch.setenv("BR_VOICE_RUNTIME_TOKEN", "runtime-token")
    calls = []
    provider = PrivateVoiceRuntimeProvider(
        profile=QWEN_OWNER_INTERACTIVE,
        base_url="http://127.0.0.1:18081",
        identity_resolver=lambda _identity: None,
        transport=lambda *_args: calls.append(_args),
    )
    with pytest.raises(VoiceProviderUnavailable, match="OWNER_VOICE_NOT_MATERIALIZED"):
        provider.synthesize(_owner_synthesis_request(), tmp_path / "owner.wav")
    assert calls == []
    assert not (tmp_path / "owner.wav").exists()


def test_private_voice_runtime_requires_matching_owner_clone_receipt(monkeypatch, tmp_path):
    monkeypatch.setenv("BR_VOICE_RUNTIME_TOKEN", "runtime-token")
    captured = {}
    profile = _ready_owner_profile()

    def transport(_url, payload, _headers):
        captured["payload"] = payload
        binding = payload["voice_identity_binding"]
        return PrivateVoiceRuntimeResponse(
            audio=b"owner-voice-wav",
            receipt={
                "schema": "OwnerVoiceSynthesisReceipt/v1",
                "voice_identity_id": "BR_OWNER_V1",
                "profile_sha256": binding["profile_sha256"],
                "voice_prompt_sha256": binding["voice_prompt_sha256"],
                "reference_set_sha256": binding["reference_set_sha256"],
                "provider": "qwen3-tts",
                "model": QWEN_OWNER_INTERACTIVE.model_id,
                "model_revision": QWEN_OWNER_INTERACTIVE.model_revision,
                "request_id": "owner-proof-request-1",
                "audio_sha256": "",
                "usage": "AUDITION",
                "reference_source": "TELEGRAM",
                "accent_locale": "pt-BR",
                "identity_binding_mode": "TELEGRAM_REFERENCE_CLONE",
                "preset_voice_used": False,
                "generic_voice_fallback": False,
            },
        )

    provider = PrivateVoiceRuntimeProvider(
        profile=QWEN_OWNER_INTERACTIVE,
        base_url="http://127.0.0.1:18081",
        identity_resolver=lambda identity: profile if identity == "BR_OWNER_V1" else None,
        transport=transport,
    )
    result = provider.synthesize(_owner_synthesis_request(), tmp_path / "owner.wav")
    binding = captured["payload"]["voice_identity_binding"]
    assert binding["voice_identity_id"] == "BR_OWNER_V1"
    assert binding["voice_prompt_ref"].startswith("private://")
    assert binding["voice_prompt_sha256"] == "c" * 64
    assert len(binding["profile_sha256"]) == 64
    assert len(binding["reference_set_sha256"]) == 64
    assert result["receipt"]["schema"] == "OwnerVoiceSynthesisReceipt/v1"
    assert result["receipt"]["voice_prompt_sha256"] == "c" * 64
    assert result["receipt"]["reference_set_sha256"] == binding["reference_set_sha256"]
    assert result["receipt"]["audio_sha256"] == result["audio_sha256"]


def test_private_voice_runtime_rejects_receipt_that_does_not_prove_bound_prompt(monkeypatch, tmp_path):
    monkeypatch.setenv("BR_VOICE_RUNTIME_TOKEN", "runtime-token")
    profile = _ready_owner_profile()

    def transport(_url, payload, _headers):
        binding = payload["voice_identity_binding"]
        return PrivateVoiceRuntimeResponse(
            audio=b"wrong-voice-wav",
            receipt={
                "schema": "OwnerVoiceSynthesisReceipt/v1",
                "voice_identity_id": "BR_OWNER_V1",
                "profile_sha256": binding["profile_sha256"],
                "voice_prompt_sha256": "d" * 64,
                "reference_set_sha256": binding["reference_set_sha256"],
                "provider": "qwen3-tts",
                "model": QWEN_OWNER_INTERACTIVE.model_id,
                "model_revision": QWEN_OWNER_INTERACTIVE.model_revision,
                "request_id": "owner-proof-request-2",
                "audio_sha256": "",
                "usage": "AUDITION",
                "reference_source": "TELEGRAM",
                "accent_locale": "pt-BR",
                "identity_binding_mode": "TELEGRAM_REFERENCE_CLONE",
                "preset_voice_used": False,
                "generic_voice_fallback": False,
            },
        )

    provider = PrivateVoiceRuntimeProvider(
        profile=QWEN_OWNER_INTERACTIVE,
        base_url="http://127.0.0.1:18081",
        identity_resolver=lambda _identity: profile,
        transport=transport,
    )
    with pytest.raises(VoiceProviderUnavailable, match="OWNER_VOICE_RECEIPT_MISMATCH"):
        provider.synthesize(_owner_synthesis_request(), tmp_path / "owner.wav")
    assert not (tmp_path / "owner.wav").exists()
