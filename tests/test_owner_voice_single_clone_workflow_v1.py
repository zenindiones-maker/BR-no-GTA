from __future__ import annotations

from pathlib import Path

WORKFLOW=Path(".github/workflows/owner-voice-single-human-clone.yml")
ORCHESTRATOR=Path("scripts/owner_voice_single_human_clone.py")
DELIVERY=Path("scripts/owner_voice_single_clone_delivery.py")


def test_single_clone_workflow_is_explicitly_gated_and_never_runs_a_b_c():
    text=WORKFLOW.read_text(encoding="utf-8")
    assert ".run/br-owner-v1-single-human-clone.request.json" in text
    assert "needs.contract.outputs.clone_requested == 'true'" in text
    assert "ONE_CANDIDATE_ONLY=TRUE" in text
    assert "sendMediaGroup" not in text
    assert "candidate A" not in text and "candidate B" not in text and "candidate C" not in text


def test_single_clone_runtime_has_real_identity_profile_and_no_placeholder_similarity():
    source=ORCHESTRATOR.read_text(encoding="utf-8")
    assert "OwnerSpeakerIdentityProfile/v1" in source
    assert "speechbrain/spkrec-ecapa-voxceleb" in source
    assert "PENDING_INDEPENDENT_VERIFIER" not in source
    assert "Qwen/Qwen3-TTS-12Hz-1.7B-Base" in source
    assert "fd4b254389122332181a7c3db7f27e918eec64e3" in source
    assert "create_voice_clone_prompt" in source
    assert "generate_voice_clone" in source
    assert "x_vector_only_mode=False" in source
    assert 'language="Auto"' in source
    assert "TRANSCRIPT_CONDITIONED_ICL" in source
    assert 'identity_gate="PASS" if identity["passed"] is True else "FAIL"' in source
    assert 'print("CLONE_IDENTITY_GATE="+identity_gate)' in source
    assert 'print("QWEN3_TTS_IDENTITY_MATCH="+identity_gate)' in source
    assert "Chatterbox" not in source


def test_single_clone_delivery_sends_reference_clone_and_control_only():
    source=DELIVERY.read_text(encoding="utf-8")
    assert "copyMessage" in source
    assert "sendAudio" in source
    assert "sendMediaGroup" not in source
    assert "REFERENCE_TELEGRAM_MESSAGE_ID=" in source
    assert "CLONE_TELEGRAM_MESSAGE_ID=" in source
    assert "CONTROL_TELEGRAM_MESSAGE_ID=" in source
    assert "HUMAN_REVIEW=PENDING" in source
    assert "BLOCKED_PENDING_HUMAN_REVIEW" in source


def test_canonical_reference_uses_vad_occupancy_not_pcm_amplitude_proxy():
    source=ORCHESTRATOR.read_text(encoding="utf-8")
    assert "amplitude_speech_ratio" in source
    assert 'row["speech_ratio"]=vad_speech_ratio' in source
    assert "OWNER_CANONICAL_PRE_ASR_ELIGIBLE_COUNT=" in source
    assert "OWNER_CANONICAL_REFERENCE_ASR_COUNT=" in source
    assert "ranked[:12]" not in source


def test_single_clone_workflow_uses_qwen_runtime_not_chatterbox():
    text=WORKFLOW.read_text(encoding="utf-8")
    assert "qwen-tts==0.1.1" in text
    assert "integrations/qwen3-tts/constraints.txt" in text
    assert "chatterbox.git" not in text
    assert "integrations/chatterbox-ptbr/constraints.txt" not in text


def test_single_clone_audio_decode_does_not_depend_on_torchcodec():
    source=ORCHESTRATOR.read_text(encoding="utf-8")
    assert "soundfile as sf" in source
    assert "torchaudio.load" not in source
    assert "load_with_torchcodec" not in source


def test_qwen_reference_preserves_original_telegram_bandwidth_before_24k_clone_prompt():
    source=ORCHESTRATOR.read_text(encoding="utf-8")
    assert "original_sources[cid]" in source
    assert "ORIGINAL_TELEGRAM_TO_24K_DIRECT" in source
    assert '_ffmpeg(canonical16,workspace/"canonical-owner-reference-24k.wav",24000)' not in source


def test_auto_gate_failure_blocks_activation_but_not_human_audition_delivery():
    source=ORCHESTRATOR.read_text(encoding="utf-8")
    delivery=DELIVERY.read_text(encoding="utf-8")
    assert "build_human_review_delivery_decision" in source
    assert 'raise RuntimeError("OWNER_CLONE_IDENTITY_MISMATCH")' not in source
    assert 'raise RuntimeError("OWNER_SINGLE_CLONE_CONTENT_QA_FAILED")' not in source
    assert '"audition_delivery_eligible":review_decision["audition_delivery_eligible"]' in source
    assert 'payload.get("clone_identity_gate") not in {"PASS","FAIL"}' in delivery
    assert 'payload.get("runtime_activation") is not False' in delivery
    assert "Runtime activation: BLOQUEADA até aprovação humana." in delivery

def test_pronunciation_calibration_requires_newer_telegram_reference_boundary():
    source=ORCHESTRATOR.read_text(encoding="utf-8")
    assert ".run/br-owner-v1-single-human-clone.request.json" in source
    assert "pronunciation_after_message_id" in source
    assert "OWNER_PRONUNCIATION_REFERENCE_COUNT=" in source
    assert "OWNER_PRONUNCIATION_REFERENCE_NOT_MATERIALIZED" in source
    assert "PRONUNCIATION_REFERENCE_SCOPE=FRESH_TELEGRAM_ONLY" in source
    assert "IDENTITY_REFERENCE_SCOPE=GLOBAL_OWNER_INLIERS" in source
    assert "QWEN3_TTS_LANGUAGE_MODE=AUTO_CODE_SWITCH" in source


def test_pronunciation_audition_challenges_official_gta_vi_names():
    source=ORCHESTRATOR.read_text(encoding="utf-8")
    for term in (
        "Vice City",
        "Jason Duval",
        "Lucia Caminos",
        "Cal Hampton",
        "Boobie Ike",
        "Dre'Quan Priest",
        "Real Dimez",
        "Raul Bautista",
        "Brian Heder",
    ):
        assert term in source



def test_private_materializer_preserves_message_id_for_pronunciation_boundary():
    service=Path("app/services/owner_voice_private_materialization_service.py").read_text(encoding="utf-8")
    assert '"telegram_message_id": int(item["telegram_message_id"])' in service


def test_pending_telegram_recovery_is_non_acknowledging_and_owner_scoped():
    service=Path("app/services/owner_voice_telegram_pending_recovery_service.py").read_text(encoding="utf-8")
    assert '"getUpdates"' in service
    assert '"offset"' not in service
    assert "after_message_id" in service
    assert "telegram_user_id" in service
    assert "telegram_chat_id" in service
    assert "recovered_reference_count" in service


def test_owner_voice_handoff_keeps_secret_authoritative_when_dispatch_is_unavailable():
    service=Path("app/services/owner_voice_telegram_handoff_service.py").read_text(encoding="utf-8")
    command=Path("scripts/owner_voice_reference_handoff.py").read_text(encoding="utf-8")
    assert "OWNER_REFERENCE_MATERIALIZATION_DISPATCH_FAILED" not in service
    assert "SECRET_UPDATED_DISPATCH_DEFERRED" in service
    assert 'receipt["status"]' in command


def test_pronunciation_refs_do_not_replace_global_identity_anchor():
    source=ORCHESTRATOR.read_text(encoding="utf-8")
    assert "fresh_reference_ids" in source
    assert "OWNER_PRONUNCIATION_REFERENCE_COUNT=" in source
    assert "pronunciation_after_message_id<=0 or int(row" not in source
    assert '"pronunciation_reference_count":len(pronunciation_refs)' in source
