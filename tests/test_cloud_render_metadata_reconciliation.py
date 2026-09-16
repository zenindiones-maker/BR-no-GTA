from types import SimpleNamespace

import pytest

from app.services.github_actions_artifact_service import GitHubActionsArtifactMetadata
from app.services.github_actions_audiovisual_executor import GitHubActionsAudiovisualExecutor
from app.services.harness_authorization_service import (
    authorization_to_context,
    issue_harness_authorization,
)
from app.services.render_executor_service import RenderExecutionResult
from app.services import render_orchestration_service as orchestration


REPOSITORY = "zenindiones-maker/BR-no-GTA"
WORKFLOW = "render-worker.yml"


def _job(**changes):
    value = {
        "id": 901,
        "status": "running",
        "video_id": 77,
        "execution_id": "render-exec-77",
        "github_execution": {
            "run_id": 123456789,
            "repository": REPOSITORY,
            "workflow": WORKFLOW,
            "ref": "work/gate6f-analytics-learning",
            "artifact_name": "render-output",
        },
    }
    value.update(changes)
    return value


class _Tracker:
    def __init__(self, status):
        self.status = status
        self.calls = []

    def get_status(self, *, repository, run_id):
        self.calls.append((repository, run_id))
        return self.status


class _Watcher:
    def __init__(self, status):
        self.tracker = _Tracker(status)


class _Artifacts:
    def __init__(self, artifact=None, error=None):
        self.artifact = artifact
        self.error = error
        self.calls = []

    def inspect(self, *, repository, run_id, artifact_name):
        self.calls.append((repository, run_id, artifact_name))
        if self.error:
            raise self.error
        return self.artifact


def _status(*, completed, conclusion=None):
    return SimpleNamespace(
        completed=completed,
        cancelled=completed and conclusion == "cancelled",
        failed=completed and conclusion == "failure",
        succeeded=completed and conclusion == "success",
        status="completed" if completed else "in_progress",
        conclusion=conclusion,
    )


def _executor(status, artifacts):
    return GitHubActionsAudiovisualExecutor(
        repository=REPOSITORY,
        workflow=WORKFLOW,
        ref="work/gate6f-analytics-learning",
        watcher=_Watcher(status),
        artifact_service=artifacts,
        artifact_name="render-output",
    )


def test_metadata_reconciliation_returns_pending_without_download_or_artifact_lookup():
    artifacts = _Artifacts()
    executor = _executor(_status(completed=False), artifacts)

    result = executor.reconcile_metadata_only(_job())

    assert result.pending is True
    assert result.success is False
    assert result.error is None
    assert result.github_execution["run_id"] == 123456789
    assert artifacts.calls == []


def test_metadata_reconciliation_fails_closed_on_failed_run():
    artifacts = _Artifacts()
    executor = _executor(_status(completed=True, conclusion="failure"), artifacts)

    result = executor.reconcile_metadata_only(_job())

    assert result.success is False
    assert result.pending is False
    assert "terminou com falha" in result.error
    assert artifacts.calls == []


def test_metadata_reconciliation_fails_closed_when_artifact_is_missing():
    artifacts = _Artifacts(error=RuntimeError("artifact not found"))
    executor = _executor(_status(completed=True, conclusion="success"), artifacts)

    result = executor.reconcile_metadata_only(_job())

    assert result.success is False
    assert result.output_path is None
    assert "artifact not found" in result.error


def test_metadata_reconciliation_enriches_durable_remote_locator_without_download():
    artifact = GitHubActionsArtifactMetadata(
        repository=REPOSITORY,
        run_id=123456789,
        artifact_id=55,
        name="render-output",
        size_in_bytes=987654,
        expired=False,
    )
    artifacts = _Artifacts(artifact=artifact)
    executor = _executor(_status(completed=True, conclusion="success"), artifacts)

    result = executor.reconcile_metadata_only(_job())

    assert result.success is True
    assert result.pending is False
    assert result.github_execution["artifact_id"] == 55
    assert result.github_execution["artifact_size_in_bytes"] == 987654
    assert result.github_execution["artifact_remote_uri"] == artifact.remote_uri
    assert result.github_execution["artifact_expired"] is False
    locator = result.github_execution["artifact_locator"]
    assert locator["workflow_run_id"] == 123456789
    assert locator["artifact_id"] == 55
    assert locator["render_job_id"] == 901
    assert locator["video_id"] == 77
    assert locator["execution_id"] == "render-exec-77"
    assert locator["media_relative_path"] == "render-exec-77/901/77.mp4"
    assert locator["manifest_relative_path"] == "render-exec-77/901/render-manifest.json"
    assert locator["probe_relative_path"] == "render-exec-77/901/video-probe.json"
    assert locator["qa_relative_path"] == "render-exec-77/901/render-qa.json"
    assert result.output_path == locator["media_uri"]
    assert result.output_path.startswith(artifact.remote_uri + "/")


@pytest.mark.parametrize(
    "github_execution",
    [
        {"run_id": 123, "repository": "other/repo", "workflow": WORKFLOW},
        {"run_id": 123, "repository": REPOSITORY, "workflow": "other.yml"},
        {"run_id": 0, "repository": REPOSITORY, "workflow": WORKFLOW},
        {"run_id": 123, "repository": REPOSITORY, "workflow": WORKFLOW, "artifact_name": "wrong"},
    ],
)
def test_metadata_reconciliation_rejects_persisted_identity_mismatch(github_execution):
    artifacts = _Artifacts()
    executor = _executor(_status(completed=False), artifacts)

    with pytest.raises(ValueError):
        executor.reconcile_metadata_only(_job(github_execution=github_execution))

    assert artifacts.calls == []


def test_orchestration_requires_fresh_harness_authorization_and_consumes_pending_observation(monkeypatch):
    job = _job()
    monkeypatch.setattr(orchestration, "get_render_job", lambda job_id: job)

    class Reconciler:
        def __init__(self):
            self.calls = 0

        def reconcile_metadata_only(self, received):
            self.calls += 1
            assert received is job
            return RenderExecutionResult(
                success=False,
                pending=True,
                github_execution=dict(job["github_execution"]),
            )

    executor = Reconciler()
    authorization = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject="action:EXECUTION",
        execution_id="reconcile-901",
        lineage={"render_job_id": 901},
    )
    context = authorization_to_context(authorization)

    result = orchestration.reconcile_running_cloud_render_job_metadata(
        901,
        executor,
        execution_context=context,
    )
    assert result.pending is True
    assert executor.calls == 1

    with pytest.raises(PermissionError, match="status"):
        orchestration.reconcile_running_cloud_render_job_metadata(
            901,
            executor,
            execution_context=context,
        )
    assert executor.calls == 1


def test_orchestration_rejects_wrong_action_before_reconciliation(monkeypatch):
    job = _job()
    monkeypatch.setattr(orchestration, "get_render_job", lambda job_id: job)

    class Reconciler:
        def reconcile_metadata_only(self, received):
            pytest.fail("reconciler must not execute after authorization rejection")

    wrong = issue_harness_authorization(
        authorized_action="YOUTUBE",
        subject="action:YOUTUBE",
        execution_id="reconcile-901",
    )
    with pytest.raises(PermissionError, match="action mismatch"):
        orchestration.reconcile_running_cloud_render_job_metadata(
            901,
            Reconciler(),
            execution_context=authorization_to_context(wrong),
        )
