from pathlib import Path
import json

CONFIG=Path("config/owner_voice_qwen3_tts_finetune_v1.json")
DATASET=Path("scripts/owner_voice_qwen3_tts_finetune_dataset.py")
WORKFLOW=Path(".github/workflows/owner-voice-qwen3-tts-finetune.yml")
SINGLE_CLONE_REQUEST=Path(".run/br-owner-v1-single-human-clone.request.json")


def test_finetune_policy_is_single_human_qwen_17b_only():
    row=json.loads(CONFIG.read_text(encoding="utf-8"))
    assert row["schema_version"]=="OwnerVoiceQwen3TTSFineTunePolicy/v2"
    assert row["voice_identity_id"]=="BR_OWNER_V1"
    assert row["reference_source"]=="TELEGRAM_HUMAN_OWNER"
    assert row["model_id"]=="Qwen/Qwen3-TTS-12Hz-1.7B-Base"
    assert row["trainer_engine"]=="modelscope/ms-swift"
    assert row["trainer_commit"]=="6f62bd4b3032197dce934b4eba1bb65463b29918"
    assert row["single_speaker_only"] is True
    assert row["same_ref_audio_for_all_samples"] is True
    assert row["generic_voice_fallback"] is False
    assert row["provider_default_voice"] is False
    assert row["provider_preset_voice"] is False
    assert row["runtime_activation_after_training"] is False
    assert row["human_review_required"] is True


def test_zero_shot_is_terminally_disarmed_after_calibrated_identity_fail():
    row=json.loads(CONFIG.read_text(encoding="utf-8"))
    boundary=row["zero_shot_boundary"]
    assert boundary["status"]=="BLOCKED_AFTER_CALIBRATED_IDENTITY_FAIL"
    assert boundary["run_id"]==37546522842
    assert boundary["clone_similarity_to_centroid"] < boundary["centroid_min_similarity"]
    assert boundary["telegram_side_effect"]=="NONE"
    assert boundary["retry_policy"]=="DO_NOT_REPEAT_ZERO_SHOT_WITH_SAME_ARCHITECTURE"
    assert not SINGLE_CLONE_REQUEST.exists()


def test_dataset_is_owner_only_and_emits_ms_swift_native_rows():
    source=DATASET.read_text(encoding="utf-8")
    assert 'VOICE_IDENTITY_ID="BR_OWNER_V1"' in source
    assert 'REFERENCE_SOURCE="TELEGRAM_HUMAN_OWNER"' in source
    assert '"ref_audio":str(canonical24.resolve())' in source
    assert '"messages":[{"role":"assistant","content":text}]' in source
    assert '"audios":[str(audio.resolve())]' in source
    assert '"ref_audios":[str(canonical24.resolve())]' in source
    assert "train_swift_jsonl=" in source
    assert '"raw_audio_public":False' in source
    assert '"transcripts_public":False' in source
    assert '"speaker_embedding_public":False' in source


def test_training_workflow_is_request_gated_private_gpu_and_pinned_ms_swift():
    source=WORKFLOW.read_text(encoding="utf-8")
    assert "br-owner-v1-qwen3-tts-finetune.request.json" in source
    assert "needs.contract.outputs.train_requested == 'true'" in source
    assert "br-owner-voice-gpu" in source
    assert "nvidia-smi" in source
    assert "modelscope/ms-swift.git@6f62bd4b3032197dce934b4eba1bb65463b29918" in source
    assert "--model Qwen/Qwen3-TTS-12Hz-1.7B-Base" in source
    assert "--tuner_type full" in source
    assert "--learning_rate 2e-6" in source
    assert "runtime_activation=false" in source
    assert "actions/upload-artifact" not in source
