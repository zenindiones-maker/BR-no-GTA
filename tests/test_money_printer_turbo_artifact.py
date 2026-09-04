from pathlib import Path
import hashlib

import pytest

from app.services.money_printer_turbo_artifact import (
    sha256_file,
    validate_non_empty_file,
    validate_sha256,
)


def test_sha256_file_returns_expected_digest(tmp_path: Path):
    file_path = tmp_path / "video.mp4"
    payload = b"BR-no-GTA-MP4"
    file_path.write_bytes(payload)

    expected = hashlib.sha256(payload).hexdigest()

    assert sha256_file(file_path) == expected


def test_sha256_file_fails_when_file_does_not_exist(
    tmp_path: Path,
):
    with pytest.raises(FileNotFoundError):
        sha256_file(tmp_path / "missing.mp4")


def test_validate_non_empty_file_returns_size(
    tmp_path: Path,
):
    file_path = tmp_path / "video.mp4"
    file_path.write_bytes(b"abc")

    assert validate_non_empty_file(file_path) == 3


def test_validate_non_empty_file_rejects_empty_file(
    tmp_path: Path,
):
    file_path = tmp_path / "video.mp4"
    file_path.write_bytes(b"")

    with pytest.raises(ValueError):
        validate_non_empty_file(file_path)


def test_validate_sha256_accepts_matching_hash():
    validate_sha256(
        expected_sha256="ABC123",
        actual_sha256="abc123",
    )


def test_validate_sha256_rejects_mismatch():
    with pytest.raises(
        ValueError,
        match="Falha de integridade",
    ):
        validate_sha256(
            expected_sha256="abc123",
            actual_sha256="def456",
        )
