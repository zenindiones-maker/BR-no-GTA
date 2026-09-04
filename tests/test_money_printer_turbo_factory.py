import pytest

from app import settings
from app.services.github_actions_artifact_service import (
    GitHubActionsArtifactService,
)
from app.services.github_actions_dispatcher import (
    GitHubActionsDispatcher,
)
from app.services.github_actions_mpt_executor import (
    GitHubActionsMptExecutor,
)
from app.services.github_actions_run_tracker import (
    GitHubActionsRunTracker,
)
from app.services.github_actions_run_watcher import (
    GitHubActionsRunWatcher,
)
from app.services.money_printer_turbo_factory import (
    create_money_printer_turbo_executor,
)


def test_factory_returns_none_without_github_repository(monkeypatch):
    monkeypatch.setenv(
        "BR_MPT_EXECUTOR",
        "github_actions",
    )

    monkeypatch.setattr(
        settings,
        "GITHUB_ACTIONS_REPOSITORY",
        "",
    )

    assert create_money_printer_turbo_executor() is None


def test_factory_builds_github_actions_executor(monkeypatch):
    monkeypatch.setenv(
        "BR_MPT_EXECUTOR",
        "github_actions",
    )

    monkeypatch.setattr(
        settings,
        "GITHUB_ACTIONS_REPOSITORY",
        "zenindiones-maker/BR-no-GTA",
    )

    monkeypatch.setattr(
        settings,
        "GITHUB_ACTIONS_RENDER_WORKFLOW",
        "render-worker.yml",
    )

    monkeypatch.setattr(
        settings,
        "GITHUB_ACTIONS_RENDER_REF",
        "main",
    )

    monkeypatch.setattr(
        settings,
        "GITHUB_ACTIONS_ARTIFACT_NAME",
        "render-output",
    )

    executor = create_money_printer_turbo_executor()

    assert isinstance(
        executor,
        GitHubActionsMptExecutor,
    )

    assert executor.repository == (
        "zenindiones-maker/BR-no-GTA"
    )

    assert executor.workflow == "render-worker.yml"
    assert executor.ref == "main"
    assert executor.artifact_name == "render-output"

    assert isinstance(
        executor.dispatcher,
        GitHubActionsDispatcher,
    )

    assert isinstance(
        executor.watcher,
        GitHubActionsRunWatcher,
    )

    assert isinstance(
        executor.watcher.tracker,
        GitHubActionsRunTracker,
    )

    assert isinstance(
        executor.artifact_service,
        GitHubActionsArtifactService,
    )


def test_factory_rejects_unknown_backend(monkeypatch):
    monkeypatch.setenv(
        "BR_MPT_EXECUTOR",
        "backend-inexistente",
    )

    with pytest.raises(
        ValueError,
        match="Backend MPT não suportado",
    ):
        create_money_printer_turbo_executor()


def test_factory_keeps_ssh_backend(monkeypatch):
    monkeypatch.setenv(
        "BR_MPT_EXECUTOR",
        "ssh",
    )

    monkeypatch.setattr(
        settings,
        "MPT_SSH_HOST",
        "",
    )

    assert create_money_printer_turbo_executor() is None
