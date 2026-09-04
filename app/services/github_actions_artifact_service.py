from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence


@dataclass(frozen=True)
class GitHubActionsArtifactDownloadResult:
    """
    Resultado do download de um artifact do GitHub Actions.
    """

    repository: str
    run_id: int
    artifact_name: str
    output_dir: str


CommandRunner = Callable[[Sequence[str]], str]


class GitHubActionsArtifactService:
    """
    Localiza e baixa artifacts produzidos por um GitHub Actions run.

    Responsabilidades:
    - validar os parâmetros do artifact;
    - localizar/selecionar o artifact pelo nome;
    - solicitar o download através do GitHub CLI;
    - garantir que o diretório local de destino exista.

    Não conhece:
    - render queue;
    - MoneyPrinterTurbo;
    - MP4;
    - banco de dados;
    - YouTube;
    - scheduler.
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

    def download(
        self,
        repository: str,
        run_id: int,
        artifact_name: str,
        output_dir: str | Path,
    ) -> GitHubActionsArtifactDownloadResult:
        """
        Localiza e baixa um artifact específico de um workflow run.
        """

        if not repository:
            raise ValueError(
                "O repositório GitHub é obrigatório."
            )

        if not isinstance(run_id, int) or run_id <= 0:
            raise ValueError(
                "O run_id GitHub deve ser um inteiro positivo."
            )

        if not artifact_name:
            raise ValueError(
                "O nome do artifact GitHub é obrigatório."
            )

        if not output_dir:
            raise ValueError(
                "O diretório de destino do artifact é obrigatório."
            )

        destination = Path(output_dir)
        destination.mkdir(
            parents=True,
            exist_ok=True,
        )

        command: list[str] = [
            "gh",
            "run",
            "download",
            str(run_id),
            "--repo",
            repository,
            "--name",
            artifact_name,
            "--dir",
            str(destination),
        ]

        self.command_runner(command)

        return GitHubActionsArtifactDownloadResult(
            repository=repository,
            run_id=run_id,
            artifact_name=artifact_name,
            output_dir=str(destination),
        )
