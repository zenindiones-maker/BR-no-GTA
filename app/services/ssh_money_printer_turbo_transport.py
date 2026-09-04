from __future__ import annotations

import shlex
import subprocess
import json
from pathlib import Path

from app.services.money_printer_turbo_artifact import (
    sha256_file,
    validate_non_empty_file,
    validate_sha256,
)
from app.services.money_printer_turbo_transport import (
    MoneyPrinterTurboTransportResult,
    parse_video_file,
)


class SshMoneyPrinterTurboTransport:
    """
    Transporte do MoneyPrinterTurbo através de SSH + rsync.

    Fluxo:

        A15
          ↓
        rsync input
          ↓
        máquina de produção
          ↓
        Remote Runner
          ↓
        output/video.mp4
          ↓
        validação remota
          ↓
        ffprobe
          ↓
        SHA-256 remoto
          ↓
        rsync output
          ↓
        SHA-256 local
          ↓
        resultado validado
    """

    def __init__(
        self,
        *,
        host: str,
        user: str,
        remote_root: str,
        remote_runner: str,
        port: int = 22,
        ssh_key: str | None = None,
        connect_timeout: float = 30,
        command_timeout: float = 3600,
    ) -> None:
        if not host:
            raise ValueError(
                "O host SSH do MPT é obrigatório."
            )

        if not user:
            raise ValueError(
                "O usuário SSH do MPT é obrigatório."
            )

        if not remote_root:
            raise ValueError(
                "O remote_root do MPT é obrigatório."
            )

        if not remote_runner:
            raise ValueError(
                "O remote_runner do MPT é obrigatório."
            )

        if port <= 0:
            raise ValueError(
                "A porta SSH deve ser positiva."
            )

        if connect_timeout <= 0:
            raise ValueError(
                "O timeout de conexão SSH deve ser positivo."
            )

        if command_timeout <= 0:
            raise ValueError(
                "O timeout de comando SSH deve ser positivo."
            )

        self._host = host
        self._user = user
        self._remote_root = remote_root.rstrip("/")
        self._remote_runner = remote_runner
        self._port = port
        self._ssh_key = ssh_key
        self._connect_timeout = connect_timeout
        self._command_timeout = command_timeout

    @property
    def destination(self) -> str:
        return f"{self._user}@{self._host}"

    @property
    def remote_runner(self) -> str:
        return self._remote_runner

    def _ssh_base_command(self) -> list[str]:
        command = [
            "ssh",
            "-p",
            str(self._port),
            "-o",
            f"ConnectTimeout={int(self._connect_timeout)}",
        ]

        if self._ssh_key:
            command.extend(
                [
                    "-i",
                    self._ssh_key,
                ]
            )

        command.append(self.destination)

        return command

    def _rsync_base_command(self) -> list[str]:
        command = [
            "rsync",
            "-a",
            "--partial",
            "--protect-args",
            "-e",
        ]

        ssh_command = (
            "ssh "
            f"-p {self._port} "
            f"-o ConnectTimeout={int(self._connect_timeout)}"
        )

        if self._ssh_key:
            ssh_command += (
                f" -i {shlex.quote(self._ssh_key)}"
            )

        command.append(ssh_command)

        return command

    def _run(
        self,
        command: list[str],
        *,
        timeout: float,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    def _run_remote_command(
        self,
        remote_command: str,
    ) -> subprocess.CompletedProcess[str]:
        command = [
            *self._ssh_base_command(),
            remote_command,
        ]

        return self._run(
            command,
            timeout=self._command_timeout,
        )

    def _remote_job_root(
        self,
        job_id: int | str,
    ) -> str:
        return (
            f"{self._remote_root}/jobs/{job_id}"
        )

    def _remote_input_dir(
        self,
        job_id: int | str,
    ) -> str:
        return (
            f"{self._remote_job_root(job_id)}/input"
        )

    def _remote_output_dir(
        self,
        job_id: int | str,
    ) -> str:
        return (
            f"{self._remote_job_root(job_id)}/output"
        )

    def _remote_video_path(
        self,
        job_id: int | str,
    ) -> str:
        return (
            f"{self._remote_output_dir(job_id)}"
            "/video.mp4"
        )

    def _build_remote_runner_command(
        self,
        *,
        input_dir: str,
        output_dir: str,
        job_id: int | str,
    ) -> str:
        arguments = [
            "python",
            self._remote_runner,
            "--input-dir",
            input_dir,
            "--mpt-root",
            self._remote_root,
            "--output-dir",
            output_dir,
            "--task-id",
            str(job_id),
        ]

        return shlex.join(arguments)

    def _run_remote_runner(
        self,
        *,
        input_dir: str,
        output_dir: str,
        job_id: int | str,
    ) -> subprocess.CompletedProcess[str]:
        remote_command = self._build_remote_runner_command(
            input_dir=input_dir,
            output_dir=output_dir,
            job_id=job_id,
        )

        return self._run_remote_command(
            remote_command
        )

    def _validate_remote_video_path(
        self,
        video_path: Path,
        remote_job_root: str,
    ) -> None:
        if not video_path.is_absolute():
            raise ValueError(
                "O caminho do vídeo remoto deve ser absoluto."
            )

        if video_path.suffix.lower() != ".mp4":
            raise ValueError(
                "O artefato remoto informado não é MP4."
            )

        job_root = Path(remote_job_root)

        try:
            video_path.relative_to(job_root)
        except ValueError as exc:
            raise ValueError(
                "O vídeo remoto está fora do staging do job."
            ) from exc

    def execute(
        self,
        *,
        job_id: int | str,
        local_input_dir: Path,
        local_output_path: Path,
    ) -> MoneyPrinterTurboTransportResult:
        if not str(job_id).strip():
            raise ValueError(
                "O job_id do MPT é obrigatório."
            )

        local_input_dir = Path(local_input_dir)
        local_output_path = Path(local_output_path)

        if not local_input_dir.exists():
            raise FileNotFoundError(
                "Diretório de entrada não encontrado: "
                f"{local_input_dir}"
            )

        if not local_input_dir.is_dir():
            raise ValueError(
                "O diretório de entrada do MPT é inválido."
            )

        local_output_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        remote_job_root = self._remote_job_root(job_id)
        remote_input_dir = self._remote_input_dir(job_id)
        remote_output_dir = self._remote_output_dir(job_id)
        remote_video_path = self._remote_video_path(job_id)

        remote_prepare_command = (
            "mkdir -p "
            + shlex.join(
                [
                    remote_input_dir,
                    remote_output_dir,
                ]
            )
        )

        self._run_remote_command(
            remote_prepare_command
        )

        rsync_upload = [
            *self._rsync_base_command(),
            f"{local_input_dir}/",
            f"{self.destination}:{remote_input_dir}/",
        ]

        self._run(
            rsync_upload,
            timeout=self._command_timeout,
        )

        runner_result = self._run_remote_runner(
            input_dir=remote_input_dir,
            output_dir=remote_output_dir,
            job_id=job_id,
        )

        reported_video_path = parse_video_file(
            runner_result.stdout
        )

        reported_video = Path(
            reported_video_path
        )

        self._validate_remote_video_path(
            reported_video,
            remote_job_root,
        )

        if reported_video_path != remote_video_path:
            raise ValueError(
                "O Remote Runner informou um vídeo "
                "diferente do artefato esperado: "
                f"esperado={remote_video_path}, "
                f"informado={reported_video_path}."
            )

        remote_ffprobe = (
            "ffprobe "
            "-v error "
            "-show_entries "
            "format=format_name,duration "
            "-show_entries "
            "stream=codec_type "
            "-of default=noprint_wrappers=1 "
            + shlex.quote(remote_video_path)
        )

        ffprobe_result = self._run_remote_command(
            remote_ffprobe
        )

        ffprobe_output = (
            ffprobe_result.stdout.strip()
        )

        try:
            ffprobe_data = json.loads(ffprobe_output)
        except json.JSONDecodeError:
            ffprobe_data = None

        if isinstance(ffprobe_data, dict):
            format_data = ffprobe_data.get("format", {})
            streams = ffprobe_data.get("streams", [])

            format_name = str(
                format_data.get("format_name", "")
            ).lower()

            duration = str(
                format_data.get("duration", "")
            ).strip()

            has_video_stream = any(
                isinstance(stream, dict)
                and stream.get("codec_type") == "video"
                for stream in streams
            )

            if "mp4" not in format_name:
                raise ValueError(
                    "O artefato remoto não foi reconhecido "
                    "como MP4 pelo ffprobe."
                )

            if not duration:
                raise ValueError(
                    "O MP4 remoto não possui duração válida."
                )

            if not has_video_stream:
                raise ValueError(
                    "O MP4 remoto não possui stream de vídeo."
                )

        else:
            normalized_ffprobe_output = (
                ffprobe_output.lower()
            )

            if (
                "format_name=mov,mp4" not in
                normalized_ffprobe_output
            ):
                raise ValueError(
                    "O artefato remoto não foi reconhecido "
                    "como MP4 pelo ffprobe."
                )

            if "duration=" not in normalized_ffprobe_output:
                raise ValueError(
                    "O MP4 remoto não possui duração válida."
                )

            if (
                "codec_type=video" not in
                normalized_ffprobe_output
            ):
                raise ValueError(
                    "O MP4 remoto não possui stream de vídeo."
                )

        remote_sha_command = (
            "sha256sum "
            + shlex.quote(remote_video_path)
        )

        sha_result = self._run_remote_command(
            remote_sha_command
        )

        sha_parts = (
            sha_result.stdout.strip().split()
        )

        if not sha_parts:
            raise ValueError(
                "O comando remoto não retornou SHA-256."
            )

        remote_sha256 = sha_parts[0]

        partial_output = local_output_path.with_suffix(
            local_output_path.suffix + ".part"
        )

        partial_output.unlink(
            missing_ok=True
        )

        rsync_download = [
            *self._rsync_base_command(),
            f"{self.destination}:{remote_video_path}",
            str(partial_output),
        ]

        self._run(
            rsync_download,
            timeout=self._command_timeout,
        )

        size_bytes = validate_non_empty_file(
            partial_output
        )

        local_sha256 = sha256_file(
            partial_output
        )

        validate_sha256(
            expected_sha256=remote_sha256,
            actual_sha256=local_sha256,
        )

        partial_output.replace(
            local_output_path
        )

        return MoneyPrinterTurboTransportResult(
            remote_video_path=remote_video_path,
            local_video_path=str(local_output_path),
            remote_sha256=remote_sha256,
            local_sha256=local_sha256,
            size_bytes=size_bytes,
        )
