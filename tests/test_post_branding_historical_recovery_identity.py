"""Regression tests for historical post-branding recovery identity tolerance."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest


def _identity_check(
    job: dict[str, Any],
    root: Path,
    expected_brain: str,
    expected_exec: str,
    expected_action: str,
    contract_fp: str,
    contract_voice: str,
) -> str:
    """Mirror of the workflow recovery identity rules (for regression)."""
    if int(job.get("render_job_id") or job.get("id") or 0) <= 0:
        raise SystemExit("BLOCKED_MISSING_RENDER_JOB_ID")
    if int(job.get("video_id") or 0) <= 0:
        raise SystemExit("BLOCKED_MISSING_VIDEO_ID")
    if job.get("brain_decision_id") != expected_brain:
        raise SystemExit("BLOCKED_DIVERGENT_BRAIN")
    if job.get("execution_id") != expected_exec:
        raise SystemExit("BLOCKED_DIVERGENT_EXECUTION")
    if job.get("authorized_action") != expected_action:
        raise SystemExit("BLOCKED_DIVERGENT_ACTION")
    fp = job.get("current_audio_contract_fingerprint")
    if fp is not None and fp != contract_fp:
        raise SystemExit("BLOCKED_INCOMPATIBLE_AUDIO_CONTRACT_FINGERPRINT")
    voice = (job.get("narration") or {}).get("voice")
    if voice is not None and voice != contract_voice:
        raise SystemExit("BLOCKED_INCOMPATIBLE_VOICE")
    has_script = (root / "script-ptbr.json").is_file()
    brand_files = list(root.glob("brand-assets.json"))
    if not has_script or not brand_files:
        raise SystemExit("BLOCKED_MISSING_HISTORICAL_IDENTITY_EVIDENCE")
    return "PASS"


def test_historical_artifact_without_fingerprint_proceeds(tmp_path: Path):
    root = tmp_path / "out"
    root.mkdir()
    (root / "script-ptbr.json").write_text("{}")
    (root / "brand-assets.json").write_text("[]")
    job = {"render_job_id": 1, "video_id": 1, "brain_decision_id": "b", "execution_id": "e", "authorized_action": "EXECUTION"}
    assert _identity_check(job, root, "b", "e", "EXECUTION", "fp", "voice") == "PASS"


def test_present_incompatible_fingerprint_blocks(tmp_path: Path):
    root = tmp_path / "out"
    root.mkdir()
    (root / "script-ptbr.json").write_text("{}")
    (root / "brand-assets.json").write_text("[]")
    job = {"render_job_id": 1, "video_id": 1, "brain_decision_id": "b", "execution_id": "e", "authorized_action": "EXECUTION", "current_audio_contract_fingerprint": "wrong"}
    with pytest.raises(SystemExit, match="BLOCKED_INCOMPATIBLE_AUDIO_CONTRACT_FINGERPRINT"):
        _identity_check(job, root, "b", "e", "EXECUTION", "expected", "voice")


def test_missing_substitute_evidence_blocks(tmp_path: Path):
    root = tmp_path / "out"
    root.mkdir()
    job = {"render_job_id": 1, "video_id": 1, "brain_decision_id": "b", "execution_id": "e", "authorized_action": "EXECUTION"}
    with pytest.raises(SystemExit, match="BLOCKED_MISSING_HISTORICAL_IDENTITY_EVIDENCE"):
        _identity_check(job, root, "b", "e", "EXECUTION", "fp", "voice")


def test_divergent_execution_blocks(tmp_path: Path):
    root = tmp_path / "out"
    root.mkdir()
    (root / "script-ptbr.json").write_text("{}")
    (root / "brand-assets.json").write_text("[]")
    job = {"render_job_id": 1, "video_id": 1, "brain_decision_id": "b", "execution_id": "other", "authorized_action": "EXECUTION"}
    with pytest.raises(SystemExit, match="BLOCKED_DIVERGENT_EXECUTION"):
        _identity_check(job, root, "b", "e", "EXECUTION", "fp", "voice")
