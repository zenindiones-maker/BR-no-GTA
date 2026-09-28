from __future__ import annotations

import json
from pathlib import Path
import pytest

from app.services.channel_spoken_branding_service import (
    ALLOW_LEGACY_VOICE_B_FALLBACK,
    LEGACY_CONTROL_VOICE_BLIND_ID,
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


def test_owner_voice_is_canonical_and_legacy_voice_b_is_runtime_disabled():
    assert OFFICIAL_VOICE_IDENTITY_ID == "BR_OWNER_V1"
    assert OFFICIAL_VOICE_BLIND_ID == "BR_OWNER_V1"
    assert OFFICIAL_VOICE_SHORT_NAME == "BR_OWNER_V1"
    assert OFFICIAL_PROVIDER == "private-voice-runtime"
    assert LEGACY_CONTROL_VOICE_BLIND_ID == "Voice B"
    assert ALLOW_LEGACY_VOICE_B_FALLBACK is False
    enrollment = json.loads(
        (ROOT / "config/voice_owner_enrollment_v1.json").read_text(encoding="utf-8")
    )
    assert enrollment["voice_identity_id"] == "BR_OWNER_V1"
    assert enrollment["consent_status"] == "APPROVED"
    assert enrollment["declared_reference_count"] == 9
    assert enrollment["reference_source"] == "TELEGRAM"
    assert enrollment["official_voice"] == "BR_OWNER_V1"
    assert enrollment["legacy_voice_b_runtime_enabled"] is False
    assert enrollment["legacy_voice_b_fallback_allowed"] is False
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


def test_provider_profiles_are_pinned_ptbr_and_self_hosted_compute():
    assert QWEN_OWNER_INTERACTIVE.model_id == "Qwen/Qwen3-TTS-12Hz-0.6B-Base"
    assert QWEN_OWNER_INTERACTIVE.model_revision == "5d83992"
    assert QWEN_OWNER_LONG_FORM.model_id == "Qwen/Qwen3-TTS-12Hz-1.7B-Base"
    assert QWEN_OWNER_LONG_FORM.model_revision == "fd4b254"
    assert CHATTERBOX_PTBR_PROFILE.model_id == "ResembleAI/Chatterbox-Multilingual-pt-br"
    assert CHATTERBOX_PTBR_PROFILE.model_revision == "b3952f1"
    assert {QWEN_OWNER_INTERACTIVE.cost_class, QWEN_OWNER_LONG_FORM.cost_class, CHATTERBOX_PTBR_PROFILE.cost_class} == {"SELF_HOSTED_COMPUTE"}
    assert all(p.supports_ptbr for p in (QWEN_OWNER_INTERACTIVE, QWEN_OWNER_LONG_FORM, CHATTERBOX_PTBR_PROFILE))


def test_long_form_routing_is_identity_sticky_and_never_silent_provider_fallback():
    request = VoiceRouteRequest(
        usage="LONG_FORM",
        language="pt-BR",
        voice_identity_id="owner-v1-candidate",
        required_voice_identity_revision="rev-1",
    )
    selected = select_voice_provider(
        request,
        candidates=(QWEN_OWNER_LONG_FORM, CHATTERBOX_PTBR_PROFILE),
        certified_provider_ids=("qwen3-tts", "chatterbox"),
        sticky_provider_id="qwen3-tts",
        sticky_model_id=QWEN_OWNER_LONG_FORM.model_id,
    )
    assert selected.provider_id == "qwen3-tts"
    with pytest.raises(RuntimeError, match="VOICE_IDENTITY_STICKY"):
        select_voice_provider(
            request,
            candidates=(CHATTERBOX_PTBR_PROFILE,),
            certified_provider_ids=("chatterbox",),
            sticky_provider_id="qwen3-tts",
            sticky_model_id=QWEN_OWNER_LONG_FORM.model_id,
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
