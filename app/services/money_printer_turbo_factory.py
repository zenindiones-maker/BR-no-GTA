import os
from pathlib import Path

from app import settings
from app.services.github_actions_artifact_service import (
    GitHubActionsArtifactService,
)
from app.services.github_actions_command_runner import (
    run_github_actions_command,
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
from app.services.money_printer_turbo_ssh_executor import (
    MoneyPrinterTurboSshExecutor,
)
from app.services.ssh_money_printer_turbo_transport import (
    SshMoneyPrinterTurboTransport,
)
from app.services.render_artifact_validator import (
    RenderArtifactValidator,
)


def create_money_printer_turbo_executor():
    backend = os.getenv(
        "BR_MPT_EXECUTOR",
        "github_actions",
    ).strip().lower()

    if backend == "github_actions":
        if not settings.GITHUB_ACTIONS_REPOSITORY:
            return None

        dispatcher = GitHubActionsDispatcher(
            command_runner=run_github_actions_command,
        )

        tracker = GitHubActionsRunTracker(
            command_runner=run_github_actions_command,
        )

        watcher = GitHubActionsRunWatcher(
            tracker=tracker,
            poll_interval=settings.GITHUB_ACTIONS_POLL_INTERVAL,
            timeout=settings.GITHUB_ACTIONS_RUN_TIMEOUT,
        )

        artifact_service = GitHubActionsArtifactService(
            command_runner=run_github_actions_command,
        )

        validator = RenderArtifactValidator()

        return GitHubActionsMptExecutor(
            repository=settings.GITHUB_ACTIONS_REPOSITORY,
            workflow=settings.GITHUB_ACTIONS_RENDER_WORKFLOW,
            ref=settings.GITHUB_ACTIONS_RENDER_REF,
            dispatcher=dispatcher,
            watcher=watcher,
            artifact_service=artifact_service,
            artifact_name=settings.GITHUB_ACTIONS_ARTIFACT_NAME,
            artifact_root=Path(
                settings.GITHUB_ACTIONS_ARTIFACT_ROOT,
            ),
            validator=validator,
        )

    if backend == "ssh":
        if not settings.MPT_SSH_HOST:
            return None

        if not settings.MPT_SSH_USER:
            return None

        if not settings.MPT_SSH_KEY:
            return None

        transport = SshMoneyPrinterTurboTransport(
            host=settings.MPT_SSH_HOST,
            user=settings.MPT_SSH_USER,
            port=settings.MPT_SSH_PORT,
            ssh_key=settings.MPT_SSH_KEY,
            remote_root=settings.MPT_REMOTE_ROOT,
            remote_runner=settings.MPT_REMOTE_RUNNER,
            connect_timeout=settings.MPT_SSH_CONNECT_TIMEOUT,
            command_timeout=settings.MPT_SSH_COMMAND_TIMEOUT,
        )

        input_root = Path(settings.MPT_LOCAL_INPUT_ROOT)

        return MoneyPrinterTurboSshExecutor(
            transport=transport,
            input_root=input_root,
        )

    raise ValueError(
        f"Backend MPT não suportado: {backend!r}"
    )
