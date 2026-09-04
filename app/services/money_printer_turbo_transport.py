from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


def parse_video_file(stdout: str) -> str:
    """
    Extrai o caminho do vídeo produzido a partir do stdout remoto.

    O contrato esperado é uma linha no formato:

        VIDEO_FILE=/caminho/absoluto/video.mp4

    Falha explicitamente quando o runner não informa o artefato.
    """

    for line in stdout.splitlines():
        line = line.strip()

        if line.startswith("VIDEO_FILE="):
            video_file = line.removeprefix("VIDEO_FILE=").strip()

            if video_file:
                return video_file

    raise ValueError(
        "O processo remoto terminou sem informar VIDEO_FILE."
    )


@dataclass(frozen=True)
class MoneyPrinterTurboTransportResult:
    """
    Resultado da execução remota do MoneyPrinterTurbo.

    O transporte não interpreta o conteúdo do vídeo.
    Ele apenas informa onde o artefato remoto foi produzido
    e onde ele foi recuperado localmente.
    """

    remote_video_path: str
    local_video_path: str
    remote_sha256: str
    local_sha256: str
    size_bytes: int


class MoneyPrinterTurboTransport(Protocol):
    """
    Contrato de transporte entre o BR e o ambiente de produção
    onde o MoneyPrinterTurbo está instalado.

    A implementação concreta será responsável por:
    - preparar o job remoto;
    - enviar os arquivos necessários;
    - executar o CLI do MoneyPrinterTurbo;
    - recuperar o MP4;
    - retornar os caminhos remoto e local.

    O executor não deve conhecer SSH, SCP ou subprocess.
    """

    def execute(
        self,
        *,
        job_id: int | str,
        local_input_dir: Path,
        local_output_path: Path,
    ) -> MoneyPrinterTurboTransportResult:
        """
        Executa um job do MoneyPrinterTurbo e recupera o vídeo.

        Args:
            job_id:
                Identificador único do render job.

            local_input_dir:
                Diretório local contendo os arquivos de entrada
                preparados pelo executor.

            local_output_path:
                Caminho local onde o MP4 final deve ser recuperado.

        Returns:
            Resultado contendo os caminhos remoto e local do vídeo.
        """
        ...
