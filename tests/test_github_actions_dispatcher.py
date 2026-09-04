import pytest

from app.services.github_actions_dispatcher import (
    GitHubActionsDispatcher,
)


class FakeCommandRunner:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def __call__(self, command):
        self.commands.append(list(command))
        return "https://github.com/zenindiones-maker/BR-no-GTA/actions/runs/123456789"


def test_dispatch_requires_repository():
    runner = FakeCommandRunner()
    dispatcher = GitHubActionsDispatcher(runner)

    with pytest.raises(
        ValueError,
        match="repositório GitHub",
    ):
        dispatcher.dispatch(
            repository="",
            workflow="render-worker.yml",
            ref="main",
        )


def test_dispatch_requires_workflow():
    runner = FakeCommandRunner()
    dispatcher = GitHubActionsDispatcher(runner)

    with pytest.raises(
        ValueError,
        match="workflow GitHub",
    ):
        dispatcher.dispatch(
            repository="zenindiones-maker/BR-no-GTA",
            workflow="",
            ref="main",
        )


def test_dispatch_requires_ref():
    runner = FakeCommandRunner()
    dispatcher = GitHubActionsDispatcher(runner)

    with pytest.raises(
        ValueError,
        match="referência Git",
    ):
        dispatcher.dispatch(
            repository="zenindiones-maker/BR-no-GTA",
            workflow="render-worker.yml",
            ref="",
        )


def test_dispatch_builds_expected_gh_command():
    runner = FakeCommandRunner()
    dispatcher = GitHubActionsDispatcher(runner)

    result = dispatcher.dispatch(
        repository="zenindiones-maker/BR-no-GTA",
        workflow="render-worker.yml",
        ref="main",
        inputs={
            "video_subject": "GTA 6 novidades",
            "video_script": "Este é o roteiro.",
            "task_id": "render-001",
        },
    )

    assert result.repository == "zenindiones-maker/BR-no-GTA"
    assert result.workflow == "render-worker.yml"
    assert result.ref == "main"
    assert result.run_id == 123456789

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
            "video_script=Este é o roteiro.",
            "--field",
            "task_id=render-001",
        ]
    ]


def test_dispatch_without_inputs_does_not_add_fields():
    runner = FakeCommandRunner()
    dispatcher = GitHubActionsDispatcher(runner)

    dispatcher.dispatch(
        repository="zenindiones-maker/BR-no-GTA",
        workflow="render-worker.yml",
        ref="main",
    )

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
        ]
    ]


def test_dispatch_rejects_empty_input_name():
    runner = FakeCommandRunner()
    dispatcher = GitHubActionsDispatcher(runner)

    with pytest.raises(
        ValueError,
        match="nome do input GitHub",
    ):
        dispatcher.dispatch(
            repository="zenindiones-maker/BR-no-GTA",
            workflow="render-worker.yml",
            ref="main",
            inputs={
                "": "valor",
            },
        )
