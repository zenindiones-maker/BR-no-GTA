from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from app.services.current_audio_contract_service import current_audio_contract


SCHEMA_VERSION = "br-no-gta-recovery-manifest/v1"
AGENT_OFFICE_CONTRACT_VERSION = {
    "coordinator": "2",
    "specialist_readonly": "1",
    "specialist_development": "1",
}
DELEGATED_AUTONOMY_PROOF_RUN_ID = 35473635778
DELEGATED_AUTONOMY_ARTIFACT_ID = 10593442720
PRODUCT_CHECKPOINT_RUN_ID = 35458162169
PRODUCT_CHECKPOINT_ARTIFACT_ID = 10589535732
MEDIA_KNOWLEDGE_RUN_ID = 35460016361
MEDIA_KNOWLEDGE_ARTIFACT_ID = 10590341059
HISTORICAL_RENDER_STATE_RUN_ID = 35463603082
HISTORICAL_RENDER_STATE_ARTIFACT_ID = 10590247951

ARTIFACT_SHA256 = {
    str(PRODUCT_CHECKPOINT_ARTIFACT_ID): "2566cb11f99b1d6c70f47e886f590e1cbcd8e9cc5c678cc2cf36f974c56402a9",
    str(MEDIA_KNOWLEDGE_ARTIFACT_ID): "f8ff0ef7c1d3c766fc84c90ef5a0f1f90d051b226818f2571cad0dcba757cbe9",
    str(HISTORICAL_RENDER_STATE_ARTIFACT_ID): "0a80177da81e0b54de50fbf469e82683ed08d2fe8b2875f97b0435c822354215",
    str(DELEGATED_AUTONOMY_ARTIFACT_ID): "2ce1e8b8adf99e5460dae559626bdd815f54429b413068d0d067be77f44f2397",
}
DATABASE_CHECKPOINT = {
    "run_id": PRODUCT_CHECKPOINT_RUN_ID,
    "artifact_id": PRODUCT_CHECKPOINT_ARTIFACT_ID,
    "file": "mission.db",
    "sha256": "e569a61befbe86fcf16d84483624816f577917da79df370dbbaf940b26b0e22e",
    "artifact_zip_sha256": ARTIFACT_SHA256[str(PRODUCT_CHECKPOINT_ARTIFACT_ID)],
    "retention_policy": "locator+sha256+rematerialize-from-provenance",
}
PRODUCT_PACKAGE = {
    "run_id": PRODUCT_CHECKPOINT_RUN_ID,
    "artifact_id": PRODUCT_CHECKPOINT_ARTIFACT_ID,
    "file": "product-quality-e2e.json",
    "sha256": "644c33b71d3c46e944e875ce9845a4e407ae0beec84072a512e269e40d64c323",
}
FOCUSED_TESTS = [
    "tests/test_current_audio_contract.py",
    "tests/test_channel_spoken_branding.py",
    "tests/test_delegated_agent_autonomy.py",
    "tests/test_agent_office.py",
    "tests/test_video_a_current_contract_e2e.py",
    "tests/test_recovery_manifest_service.py",
]


class RecoveryManifestError(RuntimeError):
    pass


def _read_json(path: Path) -> dict[str, Any]:
    value=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value,dict):
        raise RecoveryManifestError(f"{path} must contain a JSON object")
    return value


def build_recovery_manifest(
    *,
    repo_root: Path,
    branch: str,
    head_sha: str,
    checkpoint_type: str,
    git_tag: str,
    tests_passed: list[str],
    created_at: str | None = None,
    runtime_state_path: Path | None = None,
) -> dict[str, Any]:
    root=repo_root.resolve()
    request=_read_json(root/".run/video-a-current-product-e2e.request.json")
    save_request_path=root/".run/checkpoint-save.request.json"
    save_request=_read_json(save_request_path) if save_request_path.is_file() else {}
    audio=current_audio_contract()

    state: dict[str, Any]={}
    if runtime_state_path is not None and runtime_state_path.is_file():
        state=_read_json(runtime_state_path)

    goal_id=str(request["goal_id"])
    video_id=state.get("VIDEO_ID", request.get("video_id", 1))
    render_job_id=state.get("RENDER_JOB_ID", request.get("successor_render_job_id"))
    render_run_id=state.get("RENDER_RUN_ID")
    youtube_publication_id=state.get("PUBLICATION_ID") or state.get("youtube_publication_id")

    manifest={
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "branch": branch,
        "head_sha": head_sha,
        "created_at": created_at or datetime.now(timezone.utc).isoformat(),
        "checkpoint_type": checkpoint_type,
        "git_tag": git_tag,
        "goal_id": goal_id,
        "content_item_id": 1,
        "script_id": 1,
        "production_plan_id": 1,
        "video_id": video_id,
        "render_job_id": render_job_id,
        "render_run_id": render_run_id,
        "youtube_publication_id": youtube_publication_id,
        "artifact_ids": [
            PRODUCT_CHECKPOINT_ARTIFACT_ID,
            MEDIA_KNOWLEDGE_ARTIFACT_ID,
            HISTORICAL_RENDER_STATE_ARTIFACT_ID,
            DELEGATED_AUTONOMY_ARTIFACT_ID,
        ],
        "artifact_sha256": dict(ARTIFACT_SHA256),
        "artifact_provenance": {
            str(PRODUCT_CHECKPOINT_ARTIFACT_ID): {"run_id": PRODUCT_CHECKPOINT_RUN_ID, "role": "product-package+database"},
            str(MEDIA_KNOWLEDGE_ARTIFACT_ID): {"run_id": MEDIA_KNOWLEDGE_RUN_ID, "role": "content-addressed-media-knowledge"},
            str(HISTORICAL_RENDER_STATE_ARTIFACT_ID): {"run_id": HISTORICAL_RENDER_STATE_RUN_ID, "role": "historical-render-identity-only"},
            str(DELEGATED_AUTONOMY_ARTIFACT_ID): {"run_id": DELEGATED_AUTONOMY_PROOF_RUN_ID, "role": "delegated-autonomy-proof"},
        },
        "database_checkpoint": dict(DATABASE_CHECKPOINT),
        "product_package_checkpoint": dict(PRODUCT_PACKAGE),
        "current_audio_contract_fingerprint": audio["CURRENT_AUDIO_CONTRACT_FINGERPRINT"],
        "official_voice_profile": {
            "OFFICIAL_VOICE": audio["OFFICIAL_VOICE"],
            "VOICE_SHORT_NAME": audio["VOICE_SHORT_NAME"],
            "SINGLE_VOICE_ONLY": audio["SINGLE_VOICE_ONLY"],
            "ALTERNATIVE_VOICE_CASTING": audio["ALTERNATIVE_VOICE_CASTING"],
            "OPENING_REFERENCE": audio["OPENING_REFERENCE"],
            "OPENING_TAKE": audio["OPENING_TAKE"],
            "OPENING_RATE": audio["OPENING_RATE"],
            "OPENING_PITCH": audio["OPENING_PITCH"],
            "CLOSING_ASSET": audio["CLOSING_ASSET"],
            "CLOSING_ASSET_POLICY": audio["CLOSING_ASSET_POLICY"],
            "GTA_6_SYNTHESIS": audio["GTA_6_SYNTHESIS"],
            "VICE_CITY_LOCALE": audio["VICE_CITY_LOCALE"],
            "VICE_CITY_TARGET_IPA": audio["VICE_CITY_TARGET_IPA"],
        },
        "spoken_branding_contract": audio["SPOKEN_BRANDING_CONTRACT"],
        "pronunciation_lexicon_version": audio["PRONUNCIATION_LEXICON_VERSION"],
        "human_approved_asset_hashes": {
            "assets/branding/audio/g-brand-mixed-approved-20260919.mp3": audio["APPROVED_G_SHA256"],
            "assets/branding/audio/closing-from-g-approved-20260919.flac": audio["DERIVED_CLOSING_SHA256"],
        },
        "agent_office_contract_version": dict(AGENT_OFFICE_CONTRACT_VERSION),
        "delegated_autonomy_proof_run_id": DELEGATED_AUTONOMY_PROOF_RUN_ID,
        "harness_authority_contract": {
            "issuer": "deepseek_harness",
            "sole_authority": True,
            "agent_office_authority": "DELEGATED_ONLY",
            "codex_canonical_push_authority": "NONE",
            "munder_difflin": "SUBORDINATE",
        },
        "tests_required": list(FOCUSED_TESTS),
        "tests_passed": list(tests_passed),
        "validity": {
            "recovery_mode": "FORWARD_ONLY",
            "head_authority": "NEWEST_REMOTE_HEAD",
            "reuse_rule": "reuse layer only when fingerprint/hash/schema/code-profile version still matches",
            "historical_render_is_product_final": False,
            "current_audio_contract_required_for_final_video": True,
        },
        "invalidation_rules": {
            "audio_contract_mismatch": {
                "invalidates": ["Narration", "Brand Audio", "EditPlan", "RenderJob", "Render"],
                "preserves_if_fingerprint_valid": ["Research", "Brain", "ContentItem", "Script", "ProductionPlan", "MediaKnowledge", "media checkpoint"],
            },
            "never_reset_branch_to_checkpoint": True,
            "recovery_formula": "NEWEST_HEAD + VALID_OLD_ARTIFACTS -> CURRENT_PRODUCT",
        },
        "durability_policy": {
            "small_human_approved_assets": "git-versioned+sha256",
            "large_artifacts": "locator+sha256+provenance+retention/rematerialization-policy",
            "database": "manifested locator+file sha256; no reliance on run-memory",
            "github_actions_artifact_alone_is_not_durable_human_state": True,
        },
        "operational_state": {
            "DELEGATED_AUTONOMY_PROOF_RUN": DELEGATED_AUTONOMY_PROOF_RUN_ID,
            "DELEGATED_AUTONOMY": "PASS",
            "HARNESS_SOLE_AUTHORITY": "PASS",
            "AGENT_OFFICE": "ACTIVE",
            "CODEX_BOUNDED_DEVELOPMENT": "ACTIVE",
            "MUNDER_DIFFLIN": "SUBORDINATE",
            "ADDY_TASK_OWNERS": "ACTIVE",
            "VIDEO_A_CURRENT_E2E_RUN": save_request.get("video_a_e2e_run_id"),
        },
    }
    required=[
        "branch","head_sha","created_at","checkpoint_type","git_tag","goal_id",
        "content_item_id","script_id","production_plan_id","video_id","render_job_id",
        "artifact_ids","artifact_sha256","database_checkpoint",
        "current_audio_contract_fingerprint","official_voice_profile",
        "spoken_branding_contract","pronunciation_lexicon_version",
        "human_approved_asset_hashes","agent_office_contract_version",
        "delegated_autonomy_proof_run_id","harness_authority_contract",
        "tests_required","tests_passed","validity","invalidation_rules",
    ]
    missing=[key for key in required if manifest.get(key) is None]
    if missing:
        raise RecoveryManifestError(f"recovery manifest missing required state: {missing}")
    if set(manifest["tests_required"]) - set(manifest["tests_passed"]):
        raise RecoveryManifestError("focused deterministic tests are not all proven PASS")
    if len(str(manifest["current_audio_contract_fingerprint"])) != 64:
        raise RecoveryManifestError("current audio contract fingerprint is invalid")
    return manifest
