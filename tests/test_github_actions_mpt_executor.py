import pytest

from app.services.github_actions_mpt_executor import (
    GitHubActionsMptExecutor,
)


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
    executor = GitHubActionsMptExecutor(
        repository="zenindiones-maker/BR-no-GTA",
    )

    with pytest.raises(ValueError, match="render job"):
        executor.execute({})


def test_executor_does_not_implement_dispatch_yet():
    executor = GitHubActionsMptExecutor(
        repository="zenindiones-maker/BR-no-GTA",
    )

    with pytest.raises(
        NotImplementedError,
        match="GitHub Actions",
    ):
        executor.execute(
            {
                "content_item_id": 1,
            }
        )
