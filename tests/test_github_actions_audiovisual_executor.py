from pathlib import Path
from unittest.mock import patch

import pytest
from app.services.github_actions_artifact_service import (
    GitHubActionsArtifactDownloadResult,
)

from app.services.github_actions_dispatcher import (
    GitHubActionsDispatcher,
)
from app.services.github_actions_run_watcher import (
    GitHubActionsRunWatchResult,
)
from app.services.github_actions_audiovisual_executor import (
    GitHubActionsAudiovisualExecutor,
)
from app.services.audiovisual_render_request_service import build_audiovisual_render_request
from app.services.render_artifact_validator import (
    RenderArtifactValidationResult,
)


class FakeCommandRunner:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def __call__(self, command):
        self.commands.append(list(command))
        return "https://github.com/zenindiones-maker/BR-no-GTA/actions/runs/123456789"


def test_executor_requires_repository():
    with pytest.raises(ValueError, match="repositório GitHub"):
        GitHubActionsAudiovisualExecutor(repository="")


def test_executor_requires_workflow():
    with pytest.raises(ValueError, match="workflow GitHub"):
        GitHubActionsAudiovisualExecutor(
            repository="zenindiones-maker/BR-no-GTA",
            workflow="",
        )


def test_executor_requires_ref():
    with pytest.raises(ValueError, match="referência Git"):
        GitHubActionsAudiovisualExecutor(
            repository="zenindiones-maker/BR-no-GTA",
            ref="",
        )


def test_executor_rejects_invalid_render_job():
    runner = FakeCommandRunner()
    dispatcher = GitHubActionsDispatcher(runner)

    executor = GitHubActionsAudiovisualExecutor(
        repository="zenindiones-maker/BR-no-GTA",
        dispatcher=dispatcher,
    )

    with pytest.raises(ValueError, match="render job"):
        executor.execute({})


def test_executor_requires_dispatcher():
    executor = GitHubActionsAudiovisualExecutor(
        repository="zenindiones-maker/BR-no-GTA",
    )

    with pytest.raises(
        RuntimeError,
        match="dispatcher",
    ):
        executor.execute(
            {
                "content_item_id": 1,
                "video_subject": "GTA 6 novidades",
                "video_script": "Roteiro",
                "task_id": "render-001",
            }
        )


def test_executor_dispatches_render_job(tmp_path):
    runner = FakeCommandRunner()
    dispatcher = GitHubActionsDispatcher(runner)

    class FakeWatcher:
        def __init__(self):
            self.calls = []

        def wait_for_completion(self, repository, run_id):
            self.calls.append((repository, run_id))
            return GitHubActionsRunWatchResult(
                run_id=run_id,
                status="completed",
                conclusion="success",
            )

    class FakeArtifactService:
        def __init__(self):
            self.calls = []

        def download(
            self,
            repository,
            run_id,
            artifact_name,
            output_dir,
        ):
            output_dir = Path(output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)

            mp4_path = output_dir / "master_50min.mp4"
            mp4_path.write_bytes(b"fake-mp4")

            self.calls.append(
                (
                    repository,
                    run_id,
                    artifact_name,
                    output_dir,
                )
            )

            return GitHubActionsArtifactDownloadResult(
                repository=repository,
                run_id=run_id,
                artifact_name=artifact_name,
                output_dir=str(output_dir),
            )

    class FakeValidator:
        def __init__(self):
            self.calls = []

        def validate(self, output_path):
            self.calls.append(Path(output_path))

            return RenderArtifactValidationResult(
                valid=True,
                output_path=str(output_path),
                duration_seconds=3000.0,
                video_stream_count=1,
            )

    watcher = FakeWatcher()
    artifact_service = FakeArtifactService()
    validator = FakeValidator()

    executor = GitHubActionsAudiovisualExecutor(
        repository="zenindiones-maker/BR-no-GTA",
        workflow="render-worker.yml",
        ref="main",
        dispatcher=dispatcher,
        watcher=watcher,
        artifact_service=artifact_service,
        artifact_name="render-output",
        artifact_root=tmp_path,
        validator=validator,
    )

    render_job = {
        "id": 123,
        "attempt": 1,
        "content_item_id": 10,
        "script_id": 20,
        "idea_id": 30,
        "objective": "GTA 6 novidades",
        "format": "youtube_long",
        "estimated_duration_seconds": 3000,
        "brain_decision_id": "brain-123",
        "execution_id": "execution-123",
        "authorized_action": "EXECUTION",
        "scenes": [
            {
                "order": 1,
                "duration_seconds": 3000,
                "segment_id": "segment-123",
                "content_unit_id": 456,
                "source_start_seconds": 0.0,
                "source_end_seconds": 3000.0,
            }
        ],
    }

    expected_audiovisual_request = {
        "render_job": "serialized-render-job",
        "brain_decision_id": "brain-123",
        "execution_id": "execution-123",
        "authorized_action": "EXECUTION",
    }

    with patch(
        "app.services.github_actions_audiovisual_executor.build_audiovisual_render_request",
        return_value=expected_audiovisual_request,
    ) as build_request:
        result = executor.execute(render_job)

    build_request.assert_called_once_with(render_job)

    assert result.success is True
    assert result.output_path is not None
    assert result.output_path.endswith("master_50min.mp4")
    assert result.error is None

    assert watcher.calls == [
        ("zenindiones-maker/BR-no-GTA", result.github_execution["run_id"])
    ]

    assert artifact_service.calls[0][0] == "zenindiones-maker/BR-no-GTA"
    assert artifact_service.calls[0][2] == "render-output"

    assert validator.calls == [Path(result.output_path)]

    assert runner.commands == [
        [
            "gh",
            "workflow",
            "run",
            "render-worker.yml",
            "--repo",
            "zenindiones-maker/BR-no-GTA",
            "--ref",
            "main",
            "--field",
            "render_job=serialized-render-job",
            "--field",
            "brain_decision_id=brain-123",
            "--field",
            "execution_id=execution-123",
            "--field",
            "authorized_action=EXECUTION",
        ]
    ]
