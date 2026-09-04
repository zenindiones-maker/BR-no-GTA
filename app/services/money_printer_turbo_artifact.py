from __future__ import annotations

import hashlib
from pathlib import Path


SHA256_CHUNK_SIZE = 1024 * 1024


def sha256_file(path: Path) -> str:
    """
    Calcula SHA-256 de um arquivo sem carregá-lo inteiro na memória.
    """

    if not path.exists():
        raise FileNotFoundError(
            f"Arquivo não encontrado para SHA-256: {path}"
        )

    if not path.is_file():
        raise ValueError(
            f"O caminho não é um arquivo regular: {path}"
        )

    digest = hashlib.sha256()

    with path.open("rb") as file:
        while True:
            chunk = file.read(SHA256_CHUNK_SIZE)

            if not chunk:
                break

            digest.update(chunk)

    return digest.hexdigest()


def validate_non_empty_file(path: Path) -> int:
    """
    Valida existência, arquivo regular e tamanho > 0.

    Retorna o tamanho em bytes.
    """

    if not path.exists():
        raise FileNotFoundError(
            f"Artefato não encontrado: {path}"
        )

    if not path.is_file():
        raise ValueError(
            f"Artefato não é um arquivo regular: {path}"
        )

    size = path.stat().st_size

    if size <= 0:
        raise ValueError(
            f"Artefato está vazio: {path}"
        )

    return size


def validate_sha256(
    *,
    expected_sha256: str,
    actual_sha256: str,
) -> None:
    """
    Garante que o artefato recebido é exatamente o artefato enviado.
    """

    expected = expected_sha256.strip().lower()
    actual = actual_sha256.strip().lower()

    if not expected:
        raise ValueError(
            "SHA-256 esperado não pode ser vazio."
        )

    if expected != actual:
        raise ValueError(
            "Falha de integridade do MP4: "
            f"SHA-256 remoto={expected}, "
            f"SHA-256 local={actual}."
        )
