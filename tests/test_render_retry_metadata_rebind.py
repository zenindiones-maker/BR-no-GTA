from __future__ import annotations

import pytest

from app.services import render_orchestration_service as service
from app.services.render_executor_service import AbstractRenderExecutor, RenderExecutionResult


OLD_RUN_ID = 35125183151
NEW_RUN_ID = 35128202416
REPOSITORY = "zenindiones-maker/BR-no-GTA"
WORKFLOW = "render-worker.yml"
REF = "work/gate6f-analytics-learning"
EXECUTION_ID = "acc83783-a9d2-4d38-8e17-b081c2a3eb97"


def _job() -> dict:
    return {
        "id": 20,
        "video_id": 5,
        "status": "running",
        "execution_id": EXECUTION_ID,
        "github_execution": {
            "run_id": OLD_RUN_ID,
            "repository": REPOSITORY,
            "workflow": WORKFLOW,
            "ref": REF,
            "artifact_name": "render-output",
        },
    }


def _replacement() -> dict:
    return {
        "run_id": NEW_RUN_ID,
        "repository": REPOSITORY,
        "workflow": WORKFLOW,
        "ref": REF,
        "artifact_name": "render-output",
    }


def _context() -> dict:
    return {
        "authorization_id": "auth-retry-20",
        "execution_id": EXECUTION_ID,
        "authorized_action": "EXECUTION",
        "authorization_subject": "action:EXECUTION",
    }


class MetadataOnlyExecutor(AbstractRenderExecutor):
    def __init__(self, result: RenderExecutionResult) -> None:
        self.result = result
        self.execute_calls = 0
        self.reconcile_calls = 0

    def execute(self, render_job, **kwargs):
        self.execute_calls += 1
        raise AssertionError("metadata-only rebind must never call execute()")

    def reconcile_metadata_only(self, render_job):
        self.reconcile_calls += 1
        assert render_job["id"] == 20
        assert render_job["github_execution"]["run_id"] == NEW_RUN_ID
        return self.result


def _install_state(monkeypatch, state: dict):
    consumed = []
    completed = []

    monkeypatch.setattr(service, "get_render_job", lambda job_id: state if job_id == 20 else None)

    def update(job_id, *, github_execution):
        assert job_id == 20
        state["github_execution"] = dict(github_execution)
        return state

    def transition(job_id, target_status, **kwargs):
        assert job_id == 20
        state["status"] = target_status
        if "output_path" in kwargs:
            state["output_path"] = kwargs["output_path"]
        if "error" in kwargs:
            state["error"] = kwargs["error"]
        return state

    def validate(value, *, expected_action, expected_subject, expected_execution_id=None, **kwargs):
        assert value is not None
        assert expected_action == "EXECUTION"
        assert expected_subject == "action:EXECUTION"
        assert expected_execution_id == EXECUTION_ID
        return "validated-auth"

    monkeypatch.setattr(service, "update_render_job_payload", update)
    monkeypatch.setattr(service, "transition_render_job", transition)
    monkeypatch.setattr(service, "validate_harness_authorization", validate)
    monkeypatch.setattr(service, "consume_harness_authorization", consumed.append)
    monkeypatch.setattr(service, "complete_video_from_render_job", completed.append)
    return consumed, completed


def test_retry_rebind_pending_is_metadata_only_and_preserves_job_identity(monkeypatch):
    state = _job()
    consumed, completed = _install_state(monkeypatch, state)
    replacement = _replacement()
    executor = MetadataOnlyExecutor(
        RenderExecutionResult(
            success=False,
            pending=True,
            github_execution=replacement,
        )
    )

    result = service.rebind_running_cloud_render_job_metadata(
        20,
        executor,
        expected_previous_run_id=OLD_RUN_ID,
        proven_github_execution=replacement,
        expected_video_id=5,
        expected_execution_id=EXECUTION_ID,
        execution_context=_context(),
    )

    assert result.pending is True
    assert state["id"] == 20
    assert state["status"] == "running"
    assert state["github_execution"]["run_id"] == NEW_RUN_ID
    assert executor.execute_calls == 0
    assert executor.reconcile_calls == 1
    assert consumed == ["validated-auth"]
    assert completed == []


def test_retry_rebind_success_completes_from_remote_locator_without_download(monkeypatch):
    state = _job()
    consumed, completed = _install_state(monkeypatch, state)
    enriched = {
        **_replacement(),
        "artifact_id": 999,
        "artifact_remote_uri": "github-actions://render-output/999",
        "artifact_locator": {
            "media_uri": "github-actions://zenindiones-maker/BR-no-GTA/35128202416/render-output",
        },
    }
    executor = MetadataOnlyExecutor(
        RenderExecutionResult(
            success=True,
            output_path=enriched["artifact_locator"]["media_uri"],
            github_execution=enriched,
        )
    )

    result = service.rebind_running_cloud_render_job_metadata(
        20,
        executor,
        expected_previous_run_id=OLD_RUN_ID,
        proven_github_execution=_replacement(),
        expected_video_id=5,
        expected_execution_id=EXECUTION_ID,
        execution_context=_context(),
    )

    assert result.success is True
    assert state["id"] == 20
    assert state["status"] == "completed"
    assert state["github_execution"]["run_id"] == NEW_RUN_ID
    assert state["output_path"] == enriched["artifact_locator"]["media_uri"]
    assert executor.execute_calls == 0
    assert executor.reconcile_calls == 1
    assert consumed == ["validated-auth"]
    assert completed == [20]


@pytest.mark.parametrize(
    ("replacement_patch", "match"),
    [
        ({"run_id": OLD_RUN_ID}, "distinct positive GitHub run"),
        ({"repository": "other/repo"}, "repository"),
        ({"workflow": "other.yml"}, "workflow"),
        ({"ref": "main"}, "ref"),
        ({"artifact_name": "other-output"}, "artifact_name"),
    ],
)
def test_retry_rebind_rejects_unproven_identity_before_mutation(
    monkeypatch,
    replacement_patch,
    match,
):
    state = _job()
    _install_state(monkeypatch, state)
    original = dict(state["github_execution"])
    replacement = _replacement()
    replacement.update(replacement_patch)
    executor = MetadataOnlyExecutor(
        RenderExecutionResult(success=False, pending=True, github_execution=replacement)
    )

    with pytest.raises(ValueError, match=match):
        service.rebind_running_cloud_render_job_metadata(
            20,
            executor,
            expected_previous_run_id=OLD_RUN_ID,
            proven_github_execution=replacement,
            expected_video_id=5,
            expected_execution_id=EXECUTION_ID,
            execution_context=_context(),
        )

    assert state["github_execution"] == original
    assert state["status"] == "running"
    assert executor.execute_calls == 0
    assert executor.reconcile_calls == 0


def test_retry_rebind_rejects_wrong_job_execution_before_mutation(monkeypatch):
    state = _job()
    state["execution_id"] = "different-execution"
    _install_state(monkeypatch, state)
    original = dict(state["github_execution"])
    executor = MetadataOnlyExecutor(
        RenderExecutionResult(success=False, pending=True, github_execution=_replacement())
    )

    with pytest.raises(ValueError, match="execution_id"):
        service.rebind_running_cloud_render_job_metadata(
            20,
            executor,
            expected_previous_run_id=OLD_RUN_ID,
            proven_github_execution=_replacement(),
            expected_video_id=5,
            expected_execution_id=EXECUTION_ID,
            execution_context=_context(),
        )

    assert state["github_execution"] == original
    assert executor.execute_calls == 0
