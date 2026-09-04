from __future__ import annotations

import re
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
    run_id: int


CommandRunner = Callable[[Sequence[str]], str]


class GitHubActionsDispatcher:
    """
    Responsável exclusivamente por disparar workflows do GitHub Actions.

    Fluxo:

        gh workflow run
              ↓
        URL do workflow run
              ↓
        run_id

    Não conhece:
    - banco de dados;
    - render queue;
    - MoneyPrinterTurbo;
    - YouTube;
    - regras editoriais.
    """

    _RUN_ID_PATTERN = re.compile(
        r"/actions/runs/(\d+)(?:/|$)"
    )

    def __init__(
        self,
        command_runner: CommandRunner,
    ) -> None:
        if command_runner is None:
            raise ValueError(
                "O executor de comandos GitHub é obrigatório."
            )

        self.command_runner = command_runner

    @classmethod
    def _extract_run_id(
        cls,
        output: str,
    ) -> int:
        if not output:
            raise RuntimeError(
                "O GitHub Actions não retornou a URL do workflow run."
            )

        match = cls._RUN_ID_PATTERN.search(output.strip())

        if match is None:
            raise RuntimeError(
                "Não foi possível extrair o run_id do workflow GitHub."
            )

        return int(match.group(1))

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

        e captura o run_id a partir da URL retornada pelo GitHub.
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

        output = self.command_runner(command)

        run_id = self._extract_run_id(output)

        return GitHubActionsDispatchResult(
            repository=repository,
            workflow=workflow,
            ref=ref,
            run_id=run_id,
        )
