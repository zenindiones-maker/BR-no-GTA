from pathlib import Path

SCRIPT=Path("scripts/owner_voice_human_audition_pack.py")
WORKFLOW=Path(".github/workflows/owner-voice-human-audition-pack.yml")

def test_pack_runtime_consumes_generated_manifest_instead_of_regenerating_model():
    text=SCRIPT.read_text(encoding="utf-8")
    assert "BR_OWNER_PTBR_AUDITION_SET" in text
    assert "OwnerVoicePtBrAuditionSet/v1" in text
    assert "download_ptbr_model_assets" not in text
    assert "load_ptbr_chatterbox_model" not in text
    assert "model.generate(" not in text
    assert "torch" not in text
    assert "torchaudio" not in text

def test_sanitized_receipt_env_matches_workflow_upload_path():
    script=SCRIPT.read_text(encoding="utf-8")
    workflow=WORKFLOW.read_text(encoding="utf-8")
    assert "BR_OWNER_AUDITION_PUBLIC_RECEIPT" in script
    assert "BR_OWNER_AUDITION_PUBLIC_RECEIPT:" in workflow
    assert "/tmp/br-owner-audition-public/owner-voice-human-audition-pack.json" in workflow

def test_workflow_generates_once_then_machine_screens_and_sends():
    text=WORKFLOW.read_text(encoding="utf-8")
    gen=text.index("Generate three comparable BR_OWNER_V1 candidates")
    review=text.index("Machine pre-screen and send protected blind pack to Telegram")
    assert gen < review
    assert "scripts/owner_voice_chatterbox_ptbr_audition.py" in text
    assert "scripts/owner_voice_human_audition_pack.py" in text
