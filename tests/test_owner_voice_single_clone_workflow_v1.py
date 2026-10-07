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
    assert 'language="Portuguese"' in source
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
