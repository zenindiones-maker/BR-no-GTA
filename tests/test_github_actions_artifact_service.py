from pathlib import Path

import pytest

from app.services.github_actions_artifact_service import (
    GitHubActionsArtifactService,
)


class FakeCommandRunner:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def __call__(self, command) -> str:
        self.commands.append(list(command))
        return ""


def test_download_executes_expected_gh_command(tmp_path):
    runner = FakeCommandRunner()

    service = GitHubActionsArtifactService(
        command_runner=runner,
    )

    result = service.download(
        repository="zenindiones-maker/BR-no-GTA",
        run_id=123456789,
        artifact_name="render-output",
        output_dir=tmp_path / "artifacts",
    )

    assert result.repository == "zenindiones-maker/BR-no-GTA"
    assert result.run_id == 123456789
    assert result.artifact_name == "render-output"
    assert result.output_dir == str(tmp_path / "artifacts")

    assert runner.commands == [
        [
            "gh",
            "run",
            "download",
            "123456789",
            "--repo",
            "zenindiones-maker/BR-no-GTA",
            "--name",
            "render-output",
            "--dir",
            str(tmp_path / "artifacts"),
        ]
    ]


def test_download_creates_destination_directory(tmp_path):
    runner = FakeCommandRunner()

    destination = tmp_path / "nested" / "artifacts"

    service = GitHubActionsArtifactService(
        command_runner=runner,
    )

    service.download(
        repository="owner/repository",
        run_id=1,
        artifact_name="render-output",
        output_dir=destination,
    )

    assert destination.is_dir()


def test_download_accepts_string_destination(tmp_path):
    runner = FakeCommandRunner()

    destination = tmp_path / "artifacts"

    service = GitHubActionsArtifactService(
        command_runner=runner,
    )

    result = service.download(
        repository="owner/repository",
        run_id=10,
        artifact_name="video",
        output_dir=str(destination),
    )

    assert result.output_dir == str(destination)
    assert destination.is_dir()


def test_requires_command_runner():
    with pytest.raises(ValueError, match="executor de comandos GitHub"):
        GitHubActionsArtifactService(
            command_runner=None,
        )


@pytest.mark.parametrize(
    "repository,run_id,artifact_name,output_dir,message",
    [
        (
            "",
            1,
            "artifact",
            "artifacts",
            "repositório GitHub",
        ),
        (
            "owner/repository",
            0,
            "artifact",
            "artifacts",
            "run_id GitHub",
        ),
        (
            "owner/repository",
            -1,
            "artifact",
            "artifacts",
            "run_id GitHub",
        ),
        (
            "owner/repository",
            1,
            "",
            "artifacts",
            "nome do artifact GitHub",
        ),
        (
            "owner/repository",
            1,
            "artifact",
            "",
            "diretório de destino",
        ),
    ],
)
def test_validates_required_arguments(
    repository,
    run_id,
    artifact_name,
    output_dir,
    message,
):
    runner = FakeCommandRunner()

    service = GitHubActionsArtifactService(
        command_runner=runner,
    )

    with pytest.raises(ValueError, match=message):
        service.download(
            repository=repository,
            run_id=run_id,
            artifact_name=artifact_name,
            output_dir=output_dir,
        )

    assert runner.commands == []


def test_command_runner_output_is_not_required(tmp_path):
    """
    O serviço depende do comando para efetuar o download.

    O conteúdo baixado será validado por uma camada posterior,
    portanto esta camada não interpreta stdout.
    """

    runner = FakeCommandRunner()

    service = GitHubActionsArtifactService(
        command_runner=runner,
    )

    result = service.download(
        repository="owner/repository",
        run_id=999,
        artifact_name="render-output",
        output_dir=tmp_path,
    )

    assert result.run_id == 999
    assert len(runner.commands) == 1
