from __future__ import annotations

from pathlib import Path

WORKFLOW=Path(".github/workflows/owner-voice-human-audition-pack.yml")
GENERATOR=Path("scripts/owner_voice_chatterbox_ptbr_audition.py")
CONSUMER=Path("scripts/owner_voice_human_audition_pack.py")


def test_workflow_establishes_one_run_scoped_private_workspace_and_explicit_manifest_path():
    text=WORKFLOW.read_text(encoding="utf-8")
    assert '$RUNNER_TEMP/br-owner-voice/$GITHUB_RUN_ID/$GITHUB_RUN_ATTEMPT' in text
    assert '$BR_OWNER_AUDITION_WORKSPACE/audition-manifest.json' in text
    assert '$BR_OWNER_AUDITION_WORKSPACE/delivery.json' in text
    assert 'BR_OWNER_AUDITION_WORKSPACE' in text
    assert 'BR_OWNER_AUDITION_MANIFEST_PATH' in text


def test_generator_uses_handoff_contract_and_is_sole_a_b_c_manifest_producer():
    text=GENERATOR.read_text(encoding="utf-8")
    assert "run_scoped_workspace" in text
    assert "commit_audition_handoff" in text
    assert 'f"{label}.wav"' in text or 'f"{candidate_id}.wav"' in text
    assert "OwnerVoicePtBrAuditionSet/v1" not in text


def test_consumer_requires_exact_manifest_env_and_never_reconstructs_path():
    text=CONSUMER.read_text(encoding="utf-8")
    assert 'BR_OWNER_AUDITION_MANIFEST_PATH' in text
    assert "consume_audition_handoff" in text
    assert 'temp/"br-owner-voice"/"ptbr-audition-set.json"' not in text
    assert "BR_OWNER_PTBR_AUDITION_SET" not in text


def test_consumer_uses_delivery_state_machine_and_media_group_not_three_voice_sends():
    text=CONSUMER.read_text(encoding="utf-8")
    assert "deliver_owner_voice_audition" in text
    assert "send_media_group" in text
    assert "sendMediaGroup" in text
    assert "sendVoice" not in text
    assert "_send_voice" not in text


def test_workflow_persists_sanitized_receipt_before_cleanup_and_never_uploads_audio():
    text=WORKFLOW.read_text(encoding="utf-8")
    receipt=text.index("Persist sanitized terminal or failure receipt")
    cleanup=text.index("Remove ephemeral owner biometric and clone material")
    assert receipt < cleanup
    assert "if: ${{ always() }}" in text[receipt:cleanup+200]
    upload=text[text.index("Upload sanitized receipt only"):text.index("Verify private audio never entered repository or public artifact")]
    assert "owner-voice-audition-delivery-receipt.json" in upload
    assert ".wav" not in upload


def test_consumer_uses_gitbacked_durable_v3_delivery_ledger():
    text=CONSUMER.read_text(encoding="utf-8")
    assert "GitHubGitTransactionStore" in text
    assert "GitBackedAuditionDeliveryLedger" in text
    assert "deliver_owner_voice_audition_durable" in text
    assert "harness-state" in text
    assert "deliver_owner_voice_audition(" not in text


def test_audition_job_has_state_write_permission_but_no_persisted_audio_path():
    text=WORKFLOW.read_text(encoding="utf-8")
    audition=text[text.index("  audition:"):]
    assert "contents: write" in audition
    assert "GITHUB_TOKEN:" in audition
    assert "BR_OWNER_AUDITION_AUTHORITY_REF:" in audition
    assert "harness-state" in CONSUMER.read_text(encoding="utf-8")
