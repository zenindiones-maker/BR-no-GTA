from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from app.services.github_actions_run_tracker import (
    GitHubActionsRunStatus,
    GitHubActionsRunTracker,
)


@dataclass(frozen=True)
class GitHubActionsRunWatchResult:
    """
    Resultado final do acompanhamento de um workflow run.
    """

    run_id: int
    status: str
    conclusion: str | None
    timed_out: bool = False

    @property
    def succeeded(self) -> bool:
        return (
            not self.timed_out
            and self.status == "completed"
            and self.conclusion == "success"
        )

    @property
    def failed(self) -> bool:
        return (
            not self.timed_out
            and self.status == "completed"
            and self.conclusion
            in {
                "failure",
                "timed_out",
                "action_required",
            }
        )

    @property
    def cancelled(self) -> bool:
        return (
            not self.timed_out
            and self.status == "completed"
            and self.conclusion == "cancelled"
        )


SleepFunction = Callable[[float], None]
MonotonicFunction = Callable[[], float]


class GitHubActionsRunWatcher:
    """
    Acompanha um workflow run até sua conclusão ou até atingir timeout.

    Responsabilidades:
    - consultar o RunTracker;
    - aguardar entre consultas;
    - respeitar timeout;
    - retornar o estado final observado.

    Não conhece:
    - render queue;
    - MoneyPrinterTurbo;
    - banco de dados;
    - artifact;
    - MP4;
    - YouTube.
    """

    def __init__(
        self,
        tracker: GitHubActionsRunTracker,
        poll_interval: float = 5.0,
        timeout: float = 3600.0,
        sleep: SleepFunction = time.sleep,
        monotonic: MonotonicFunction = time.monotonic,
    ) -> None:
        if tracker is None:
            raise ValueError(
                "O RunTracker do GitHub Actions é obrigatório."
            )

        if poll_interval <= 0:
            raise ValueError(
                "O intervalo de polling deve ser maior que zero."
            )

        if timeout <= 0:
            raise ValueError(
                "O timeout deve ser maior que zero."
            )

        if sleep is None:
            raise ValueError(
                "A função de espera é obrigatória."
            )

        if monotonic is None:
            raise ValueError(
                "A função monotonic é obrigatória."
            )

        self.tracker = tracker
        self.poll_interval = poll_interval
        self.timeout = timeout
        self.sleep = sleep
        self.monotonic = monotonic

    def wait_for_completion(
        self,
        repository: str,
        run_id: int,
    ) -> GitHubActionsRunWatchResult:
        """
        Aguarda o workflow até conclusão ou timeout.
        """

        if not repository:
            raise ValueError(
                "O repositório GitHub é obrigatório."
            )

        if not isinstance(run_id, int) or run_id <= 0:
            raise ValueError(
                "O run_id GitHub deve ser um inteiro positivo."
            )

        started_at = self.monotonic()

        while True:
            current: GitHubActionsRunStatus = (
                self.tracker.get_status(
                    repository=repository,
                    run_id=run_id,
                )
            )

            if current.completed:
                return GitHubActionsRunWatchResult(
                    run_id=current.run_id,
                    status=current.status,
                    conclusion=current.conclusion,
                )

            elapsed = self.monotonic() - started_at

            if elapsed >= self.timeout:
                return GitHubActionsRunWatchResult(
                    run_id=current.run_id,
                    status=current.status,
                    conclusion=current.conclusion,
                    timed_out=True,
                )

            remaining = self.timeout - elapsed
            delay = min(self.poll_interval, remaining)

            self.sleep(delay)
