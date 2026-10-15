"""Fail-closed validation for identity-bound edit QA checkpoints."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class CheckpointValidationError(ValueError):
    """Raised when the edit QA checkpoint cannot be tied to this execution."""


def _read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CheckpointValidationError(f"INVALID_{label}_JSON:{path.name}") from exc
    if not isinstance(value, dict):
        raise CheckpointValidationError(f"INVALID_{label}_SHAPE:{path.name}")
    return value


def validate_edit_checkpoint(output_root: Path | str, expected_execution_id: str) -> dict[str, Any]:
    """Require co-located job and edit QA metadata matching the requested execution.

    The caller must pass the exact output directory containing the resumed MP4,
    not a broad tree searched for any file with a matching basename.
    """
    root = Path(output_root)
    if not expected_execution_id or not expected_execution_id.strip():
        raise CheckpointValidationError("MISSING_EXPECTED_EXECUTION_ID")
    job_path = root / "render-job.json"
    qa_path = root / "edit-qa.json"
    if not job_path.is_file():
        raise CheckpointValidationError("MISSING_RENDER_JOB_IDENTITY")
    if not qa_path.is_file():
        raise CheckpointValidationError("MISSING_EDIT_QA")

    job = _read_object(job_path, "RENDER_JOB")
    qa = _read_object(qa_path, "EDIT_QA")
    job_execution_id = job.get("execution_id")
    if job_execution_id != expected_execution_id:
        raise CheckpointValidationError("RENDER_JOB_EXECUTION_ID_MISMATCH")

    render_job_id = job.get("render_job_id") or job.get("id")
    if render_job_id is None:
        raise CheckpointValidationError("MISSING_RENDER_JOB_ID")
    if qa.get("execution_id") is None or qa.get("render_job_id") is None:
        raise CheckpointValidationError("MISSING_CHECKPOINT_IDENTITY")
    if qa.get("execution_id") != expected_execution_id:
        raise CheckpointValidationError("EXECUTION_ID_MISMATCH")
    if str(qa.get("render_job_id")) != str(render_job_id):
        raise CheckpointValidationError("RENDER_JOB_ID_MISMATCH")
    if qa.get("status") != "PASS":
        raise CheckpointValidationError("EDIT_QA_NOT_PASSED")

    return {
        "execution_id": expected_execution_id,
        "render_job_id": render_job_id,
        "checkpoint": str(qa_path),
        "status": "PASS",
    }
