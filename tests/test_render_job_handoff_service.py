from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.render_job_handoff_service import (
    RenderJobHandoffError,
    build_artifact_descriptor,
    resolve_render_job,
)


SOURCE_SHA = "a" * 40


def _job(**updates):
    value = {
        "render_job_id": 920101,
        "video_id": 920101,
        "execution_id": "run001-video-a-investigative-v1",
        "goal_id": "goal-video-a-state-of-knowledge-20260917",
        "brain_decision_id": "decision-a",
        "authorized_action": "EXECUTION",
        "issued_by": "deepseek_harness",
        "youtube_publication": False,
        "product_profile": "professional_ptbr_v1",
    }
    value.update(updates)
    return value


def _artifact(tmp_path: Path, job=None):
    job = _job() if job is None else job
    root = tmp_path / "handoff"
    root.mkdir()
    path = root / "render-job.json"
    path.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
    descriptor = build_artifact_descriptor(
        render_job_path=path,
        job=job,
        artifact_id=12345,
        artifact_name="render-job-handoff-999",
        producer_run_id=999,
        producer_workflow="run001-longform-video-a.yml",
        source_sha=SOURCE_SHA,
    )
    return root, path, descriptor


def _resolve_artifact(root: Path, descriptor: dict):
    return resolve_render_job(
        inline_json="",
        descriptor_json=json.dumps(descriptor),
        artifact_root=root,
        expected_brain_decision_id="decision-a",
        expected_execution_id="run001-video-a-investigative-v1",
        expected_authorized_action="EXECUTION",
        expected_source_sha=SOURCE_SHA,
    )


def test_large_render_job_artifact_handoff_passes(tmp_path: Path):
    job = _job(research_dossier={"payload": "x" * 200_000})
    root, _, descriptor = _artifact(tmp_path, job)
    resolved, mode = _resolve_artifact(root, descriptor)
    assert mode == "artifact"
    assert resolved == job
    assert len(json.dumps(job)) > 64_000


def test_small_inline_render_job_remains_backward_compatible():
    job = _job()
    resolved, mode = resolve_render_job(
        inline_json=json.dumps(job),
        descriptor_json="",
        artifact_root=None,
        expected_brain_decision_id="decision-a",
        expected_execution_id="run001-video-a-investigative-v1",
        expected_authorized_action="EXECUTION",
    )
    assert mode == "inline"
    assert resolved == job


def test_missing_artifact_fails_closed(tmp_path: Path):
    root, _, descriptor = _artifact(tmp_path)
    missing = tmp_path / "gone"
    with pytest.raises(RenderJobHandoffError, match="artifact does not exist"):
        _resolve_artifact(missing, descriptor)


def test_missing_render_job_json_fails_closed(tmp_path: Path):
    root, path, descriptor = _artifact(tmp_path)
    path.unlink()
    with pytest.raises(RenderJobHandoffError, match="missing render-job.json"):
        _resolve_artifact(root, descriptor)


def test_sha_mismatch_fails_closed(tmp_path: Path):
    root, path, descriptor = _artifact(tmp_path)
    path.write_text(json.dumps(_job(title="tampered")), encoding="utf-8")
    with pytest.raises(RenderJobHandoffError, match="SHA-256 mismatch"):
        _resolve_artifact(root, descriptor)


@pytest.mark.parametrize("field,bad", [
    ("render_job_id", 920102),
    ("video_id", 920102),
    ("execution_id", "other-execution"),
])
def test_identity_mismatch_fails_closed(tmp_path: Path, field: str, bad):
    root, _, descriptor = _artifact(tmp_path)
    descriptor[field] = bad
    with pytest.raises(RenderJobHandoffError, match=f"identity mismatch: {field}"):
        _resolve_artifact(root, descriptor)


def test_invalid_descriptor_schema_fails_closed(tmp_path: Path):
    root, _, descriptor = _artifact(tmp_path)
    descriptor["schema"] = "render-job-handoff/v0"
    with pytest.raises(RenderJobHandoffError, match="unsupported"):
        _resolve_artifact(root, descriptor)


def test_wrong_lineage_or_authorization_fails_closed(tmp_path: Path):
    root, _, descriptor = _artifact(tmp_path)
    descriptor["source_sha"] = "b" * 40
    with pytest.raises(RenderJobHandoffError, match="source commit mismatch"):
        _resolve_artifact(root, descriptor)

    root2 = tmp_path / "second"
    root2.mkdir()
    job = _job(authorized_action="RESEARCH")
    path = root2 / "render-job.json"
    path.write_text(json.dumps(job), encoding="utf-8")
    with pytest.raises(RenderJobHandoffError, match="EXECUTION authorization"):
        build_artifact_descriptor(
            render_job_path=path,
            job=job,
            artifact_id=44,
            artifact_name="bad-auth",
            producer_run_id=7,
            producer_workflow="producer.yml",
            source_sha=SOURCE_SHA,
        )


@pytest.mark.parametrize("forbidden_id", [18, 20])
def test_job18_and_job20_are_forbidden_final_transports(forbidden_id: int):
    job = _job(render_job_id=forbidden_id)
    with pytest.raises(RenderJobHandoffError, match="Job18 is frozen"):
        resolve_render_job(
            inline_json=json.dumps(job),
            descriptor_json="",
            artifact_root=None,
            expected_brain_decision_id="decision-a",
            expected_execution_id="run001-video-a-investigative-v1",
            expected_authorized_action="EXECUTION",
        )


def test_youtube_publication_remains_forbidden():
    job = _job(youtube_publication=True)
    with pytest.raises(RenderJobHandoffError, match="YouTube publication is forbidden"):
        resolve_render_job(
            inline_json=json.dumps(job),
            descriptor_json="",
            artifact_root=None,
            expected_brain_decision_id="decision-a",
            expected_execution_id="run001-video-a-investigative-v1",
            expected_authorized_action="EXECUTION",
        )


def test_render_worker_downloads_artifact_into_expected_root():
    workflow = Path(".github/workflows/render-worker.yml").read_text(encoding="utf-8")
    assert "name: Materialize artifact-backed RenderJob" in workflow
    assert "merge-multiple: true" in workflow
    assert "path: runtime/render/handoff" in workflow


def test_render_worker_installs_pytest_before_adapter_validation():
    workflow = Path(".github/workflows/render-worker.yml").read_text(encoding="utf-8")
    assert "python -m pip install -r requirements.txt pytest" in workflow
    assert "python -m pytest -q tests/test_semantic_ptbr_audio_qa.py" in workflow
