from __future__ import annotations

from pathlib import Path

WORKFLOW=Path(".github/workflows/owner-voice-private-materialization.yml")
AUDIT=Path("scripts/owner_voice_professional_corpus_audit.py")


def test_private_materialization_workflow_is_audit_only_before_bakeoff():
    text=WORKFLOW.read_text(encoding="utf-8")
    assert "BR_OWNER_STT_MODEL: large-v3" in text
    assert "scripts/owner_voice_professional_corpus_audit.py" in text
    assert "owner-voice-professional-corpus-audit-public" in text
    assert "/tmp/br-owner-professional-public" in text
    assert "scripts/owner_voice_chatterbox_ptbr_audition.py" not in text
    assert "scripts/owner_voice_qwen_ephemeral_audition.py" not in text
    assert "OWNER_VOICE_BAKEOFF=BLOCKED_UNTIL_CORPUS_AUDIT_RECONCILED" in text


def test_public_artifact_path_excludes_private_audio_and_transcripts():
    text=WORKFLOW.read_text(encoding="utf-8")
    upload=text[text.index("Upload sanitized professional corpus evidence only"):]
    upload=upload[:upload.index("Verify repository contains no owner biometric material")]
    assert "/tmp/br-owner-professional-public" in upload
    assert "/tmp/br-owner-voice" not in upload
    assert "/tmp/br-owner-professional-audit/private" not in upload


def test_professional_audit_keeps_private_transcript_out_of_public_inventory():
    text=AUDIT.read_text(encoding="utf-8")
    assert "owner-voice-corpus-inventory-private.json" in text
    assert "owner-voice-corpus-inventory-v1.json" in text
    assert "OWNER_TRANSCRIPT_IN_PUBLIC_ARTIFACT=0" in text
    assert 'model_id=str(os.environ.get("BR_OWNER_STT_MODEL") or "large-v3")' in text
