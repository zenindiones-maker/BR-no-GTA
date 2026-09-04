from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence


@dataclass(frozen=True)
class GitHubActionsDispatchResult:
    """
    Resultado do despacho de um workflow GitHub Actions.
    """

    repository: str
    workflow: str
    ref: str
    run_id: int | None = None


CommandRunner = Callable[[Sequence[str]], str]


class GitHubActionsDispatcher:
    """
    Responsável exclusivamente por disparar workflows do GitHub Actions.

    Não conhece:
    - banco de dados;
    - render queue;
    - MoneyPrinterTurbo;
    - YouTube;
    - regras editoriais.

    Ele apenas transforma uma solicitação em uma chamada
    ao GitHub CLI (gh).
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

    def dispatch(
        self,
        repository: str,
        workflow: str,
        ref: str,
        inputs: dict[str, str] | None = None,
    ) -> GitHubActionsDispatchResult:
        """
        Dispara um workflow através de:

            gh workflow run

        Os inputs são enviados como --field.
        """

        if not repository:
            raise ValueError(
                "O repositório GitHub é obrigatório."
            )

        if not workflow:
            raise ValueError(
                "O workflow GitHub é obrigatório."
            )

        if not ref:
            raise ValueError(
                "A referência Git é obrigatória."
            )

        command: list[str] = [
            "gh",
            "workflow",
            "run",
            workflow,
            "--repo",
            repository,
            "--ref",
            ref,
        ]

        for name, value in (inputs or {}).items():
            if not name:
                raise ValueError(
                    "O nome do input GitHub é obrigatório."
                )

            if value is None:
                raise ValueError(
                    f"O valor do input GitHub '{name}' é obrigatório."
                )

            command.extend(
                [
                    "--field",
                    f"{name}={value}",
                ]
            )

        self.command_runner(command)

        return GitHubActionsDispatchResult(
            repository=repository,
            workflow=workflow,
            ref=ref,
        )
