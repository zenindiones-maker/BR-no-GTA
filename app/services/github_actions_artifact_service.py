from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Callable, Sequence


@dataclass(frozen=True)
class GitHubActionsArtifactDownloadResult:
    """Resultado do download de um artifact do GitHub Actions."""

    repository: str
    run_id: int
    artifact_name: str
    output_dir: str


@dataclass(frozen=True)
class GitHubActionsArtifactMetadata:
    """Metadados suficientes para provar um artifact remoto sem baixá-lo."""

    repository: str
    run_id: int
    artifact_id: int
    name: str
    size_in_bytes: int
    expired: bool
    url: str | None = None
    archive_download_url: str | None = None

    @property
    def recoverable(self) -> bool:
        return not self.expired and self.size_in_bytes > 0

    @property
    def remote_uri(self) -> str:
        return (
            f"github-actions://{self.repository}/actions/runs/{self.run_id}"
            f"/artifacts/{self.artifact_id}/{self.name}"
        )


CommandRunner = Callable[[Sequence[str]], str]


class GitHubActionsArtifactService:
    """Download or inspect a named GitHub Actions artifact.

    Metadata inspection deliberately avoids downloading the archive. This is
    used by the A15 control plane when a large render remains in GitHub Actions.
    """

    def __init__(self, command_runner: CommandRunner) -> None:
        if command_runner is None:
            raise ValueError("O executor de comandos GitHub é obrigatório.")
        self.command_runner = command_runner

    @staticmethod
    def _validate_identity(repository: str, run_id: int, artifact_name: str) -> None:
        if not repository:
            raise ValueError("O repositório GitHub é obrigatório.")
        if repository.count("/") != 1 or any(not part for part in repository.split("/")):
            raise ValueError("O repositório GitHub deve usar owner/name.")
        if not isinstance(run_id, int) or isinstance(run_id, bool) or run_id <= 0:
            raise ValueError("O run_id GitHub deve ser um inteiro positivo.")
        if not artifact_name:
            raise ValueError("O nome do artifact GitHub é obrigatório.")

    def inspect(
        self,
        repository: str,
        run_id: int,
        artifact_name: str,
    ) -> GitHubActionsArtifactMetadata:
        """Resolve exatamente um artifact remoto pelo nome, sem baixar bytes."""
        self._validate_identity(repository, run_id, artifact_name)
        endpoint = (
            f"repos/{repository}/actions/runs/{run_id}/artifacts?per_page=100"
        )
        output = self.command_runner(["gh", "api", endpoint])
        if not output:
            raise RuntimeError("O GitHub Actions não retornou metadados de artifacts.")
        try:
            payload = json.loads(output)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Metadados de artifacts não são JSON válido.") from exc
        artifacts = payload.get("artifacts") if isinstance(payload, dict) else None
        if not isinstance(artifacts, list):
            raise RuntimeError("Resposta de artifacts não contém uma lista válida.")
        matches = [
            item
            for item in artifacts
            if isinstance(item, dict) and item.get("name") == artifact_name
        ]
        if len(matches) != 1:
            raise RuntimeError(
                f"Esperado exatamente um artifact {artifact_name!r}; encontrados {len(matches)}."
            )
        item = matches[0]
        artifact_id = item.get("id")
        size_in_bytes = item.get("size_in_bytes")
        expired = item.get("expired")
        if not isinstance(artifact_id, int) or isinstance(artifact_id, bool) or artifact_id <= 0:
            raise RuntimeError("Artifact remoto não possui id válido.")
        if not isinstance(size_in_bytes, int) or isinstance(size_in_bytes, bool):
            raise RuntimeError("Artifact remoto não possui size_in_bytes válido.")
        if not isinstance(expired, bool):
            raise RuntimeError("Artifact remoto não possui expired válido.")
        metadata = GitHubActionsArtifactMetadata(
            repository=repository,
            run_id=run_id,
            artifact_id=artifact_id,
            name=artifact_name,
            size_in_bytes=size_in_bytes,
            expired=expired,
            url=item.get("url") if isinstance(item.get("url"), str) else None,
            archive_download_url=(
                item.get("archive_download_url")
                if isinstance(item.get("archive_download_url"), str)
                else None
            ),
        )
        if not metadata.recoverable:
            raise RuntimeError(
                "Artifact remoto não é recuperável: "
                f"expired={metadata.expired} size_in_bytes={metadata.size_in_bytes}"
            )
        return metadata

    def download(
        self,
        repository: str,
        run_id: int,
        artifact_name: str,
        output_dir: str | Path,
    ) -> GitHubActionsArtifactDownloadResult:
        """Localiza e baixa um artifact específico de um workflow run."""
        self._validate_identity(repository, run_id, artifact_name)
        if not output_dir:
            raise ValueError("O diretório de destino do artifact é obrigatório.")
        destination = Path(output_dir)
        destination.mkdir(parents=True, exist_ok=True)
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
