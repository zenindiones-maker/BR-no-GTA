from __future__ import annotations

import json
import math
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence


@dataclass(frozen=True)
class RenderArtifactValidationResult:
    """
    Resultado da validação de um artifact de renderização.

    O resultado é deliberadamente independente de GitHub,
    MoneyPrinterTurbo, banco de dados e render queue.
    """

    valid: bool
    output_path: str
    duration_seconds: float | None = None
    video_stream_count: int = 0
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.valid


ProbeRunner = Callable[[Sequence[str]], str]


class RenderArtifactValidator:
    """
    Valida um artifact de vídeo produzido por um render remoto.

    Pipeline de validação:

        caminho informado
             ↓
        existe?
             ↓
        é arquivo regular?
             ↓
        não está vazio?
             ↓
        extensão .mp4?
             ↓
        ffprobe
             ↓
        JSON válido?
             ↓
        existe stream de vídeo?
             ↓
        duração numérica?
             ↓
        duração > 0?
             ↓
        MP4 válido

    Responsabilidades exclusivas:
    - validação estrutural do arquivo;
    - inspeção técnica através do ffprobe;
    - retorno de um resultado normalizado.

    Não conhece:
    - GitHub Actions;
    - MoneyPrinterTurbo;
    - render queue;
    - banco de dados;
    - YouTube;
    - scheduler.
    """

    def __init__(
        self,
        probe_runner: ProbeRunner | None = None,
    ) -> None:
        self.probe_runner = (
            probe_runner
            if probe_runner is not None
            else self._default_probe_runner
        )

    @staticmethod
    def _default_probe_runner(
        command: Sequence[str],
    ) -> str:
        """
        Executa o ffprobe sem shell.

        O comando é recebido como sequência de argumentos para
        impedir interpretação pelo shell e manter a execução
        determinística.
        """

        completed = subprocess.run(
            list(command),
            check=False,
            capture_output=True,
            text=True,
        )

        if completed.returncode != 0:
            detail = (
                completed.stderr.strip()
                or "ffprobe terminou com código diferente de zero."
            )

            raise RuntimeError(detail)

        return completed.stdout

    @staticmethod
    def _invalid(
        path: Path,
        error: str,
    ) -> RenderArtifactValidationResult:
        return RenderArtifactValidationResult(
            valid=False,
            output_path=str(path),
            error=error,
        )

    def validate(
        self,
        output_path: str | Path,
    ) -> RenderArtifactValidationResult:
        """
        Valida tecnicamente um artifact de vídeo.

        Erros relacionados ao artifact retornam
        RenderArtifactValidationResult(valid=False).

        Argumentos de chamada inválidos continuam sendo tratados
        como erros de programação através de ValueError.
        """

        if not output_path:
            raise ValueError(
                "O caminho do artifact é obrigatório."
            )

        path = Path(output_path)

        if not path.exists():
            return self._invalid(
                path,
                "O artifact de renderização não existe.",
            )

        if not path.is_file():
            return self._invalid(
                path,
                "O artifact de renderização não é um arquivo.",
            )

        try:
            file_size = path.stat().st_size
        except OSError as exc:
            return self._invalid(
                path,
                f"Não foi possível acessar o artifact: {exc}",
            )

        if file_size <= 0:
            return self._invalid(
                path,
                "O artifact de renderização está vazio.",
            )

        if path.suffix.lower() != ".mp4":
            return self._invalid(
                path,
                "O artifact de renderização não possui extensão .mp4.",
            )

        command: list[str] = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ]

        try:
            raw_output = self.probe_runner(command)
        except (OSError, RuntimeError) as exc:
            return self._invalid(
                path,
                f"Não foi possível validar o MP4 com ffprobe: {exc}",
            )

        if not raw_output:
            return self._invalid(
                path,
                "O ffprobe não retornou dados sobre o MP4.",
            )

        try:
            payload = json.loads(raw_output)
        except json.JSONDecodeError as exc:
            return self._invalid(
                path,
                f"A resposta do ffprobe não é um JSON válido: {exc}",
            )

        streams = payload.get("streams")

        if not isinstance(streams, list):
            return self._invalid(
                path,
                "A resposta do ffprobe não contém uma lista de streams.",
            )

        video_stream_count = sum(
            1
            for stream in streams
            if isinstance(stream, dict)
            and stream.get("codec_type") == "video"
        )

        if video_stream_count <= 0:
            return self._invalid(
                path,
                "O MP4 não contém stream de vídeo.",
            )

        format_data = payload.get("format")

        if not isinstance(format_data, dict):
            return self._invalid(
                path,
                "A resposta do ffprobe não contém informações de formato.",
            )

        raw_duration = format_data.get("duration")

        if raw_duration is None:
            return self._invalid(
                path,
                "O MP4 não possui duração informada pelo ffprobe.",
            )

        try:
            duration_seconds = float(raw_duration)
        except (TypeError, ValueError):
            return self._invalid(
                path,
                "A duração informada pelo ffprobe não é numérica.",
            )

        if not math.isfinite(duration_seconds):
            return self._invalid(
                path,
                "A duração do MP4 não é finita.",
            )

        if duration_seconds <= 0:
            return self._invalid(
                path,
                "A duração do MP4 deve ser maior que zero.",
            )

        return RenderArtifactValidationResult(
            valid=True,
            output_path=str(path),
            duration_seconds=duration_seconds,
            video_stream_count=video_stream_count,
            error=None,
        )
