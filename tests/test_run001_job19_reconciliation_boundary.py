from app.services.render_executor_service import RenderExecutionResult
import app.services.render_orchestration_service as service


class Executor:
    def execute(self, job, *, on_dispatch=None):
        assert job["github_execution"]["run_id"] == 34984341615
        return RenderExecutionResult(success=True, output_path="/tmp/canary.mp4", error=None, github_execution=job["github_execution"])


def _job(run_id=34982292834):
    return {
        "id": 19,
        "status": "running",
        "video_id": 4,
        "execution_id": "7307774b-b6c4-48e7-8b43-b13dce9ec50f",
        "github_execution": {
            "run_id": run_id,
            "repository": "zenindiones-maker/BR-no-GTA",
            "workflow": "render-worker.yml",
        },
    }


def test_reconcile_proven_retry_uses_existing_run_without_dispatch(monkeypatch):
    state = _job()
    monkeypatch.setattr(service, "get_render_job", lambda job_id: dict(state))

    def update(job_id, *, github_execution):
        state["github_execution"] = dict(github_execution)
        return dict(state)

    monkeypatch.setattr(service, "update_render_job_payload", update)
    monkeypatch.setattr(service, "transition_render_job", lambda *args, **kwargs: None)
    monkeypatch.setattr(service, "complete_video_from_render_job", lambda job_id: None)

    result = service.reconcile_cloud_render_execution(
        19,
        Executor(),
        expected_previous_run_id=34982292834,
        proven_github_execution={
            "run_id": 34984341615,
            "repository": "zenindiones-maker/BR-no-GTA",
            "workflow": "render-worker.yml",
        },
        expected_video_id=4,
        expected_execution_id="7307774b-b6c4-48e7-8b43-b13dce9ec50f",
    )
    assert result.success is True
    assert state["github_execution"]["run_id"] == 34984341615


def test_reconcile_rejects_arbitrary_run_when_previous_run_changed(monkeypatch):
    monkeypatch.setattr(service, "get_render_job", lambda job_id: _job(999))
    try:
        service.reconcile_cloud_render_execution(
            19,
            Executor(),
            expected_previous_run_id=34982292834,
            proven_github_execution={
                "run_id": 34984341615,
                "repository": "zenindiones-maker/BR-no-GTA",
                "workflow": "render-worker.yml",
            },
            expected_video_id=4,
            expected_execution_id="7307774b-b6c4-48e7-8b43-b13dce9ec50f",
        )
    except ValueError as exc:
        assert "changed before reconciliation" in str(exc)
    else:
        raise AssertionError("arbitrary persisted run was accepted")


def test_reconcile_rejects_wrong_job_identity(monkeypatch):
    bad = _job()
    bad["video_id"] = 99
    monkeypatch.setattr(service, "get_render_job", lambda job_id: bad)
    try:
        service.reconcile_cloud_render_execution(
            19,
            Executor(),
            expected_previous_run_id=34982292834,
            proven_github_execution={
                "run_id": 34984341615,
                "repository": "zenindiones-maker/BR-no-GTA",
                "workflow": "render-worker.yml",
            },
            expected_video_id=4,
            expected_execution_id="7307774b-b6c4-48e7-8b43-b13dce9ec50f",
        )
    except ValueError as exc:
        assert "video_id" in str(exc)
    else:
        raise AssertionError("wrong Job19 identity was accepted")
