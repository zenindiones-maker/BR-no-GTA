from pathlib import Path
import json

CONFIG=Path("config/owner_voice_qwen3_tts_finetune_v1.json")
DATASET=Path("scripts/owner_voice_qwen3_tts_finetune_dataset.py")
PATCHER=Path("scripts/owner_voice_qwen3_tts_finetune_patch.py")
WORKFLOW=Path(".github/workflows/owner-voice-qwen3-tts-finetune.yml")


def test_finetune_policy_is_single_human_qwen_17b_only():
    row=json.loads(CONFIG.read_text(encoding="utf-8"))
    assert row["voice_identity_id"]=="BR_OWNER_V1"
    assert row["reference_source"]=="TELEGRAM_HUMAN_OWNER"
    assert row["model_id"]=="Qwen/Qwen3-TTS-12Hz-1.7B-Base"
    assert row["single_speaker_only"] is True
    assert row["same_ref_audio_for_all_samples"] is True
    assert row["generic_voice_fallback"] is False
    assert row["provider_default_voice"] is False
    assert row["provider_preset_voice"] is False
    assert row["runtime_activation_after_training"] is False
    assert row["human_review_required"] is True


def test_dataset_never_uses_non_owner_reference_or_public_biometric_artifacts():
    source=DATASET.read_text(encoding="utf-8")
    assert 'VOICE_IDENTITY_ID="BR_OWNER_V1"' in source
    assert 'REFERENCE_SOURCE="TELEGRAM_HUMAN_OWNER"' in source
    assert '"ref_audio":str(canonical24.resolve())' in source
    assert '"raw_audio_public":False' in source
    assert '"transcripts_public":False' in source
    assert '"speaker_embedding_public":False' in source


def test_patcher_closes_known_upstream_alignment_failures():
    source=PATCHER.read_text(encoding="utf-8")
    assert 'UPSTREAM_COMMIT="022e286b98fbec7e1e916cb940cdf532cd9f488e"' in source
    assert "text_projection" in source
    assert "remove_future_codec_leak" in source
    assert "previous_frame_mask" in source
    assert "shift_labels=labels.contiguous()" in source


def test_training_workflow_is_manual_private_gpu_only_and_never_auto_activates():
    source=WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in source
    assert "push:" not in source
    assert "br-owner-voice-gpu" in source
    assert "nvidia-smi" in source
    assert "runtime_activation=false" in source
    assert "actions/upload-artifact" not in source
