from pathlib import Path

from app.services.recovery_manifest_service import (
    DELEGATED_AUTONOMY_PROOF_RUN_ID,
    FOCUSED_TESTS,
    build_recovery_manifest,
)


def test_recovery_manifest_is_forward_only_and_audio_fingerprinted(tmp_path: Path):
    repo=Path.cwd()
    manifest=build_recovery_manifest(
        repo_root=repo,
        branch="work/gate6f-analytics-learning",
        head_sha="a"*40,
        checkpoint_type="test",
        git_tag="br-recovery-test",
        tests_passed=list(FOCUSED_TESTS),
        created_at="2026-09-19T23:30:00+00:00",
    )
    assert manifest["status"]=="PASS"
    assert manifest["delegated_autonomy_proof_run_id"]==DELEGATED_AUTONOMY_PROOF_RUN_ID==35473635778
    assert manifest["operational_state"]["DELEGATED_AUTONOMY"]=="PASS"
    assert manifest["operational_state"]["HARNESS_SOLE_AUTHORITY"]=="PASS"
    assert manifest["harness_authority_contract"]["agent_office_authority"]=="DELEGATED_ONLY"
    assert manifest["harness_authority_contract"]["codex_canonical_push_authority"]=="NONE"
    assert manifest["validity"]["recovery_mode"]=="FORWARD_ONLY"
    assert manifest["invalidation_rules"]["never_reset_branch_to_checkpoint"] is True
    assert manifest["current_audio_contract_fingerprint"]
    assert len(manifest["current_audio_contract_fingerprint"])==64
    invalidated=manifest["invalidation_rules"]["audio_contract_mismatch"]["invalidates"]
    assert invalidated==["Narration","Brand Audio","EditPlan","RenderJob","Render"]
    preserved=manifest["invalidation_rules"]["audio_contract_mismatch"]["preserves_if_fingerprint_valid"]
    assert "Research" in preserved and "MediaKnowledge" in preserved
    assert manifest["human_approved_asset_hashes"]["assets/branding/audio/g-brand-mixed-approved-20260919.mp3"]=="9e2e7a2d9717f460dd45cf0d07e96a4596e4f61372c6d87028b8809a052c59ca"


def test_recovery_manifest_records_final_private_youtube_and_telegram_milestone(tmp_path: Path):
    repo=Path.cwd()
    manifest=build_recovery_manifest(
        repo_root=repo,
        branch="work/gate6f-analytics-learning",
        head_sha="b"*40,
        checkpoint_type="video-a-private-human-review",
        git_tag="br-recovery-final-test",
        tests_passed=list(FOCUSED_TESTS),
        created_at="2026-09-20T01:50:00+00:00",
    )
    final=manifest["final_delivery_checkpoint"]
    assert final is not None
    assert manifest["youtube_publication_id"]==1
    assert manifest["video_id"]==1
    assert manifest["render_job_id"]==2
    assert final["youtube_review_video_id"]=="4IKhAiC5mTs"
    assert final["youtube_privacy_status"]=="private"
    assert final["youtube_processing_status"]=="READY"
    assert final["telegram_delivery_status"]=="PASS"
    assert final["telegram_message_id"]==201
    assert final["human_review_status"]=="PENDING"
    assert final["render_media_sha256"]=="7cfbca3f36ec66b832c93df80dc929ca931c5d70fa63a6a3c74d64824e369436"
    assert manifest["database_checkpoint"]["artifact_id"]==10596163504
