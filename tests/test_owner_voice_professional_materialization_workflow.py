from pathlib import Path

WORKFLOW=Path(".github/workflows/owner-voice-private-materialization.yml")

def test_owner_voice_private_materialization_is_audit_first():
    text=WORKFLOW.read_text(encoding="utf-8")
    assert ("BR_OWNER_STT_MODEL: large-v3-turbo" in text or "BR_OWNER_STT_MODEL: large-v3" in text)
    assert "BR_OWNER_STT_MODEL: medium" not in text
    assert "BR_OWNER_STT_MODEL: tiny" not in text
    assert "scripts/owner_voice_professional_corpus_audit.py" in text
    assert "owner-voice-professional-corpus-audit-public" in text
    assert "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02" in text
    assert "scripts/owner_voice_chatterbox_ptbr_audition.py" not in text
    assert "scripts/owner_voice_ptbr_audition_review.py" not in text
    assert "RAW_OWNER_AUDIO_IN_PUBLIC_ARTIFACT=0" in text
