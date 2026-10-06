from __future__ import annotations

from pathlib import Path

WORKFLOW=Path(".github/workflows/owner-voice-human-audition-pack.yml")
GENERATOR=Path("scripts/owner_voice_chatterbox_ptbr_audition.py")
CONSUMER=Path("scripts/owner_voice_human_audition_pack.py")


def test_workflow_establishes_one_run_scoped_private_workspace_and_explicit_generator_outputs():
    text=WORKFLOW.read_text(encoding="utf-8")
    assert '$RUNNER_TEMP/br-owner-voice/$GITHUB_RUN_ID/$GITHUB_RUN_ATTEMPT' in text
    assert '$BR_OWNER_AUDITION_WORKSPACE/delivery.json' in text
    assert 'BR_OWNER_AUDITION_WORKSPACE' in text
    assert 'steps.generate.outputs.manifest_path' in text
    assert 'steps.generate.outputs.pack_id' in text
    assert '/tmp/br-owner-voice/ptbr-audition-set.json' not in text


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
    assert "path: ${{ env.BR_OWNER_AUDITION_TERMINAL_RECEIPT }}" in upload
    assert "owner-voice-audition-delivery-receipt.json" in text
    assert ".wav" not in upload


def test_consumer_uses_gitbacked_durable_v3_delivery_ledger():
    text=CONSUMER.read_text(encoding="utf-8")
    assert "store_from_environment" in text
    assert "GitBackedAuditionDeliveryLedger" in text
    assert "deliver_owner_voice_audition_durable" in text
    assert "GitHubGitTransactionStore" not in text
    assert "GITHUB_TOKEN" not in text
    assert "deliver_owner_voice_audition(" not in text


def test_audition_job_is_read_only_and_ledger_key_is_step_scoped():
    text=WORKFLOW.read_text(encoding="utf-8")
    audition=text[text.index("  audition:"):]
    assert "contents: read" in audition
    assert "contents: write" not in audition
    assert "GITHUB_TOKEN:" not in audition
    assert "BR_OWNER_AUDITION_AUTHORITY_REF:" in audition
    expected="BR_OWNER_AUDITION_LEDGER_SSH_KEY: $" + "{{ secrets.BR_OWNER_AUDITION_LEDGER_SSH_KEY }}"
    assert audition.count(expected)==3


def test_workflow_preflights_secrets_before_model_download_and_pins_stt_decode_contract():
    text=WORKFLOW.read_text(encoding="utf-8")
    preflight=text.index("Preflight required audition secrets")
    stt=text.index("Install strong private STT runtime")
    chatterbox=text.index("Install isolated pinned Chatterbox PT-BR runtime")
    assert preflight < stt < chatterbox
    for expected in (
        "TELEGRAM_BOT_TOKEN_PRESENT=",
        "OWNER_REFERENCE_ENVELOPE_PRESENT=",
        "AUDITION_LEDGER_KEY_PRESENT=",
        '"faster-whisper==1.2.0"',
        '"av==18.0.0"',
        "PYAV_MAJOR_LT_19=TRUE",
        "STT_AUDIO_DECODE_COMPATIBILITY=PASS",
    ):
        assert expected in text


def test_workflow_runs_contract_on_recovery_push_but_gates_heavy_audition_on_explicit_request():
    text=WORKFLOW.read_text(encoding="utf-8")
    assert "recovery/dev/br-owner-v1-human-audition-v2" in text
    assert "audition_requested" in text
    assert ".run/br-owner-v1-human-audition.request.json" in text
    assert "needs.contract.outputs.audition_requested == 'true'" in text


def test_consumer_emits_exact_human_delivery_success_boundary():
    text=CONSUMER.read_text(encoding="utf-8")
    for expected in (
        "REFERENCE_TELEGRAM_MESSAGE_ID=",
        "A_TELEGRAM_MESSAGE_ID=",
        "B_TELEGRAM_MESSAGE_ID=",
        "C_TELEGRAM_MESSAGE_ID=",
        "CONTROL_TELEGRAM_MESSAGE_ID=",
        "AUDITION_DELIVERED_TO_TELEGRAM=PASS",
        "HUMAN_REVIEW=PENDING",
        "BR_OWNER_V1_RUNTIME_ACTIVATION=BLOCKED_PENDING_HUMAN_REVIEW",
    ):
        assert expected in text


def test_request_validation_is_noop_for_implementation_push_without_marker():
    text=WORKFLOW.read_text(encoding="utf-8")
    validate=text[text.index("Validate request"):text.index("Prove audition handoff and delivery contracts")]
    assert 'if [ ! -f .run/br-owner-v1-human-audition.request.json ]' in validate
    assert 'AUDITION_REQUEST_PRESENT=false' in validate
    assert 'AUDITION_REQUEST_PRESENT=true' in validate


def test_prescreen_observability_is_sanitized_and_per_candidate():
    text=CONSUMER.read_text(encoding="utf-8")
    assert "MachineAuditionCandidateQA/v1" in text
    assert 'print(f"CANDIDATE_{label}_{name}={value}")' in text
    for suffix in (
        "QA_ELIGIBLE","QA_ISSUES","LANGUAGE","LANGUAGE_PROBABILITY",
        "WER","CER","DURATION_SECONDS","CLIPPING_RATIO","SPEECH_RATIO",
        "MISSING_WORD_ESTIMATE","INSERTED_WORD_ESTIMATE","REPETITION_COUNT",
    ):
        assert f'emit("{suffix}"' in text
    sanitized=text[
        text.index("def _sanitized_machine_qa"):
        text.index("def _emit_sanitized_candidate_qa")
    ]
    assert "observed_text" not in sanitized
    assert "runtime_path" not in sanitized
    assert "OwnerVoiceAuditionFailureReceipt/v1" in text
    assert '"failure_step":"machine_prescreen"' in text
    assert '"side_effect_state":"NOT_STARTED"' in text


def test_receipt_upload_uses_run_scoped_env_path_not_tmp_hardcode():
    text=WORKFLOW.read_text(encoding="utf-8")
    upload=text[text.index("Upload sanitized receipt only"):text.index("Verify private audio never entered repository or public artifact")]
    assert "path: ${{ env.BR_OWNER_AUDITION_TERMINAL_RECEIPT }}" in upload
    assert "/tmp/br-owner-audition-public" not in upload
