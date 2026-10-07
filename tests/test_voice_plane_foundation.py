from __future__ import annotations

from dataclasses import replace
import json
import hashlib
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
    _default_owner_identity_resolver,
)
from app.services.voice_identity_store import (
    PrivateVoiceAssetRef,
    PrivateVoiceIdentityStore,
    official_voice_promotion_allowed,
)
from app.services.voice_egress_policy import apply_voice_egress_policy
from app.services.owner_voice_qwen_runtime_service import (
    OwnerVoiceQwenRuntime,
    OwnerVoiceQwenRuntimeError,
    load_private_prompt_bundle,
)
from app.services.owner_voice_private_promotion_service import (
    OwnerVoicePrivatePromotionError,
    promote_approved_owner_voice,
)
from app.services.owner_voice_single_clone_delivery_service import (
    review_token_for_clone,
)


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


class _FakePrompt:
    def __init__(self, name):
        self.name=name
        self.ref_code=f"code:{name}"
        self.ref_spk_embedding=f"spk:{name}"
        self.x_vector_only_mode=False
        self.icl_mode=True
        self.ref_text=f"text:{name}"


class _FakeQwenModel:
    def __init__(self):
        self.prompt_calls=[]
        self.generate_calls=[]

    def create_voice_clone_prompt(self, *, ref_audio, ref_text, x_vector_only_mode):
        self.prompt_calls.append((ref_audio,ref_text,x_vector_only_mode))
        return [_FakePrompt(str(ref_audio))]

    def generate_voice_clone(self, *, text, language, voice_clone_prompt, non_streaming_mode, **kwargs):
        self.generate_calls.append({
            "text":list(text),
            "language":list(language),
            "voice_clone_prompt":list(voice_clone_prompt),
            "non_streaming_mode":non_streaming_mode,
            "kwargs":dict(kwargs),
        })
        return [
            [0.10+(index*0.01),0.11+(index*0.01),0.12+(index*0.01)]
            for index,_item in enumerate(text)
        ],24000


def _runtime_payload():
    return {
        **_owner_synthesis_request().to_dict(),
        "provider":"qwen3-tts",
        "model":"Qwen/Qwen3-TTS-12Hz-1.7B-Base",
        "model_revision":"fd4b254389122332181a7c3db7f27e918eec64e3",
        "voice_identity_binding":{
            "voice_identity_id":"BR_OWNER_V1",
            "profile_sha256":"a"*64,
            "voice_prompt_ref":"private://voice/BR_OWNER_V1/qwen-prompt/current",
            "voice_prompt_sha256":"b"*64,
            "reference_set_sha256":"c"*64,
            "reference_source":"TELEGRAM",
            "accent_locale":"pt-BR",
            "identity_binding_mode":"TELEGRAM_REFERENCE_CLONE",
            "preset_voice_used":"false",
            "generic_voice_fallback":"false",
        },
        "owner_voice_policy":{
            "voice_identity_id":"BR_OWNER_V1",
            "language":"pt-BR",
            "accent_locale":"pt-BR",
            "reference_source":"TELEGRAM",
            "identity_binding_mode":"TELEGRAM_REFERENCE_CLONE",
            "provider_preset_voice_allowed":False,
            "generic_voice_fallback":False,
            "alternate_voice_identities_allowed":False,
        },
        "accent_locale":"pt-BR",
        "reference_source":"TELEGRAM",
        "identity_binding_mode":"TELEGRAM_REFERENCE_CLONE",
        "provider_preset_voice_allowed":False,
        "generic_voice_fallback":False,
    }


def _runtime_prompt_bundle():
    return {
        "schema":"OwnerVoiceQwenPromptPackage/v1",
        "voice_identity_id":"BR_OWNER_V1",
        "model_id":"Qwen/Qwen3-TTS-12Hz-1.7B-Base",
        "model_revision":"fd4b254389122332181a7c3db7f27e918eec64e3",
        "prompt_sha256":"b"*64,
        "anchor":{
            "audio_path":"/private/anchor.wav",
            "audio_sha256":"d"*64,
            "ref_text":"Booooa meu povo, aqui é BR no GTA 6.",
        },
        "pronunciation_references":{
            "__english__":{
                "audio_path":"/private/names.wav",
                "audio_sha256":"e"*64,
                "ref_text":"Rockstar Games, Jason Duval e Lucia Caminos.",
            },
            "Vice City":{
                "audio_path":"/private/vice-city.wav",
                "audio_sha256":"f"*64,
                "ref_text":"Vice City.",
            },
        },
    }


def test_qwen_runtime_batches_ptbr_and_governed_english_with_owner_prompts():
    model=_FakeQwenModel()
    runtime=OwnerVoiceQwenRuntime(
        model_loader=lambda:model,
        prompt_bundle_loader=lambda _binding:_runtime_prompt_bundle(),
        audio_encoder=lambda wavs,sr:b"RIFF-owner-qwen",
        prompt_item_factory=lambda **kwargs:kwargs,
    )
    payload=_runtime_payload()
    payload["text"]="BR no GTA 6 chega a Vice City com Jason Duval."
    result=runtime.synthesize(payload)
    assert result.audio==b"RIFF-owner-qwen"
    assert result.receipt["schema"]=="OwnerVoiceSynthesisReceipt/v1"
    assert result.receipt["voice_identity_id"]=="BR_OWNER_V1"
    assert result.receipt["provider"]=="qwen3-tts"
    assert result.receipt["model"]=="Qwen/Qwen3-TTS-12Hz-1.7B-Base"
    call=model.generate_calls[0]
    assert "Auto" not in call["language"]
    assert "Portuguese" in call["language"]
    assert "English" in call["language"]
    assert any("Gê Tê A seis" in text for text in call["text"])
    vice_index=next(i for i,text in enumerate(call["text"]) if "Vice City" in text)
    vice_prompt=call["voice_clone_prompt"][vice_index]
    assert vice_prompt["ref_code"]=="code:/private/vice-city.wav"
    assert vice_prompt["ref_spk_embedding"]=="spk:/private/anchor.wav"
    assert result.diagnostics["seed"]==424242


def test_qwen_runtime_fails_closed_on_wrong_model_or_fallback():
    runtime=OwnerVoiceQwenRuntime(
        model_loader=lambda:_FakeQwenModel(),
        prompt_bundle_loader=lambda _binding:_runtime_prompt_bundle(),
        audio_encoder=lambda wavs,sr:b"audio",
        prompt_item_factory=lambda **kwargs:kwargs,
    )
    wrong=_runtime_payload()
    wrong["model"]="some-other-model"
    with pytest.raises(OwnerVoiceQwenRuntimeError,match="MODEL_REQUIRED"):
        runtime.synthesize(wrong)
    fallback=_runtime_payload()
    fallback["generic_voice_fallback"]=True
    with pytest.raises(OwnerVoiceQwenRuntimeError,match="FALLBACK_FORBIDDEN"):
        runtime.synthesize(fallback)


def test_private_prompt_bundle_is_hash_bound_and_confined_to_private_store(tmp_path):
    root=tmp_path/"private"
    root.mkdir()
    anchor=root/"anchor.wav"; anchor.write_bytes(b"anchor")
    names=root/"names.wav"; names.write_bytes(b"names")
    vice=root/"vice.wav"; vice.write_bytes(b"vice")
    package={
        "schema":"OwnerVoiceQwenPromptPackage/v1",
        "voice_identity_id":"BR_OWNER_V1",
        "model_id":"Qwen/Qwen3-TTS-12Hz-1.7B-Base",
        "model_revision":"fd4b254389122332181a7c3db7f27e918eec64e3",
        "anchor":{
            "audio_path":"anchor.wav",
            "audio_sha256":hashlib.sha256(anchor.read_bytes()).hexdigest(),
            "ref_text":"Booooa meu povo.",
        },
        "pronunciation_references":{
            "__english__":{
                "audio_path":"names.wav",
                "audio_sha256":hashlib.sha256(names.read_bytes()).hexdigest(),
                "ref_text":"Jason Duval e Lucia Caminos.",
            },
            "Vice City":{
                "audio_path":"vice.wav",
                "audio_sha256":hashlib.sha256(vice.read_bytes()).hexdigest(),
                "ref_text":"Vice City.",
            },
        },
    }
    package_path=root/"BR_OWNER_V1.prompt.json"
    package_path.write_text(json.dumps(package,sort_keys=True,separators=(",",":")),encoding="utf-8")
    binding={
        "voice_prompt_ref":"private://voice/BR_OWNER_V1/qwen-prompt/current",
        "voice_prompt_sha256":hashlib.sha256(package_path.read_bytes()).hexdigest(),
    }
    loaded=load_private_prompt_bundle(binding,private_store_root=root)
    assert loaded["anchor"]["audio_path"]==str(anchor.resolve())
    assert loaded["pronunciation_references"]["Vice City"]["audio_path"]==str(vice.resolve())

    binding["voice_prompt_sha256"]="0"*64
    with pytest.raises(OwnerVoiceQwenRuntimeError,match="PROMPT_HASH_MISMATCH"):
        load_private_prompt_bundle(binding,private_store_root=root)


def test_qwen_runtime_http_server_is_loopback_authenticated_and_bounded():
    source=(ROOT/"scripts/owner_voice_qwen_runtime.py").read_text(encoding="utf-8")
    assert '"127.0.0.1"' in source
    assert '"0.0.0.0"' not in source
    assert "hmac.compare_digest" in source
    assert "BR_VOICE_RUNTIME_TOKEN" in source
    assert "MAX_REQUEST_BYTES" in source
    assert '"/v1/speech"' in source


def _promotion_reference(tmp_path, input_id, name, text):
    path=tmp_path/f"{name}.wav"
    payload=(name+"-audio").encode()
    path.write_bytes(payload)
    return {
        "telegram_input_id":input_id,
        "runtime_path":str(path),
        "sha256":hashlib.sha256(payload).hexdigest(),
        "ref_text":text,
    }


def _promotion_delivery(token):
    return {
        "schema_version":"OwnerVoiceSingleCloneDelivery/v1",
        "clone_id":"BR_OWNER_V1_SINGLE_CLONE_FINAL_1",
        "state":"CONFIRMED",
        "candidate_mode":"SINGLE_CLONE",
        "review_token":token,
        "clone_identity_gate":"PASS",
        "content_audio_prescreen":"PASS",
        "runtime_activation":False,
        "identity_anchor_telegram_input_id":125,
        "pronunciation_reference_telegram_input_ids":[126,127],
        "vice_city_reference_telegram_input_id":126,
    }


def _promotion_review(token):
    return {
        "schema":"OwnerVoiceHumanReviewReceipt/v2",
        "voice_identity_id":"BR_OWNER_V1",
        "candidate_mode":"SINGLE_CLONE",
        "review_token":token,
        "status":"APPROVED_PENDING_PROMOTION",
        "review_action":"approve",
        "production_activation":"BLOCKED_PENDING_PROMOTION",
        "authorized_human":True,
        "production_authority":True,
        "lineage_bound":True,
        "automatic_gates_passed":True,
        "identity_anchor_telegram_input_id":125,
        "pronunciation_reference_telegram_input_ids":[126,127],
        "vice_city_reference_telegram_input_id":126,
        "recorded_at_epoch":123.0,
    }


def test_private_promotion_writes_hash_bound_qwen_package_and_profile_without_activation(tmp_path):
    repo_root=tmp_path/"repo"; repo_root.mkdir()
    source_root=tmp_path/"materialized"; source_root.mkdir()
    private_root=tmp_path/"private"
    refs={
        125:_promotion_reference(source_root,125,"anchor","Booooa meu povo, aqui é BR no GTA 6."),
        126:_promotion_reference(source_root,126,"vice","Vice City."),
        127:_promotion_reference(source_root,127,"names","Rockstar Games, Jason Duval e Lucia Caminos."),
    }
    token=review_token_for_clone("BR_OWNER_V1_SINGLE_CLONE_FINAL_1")
    receipt=promote_approved_owner_voice(
        clone_delivery=_promotion_delivery(token),
        human_review=_promotion_review(token),
        references_by_input_id=refs,
        private_store_root=private_root,
        repository_root=repo_root,
    )
    assert receipt["schema"]=="OwnerVoicePrivatePromotionReceipt/v1"
    assert receipt["status"]=="PROMOTED_PRIVATE_PENDING_PUBLIC_ACTIVATION"
    assert receipt["runtime_activation"] is False
    assert len(receipt["voice_prompt_sha256"])==64
    assert len(receipt["profile_sha256"])==64

    package_path=private_root/"BR_OWNER_V1.prompt.json"
    profile_path=private_root/"BR_OWNER_V1.json"
    assert package_path.is_file()
    assert profile_path.is_file()
    package=json.loads(package_path.read_text())
    profile=json.loads(profile_path.read_text())
    assert hashlib.sha256(package_path.read_bytes()).hexdigest()==receipt["voice_prompt_sha256"]
    assert profile["clone_provider"]=="qwen3-tts"
    assert profile["clone_model"]=="Qwen/Qwen3-TTS-12Hz-1.7B-Base"
    assert profile["voice_prompt_sha256"]==receipt["voice_prompt_sha256"]
    assert profile["quality_status"]=="READY"
    assert profile["generic_voice_fallback"] is False
    assert package["pronunciation_references"]["Vice City"]["ref_text"]=="Vice City."
    assert package["pronunciation_references"]["__english__"]["ref_text"].startswith("Rockstar Games")
    assert (package_path.stat().st_mode & 0o777)==0o600
    assert (profile_path.stat().st_mode & 0o777)==0o600
    assert (private_root.stat().st_mode & 0o777)==0o700


def test_private_promotion_rejects_auto_gate_failure_even_with_human_approval(tmp_path):
    repo_root=tmp_path/"repo"; repo_root.mkdir()
    private_root=tmp_path/"private"
    token=review_token_for_clone("BR_OWNER_V1_SINGLE_CLONE_FINAL_1")
    delivery=_promotion_delivery(token)
    delivery["clone_identity_gate"]="FAIL"
    with pytest.raises(OwnerVoicePrivatePromotionError,match="AUTOMATIC_GATES_REQUIRED"):
        promote_approved_owner_voice(
            clone_delivery=delivery,
            human_review=_promotion_review(token),
            references_by_input_id={},
            private_store_root=private_root,
            repository_root=repo_root,
        )


def test_private_promotion_rejects_review_token_or_lineage_mismatch(tmp_path):
    repo_root=tmp_path/"repo"; repo_root.mkdir()
    private_root=tmp_path/"private"
    token=review_token_for_clone("BR_OWNER_V1_SINGLE_CLONE_FINAL_1")
    review=_promotion_review(token)
    review["review_token"]="0"*20
    with pytest.raises(OwnerVoicePrivatePromotionError,match="REVIEW_BINDING_MISMATCH"):
        promote_approved_owner_voice(
            clone_delivery=_promotion_delivery(token),
            human_review=review,
            references_by_input_id={},
            private_store_root=private_root,
            repository_root=repo_root,
        )


def test_default_owner_resolver_uses_private_runtime_activation_not_mutable_public_ready_flags(tmp_path,monkeypatch):
    repo_root=tmp_path/"repo"; repo_root.mkdir()
    private=tmp_path/"private"
    refs=tmp_path/"materialized"; refs.mkdir()
    rows=[]
    transcripts={}
    for input_id,name,text_value in (
        (125,"anchor","Booooa meu povo, aqui é BR no GTA 6."),
        (126,"vice","Vice City."),
        (127,"names","Rockstar Games, Jason Duval e Lucia Caminos."),
    ):
        path=refs/f"{name}.wav"
        payload=(name+"-audio").encode()
        path.write_bytes(payload)
        rows.append({
            "telegram_input_id":input_id,
            "runtime_path":str(path),
            "private_audio_ref":f"private://voice/BR_OWNER_V1/references/{input_id}",
            "sha256":hashlib.sha256(payload).hexdigest(),
        })
        transcripts[input_id]=text_value
    token=review_token_for_clone("BR_OWNER_V1_SINGLE_CLONE_FINAL_1")
    review=_promotion_review(token)
    review["telegram_chat_id"]=-1001
    review["telegram_message_id"]=704
    delivery=_promotion_delivery(token)
    delivery["telegram_chat_id"]=-1001
    delivery["confirmed_message_ids"]={"reference":702,"clone":703,"control":704}
    result=promote_approved_single_clone(
        review_receipt=review,
        delivery_state=delivery,
        materialized_references=rows,
        reference_transcripts=transcripts,
        private_store_root=private,
        repository_root=repo_root,
        promoted_at="2026-10-07T22:00:00Z",
    )
    assert result["status"]=="READY"

    enrollment_path=tmp_path/"enrollment.json"
    enrollment_path.write_text(json.dumps({
        "schema":"OwnerVoiceEnrollmentState/v1",
        "voice_identity_id":"BR_OWNER_V1",
        "consent_status":"APPROVED",
        "reference_source":"TELEGRAM",
        "official_voice":"BR_OWNER_V1",
        "active_voice_identities":["BR_OWNER_V1"],
        "provider_preset_voice_allowed":False,
        "generic_voice_fallback":False,
        "runtime_activation_status":"BLOCKED_HUMAN_VOICE_REVIEW",
        "owner_voice_status":"HISTORICAL_PUBLIC_STATUS_ONLY",
    }),encoding="utf-8")
    monkeypatch.setenv("BR_OWNER_ENROLLMENT_STATE_PATH",str(enrollment_path))
    monkeypatch.setenv("BR_PRIVATE_VOICE_STORE",str(private))

    profile=_default_owner_identity_resolver("BR_OWNER_V1")
    assert profile is not None
    assert profile["voice_identity_id"]=="BR_OWNER_V1"
    assert profile["clone_provider"]=="qwen3-tts"

    activation_path=private/"BR_OWNER_V1.runtime.json"
    activation=json.loads(activation_path.read_text())
    activation["profile_sha256"]="0"*64
    activation_path.write_text(json.dumps(activation),encoding="utf-8")
    assert _default_owner_identity_resolver("BR_OWNER_V1") is None
