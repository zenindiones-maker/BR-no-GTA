import pytest

from app.services.github_actions_dispatcher import (
    GitHubActionsDispatcher,
)
from app.services.github_actions_mpt_executor import (
    GitHubActionsMptExecutor,
)


class FakeCommandRunner:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def __call__(self, command):
        self.commands.append(list(command))
        return "https://github.com/zenindiones-maker/BR-no-GTA/actions/runs/123456789"


def test_executor_requires_repository():
    with pytest.raises(ValueError, match="repositório GitHub"):
        GitHubActionsMptExecutor(repository="")


def test_executor_requires_workflow():
    with pytest.raises(ValueError, match="workflow GitHub"):
        GitHubActionsMptExecutor(
            repository="zenindiones-maker/BR-no-GTA",
            workflow="",
        )


def test_executor_requires_ref():
    with pytest.raises(ValueError, match="referência Git"):
        GitHubActionsMptExecutor(
            repository="zenindiones-maker/BR-no-GTA",
            ref="",
        )


def test_executor_rejects_invalid_render_job():
    runner = FakeCommandRunner()
    dispatcher = GitHubActionsDispatcher(runner)

    executor = GitHubActionsMptExecutor(
        repository="zenindiones-maker/BR-no-GTA",
        dispatcher=dispatcher,
    )

    with pytest.raises(ValueError, match="render job"):
        executor.execute({})


def test_executor_requires_dispatcher():
    executor = GitHubActionsMptExecutor(
        repository="zenindiones-maker/BR-no-GTA",
    )

    with pytest.raises(
        RuntimeError,
        match="dispatcher",
    ):
        executor.execute(
            {
                "content_item_id": 1,
            }
        )


def test_executor_requires_video_subject():
    runner = FakeCommandRunner()
    dispatcher = GitHubActionsDispatcher(runner)

    executor = GitHubActionsMptExecutor(
        repository="zenindiones-maker/BR-no-GTA",
        dispatcher=dispatcher,
    )

    with pytest.raises(
        ValueError,
        match="assunto do vídeo",
    ):
        executor.execute(
            {
                "video_script": "Roteiro",
                "task_id": "render-001",
            }
        )


def test_executor_requires_video_script():
    runner = FakeCommandRunner()
    dispatcher = GitHubActionsDispatcher(runner)

    executor = GitHubActionsMptExecutor(
        repository="zenindiones-maker/BR-no-GTA",
        dispatcher=dispatcher,
    )

    with pytest.raises(
        ValueError,
        match="roteiro do vídeo",
    ):
        executor.execute(
            {
                "video_subject": "GTA 6 novidades",
                "task_id": "render-001",
            }
        )


def test_executor_requires_task_id():
    runner = FakeCommandRunner()
    dispatcher = GitHubActionsDispatcher(runner)

    executor = GitHubActionsMptExecutor(
        repository="zenindiones-maker/BR-no-GTA",
        dispatcher=dispatcher,
    )

    with pytest.raises(
        ValueError,
        match="task_id",
    ):
        executor.execute(
            {
                "video_subject": "GTA 6 novidades",
                "video_script": "Roteiro",
            }
        )


def test_executor_dispatches_render_job():
    runner = FakeCommandRunner()
    dispatcher = GitHubActionsDispatcher(runner)

    executor = GitHubActionsMptExecutor(
        repository="zenindiones-maker/BR-no-GTA",
        workflow="render-worker.yml",
        ref="main",
        dispatcher=dispatcher,
    )

    result = executor.execute(
        {
            "video_subject": "GTA 6 novidades",
            "video_script": "Este é o roteiro do vídeo.",
            "task_id": "render-001",
        }
    )

    assert result.success is False
    assert result.output_path is None
    assert "GitHub Actions foi acionado" in result.error

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
            "video_subject=GTA 6 novidades",
            "--field",
            "video_script=Este é o roteiro do vídeo.",
            "--field",
            "task_id=render-001",
        ]
    ]
