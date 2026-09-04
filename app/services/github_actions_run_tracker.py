from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable, Sequence


@dataclass(frozen=True)
class GitHubActionsRunStatus:
    """
    Estado observado de uma execução do GitHub Actions.
    """

    run_id: int
    status: str
    conclusion: str | None = None

    @property
    def completed(self) -> bool:
        return self.status == "completed"

    @property
    def succeeded(self) -> bool:
        return (
            self.status == "completed"
            and self.conclusion == "success"
        )

    @property
    def failed(self) -> bool:
        return (
            self.status == "completed"
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
            self.status == "completed"
            and self.conclusion == "cancelled"
        )


CommandRunner = Callable[[Sequence[str]], str]


class GitHubActionsRunTracker:
    """
    Consulta exclusivamente o estado de um workflow run.

    Não conhece:
    - banco de dados;
    - render queue;
    - MoneyPrinterTurbo;
    - YouTube;
    - regras editoriais.

    Usa o GitHub CLI:

        gh run view <run_id> --repo <repository>
            --json status,conclusion
    """

    def __init__(
        self,
        command_runner: CommandRunner,
    ) -> None:
        if command_runner is None:
            raise ValueError(
                "O executor de comandos GitHub é obrigatório."
            )

        self.command_runner = command_runner

    def get_status(
        self,
        repository: str,
        run_id: int,
    ) -> GitHubActionsRunStatus:
        """
        Consulta o estado atual de um workflow run.
        """

        if not repository:
            raise ValueError(
                "O repositório GitHub é obrigatório."
            )

        if not isinstance(run_id, int) or run_id <= 0:
            raise ValueError(
                "O run_id GitHub deve ser um inteiro positivo."
            )

        command: list[str] = [
            "gh",
            "run",
            "view",
            str(run_id),
            "--repo",
            repository,
            "--json",
            "status,conclusion",
        ]

        output = self.command_runner(command)

        if not output:
            raise RuntimeError(
                "O GitHub Actions não retornou o estado do workflow run."
            )

        try:
            payload = json.loads(output)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "A resposta do GitHub Actions não é um JSON válido."
            ) from exc

        status = payload.get("status")
        conclusion = payload.get("conclusion")

        if not status:
            raise RuntimeError(
                "A resposta do GitHub Actions não contém o status do run."
            )

        return GitHubActionsRunStatus(
            run_id=run_id,
            status=str(status),
            conclusion=(
                str(conclusion)
                if conclusion is not None
                else None
            ),
        )
