import os
from pathlib import Path

import app.settings as app_settings
from app.services.github_actions_artifact_service import (
    GitHubActionsArtifactService,
)
from app.services.github_actions_command_runner import (
    run_github_actions_command,
)
from app.services.github_actions_dispatcher import GitHubActionsDispatcher
from app.services.github_actions_audiovisual_executor import GitHubActionsAudiovisualExecutor
from app.services.github_actions_run_tracker import GitHubActionsRunTracker
from app.services.github_actions_run_watcher import GitHubActionsRunWatcher
from app.services.render_artifact_validator import RenderArtifactValidator


def create_audiovisual_executor():
    backend = os.getenv(
        "BR_RENDER_EXECUTOR",
        "github_actions",
    ).strip().lower()

    if backend != "github_actions":
        raise ValueError(
            f"Backend audiovisual não suportado: {backend!r}. "
            "O executor oficial é github_actions."
        )

    if not app_settings.GITHUB_ACTIONS_REPOSITORY:
        return None

    dispatcher = GitHubActionsDispatcher(
        command_runner=run_github_actions_command,
    )

    tracker = GitHubActionsRunTracker(
        command_runner=run_github_actions_command,
    )

    watcher = GitHubActionsRunWatcher(
        tracker=tracker,
        poll_interval=app_settings.GITHUB_ACTIONS_POLL_INTERVAL,
        timeout=app_settings.GITHUB_ACTIONS_RUN_TIMEOUT,
    )

    artifact_service = GitHubActionsArtifactService(
        command_runner=run_github_actions_command,
    )

    validator = RenderArtifactValidator()

    return GitHubActionsAudiovisualExecutor(
        repository=app_settings.GITHUB_ACTIONS_REPOSITORY,
        workflow=app_settings.GITHUB_ACTIONS_RENDER_WORKFLOW,
        ref=app_settings.GITHUB_ACTIONS_RENDER_REF,
        dispatcher=dispatcher,
        watcher=watcher,
        artifact_service=artifact_service,
        artifact_name=app_settings.GITHUB_ACTIONS_ARTIFACT_NAME,
        artifact_root=Path(
            app_settings.GITHUB_ACTIONS_ARTIFACT_ROOT,
        ),
        validator=validator,
        wait_for_completion=False,
    )
