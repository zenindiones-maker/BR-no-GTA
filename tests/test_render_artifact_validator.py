import json
from pathlib import Path

import pytest

from app.services.render_artifact_validator import (
    RenderArtifactValidator,
)


class FakeProbeRunner:
    def __init__(
        self,
        output: str | None = None,
        error: Exception | None = None,
    ) -> None:
        self.output = output
        self.error = error
        self.commands: list[list[str]] = []

    def __call__(self, command) -> str:
        self.commands.append(list(command))

        if self.error is not None:
            raise self.error

        return self.output or ""


def valid_ffprobe_output(
    duration: str = "12.5",
    video_streams: int = 1,
) -> str:
    streams = [
        {"codec_type": "video"}
        for _ in range(video_streams)
    ]

    return json.dumps(
        {
            "streams": streams,
            "format": {
                "duration": duration,
            },
        }
    )


def create_non_empty_file(
    path: Path,
    content: bytes = b"fake-mp4-content",
) -> Path:
    path.write_bytes(content)
    return path


def test_file_does_not_exist(tmp_path):
    runner = FakeProbeRunner(
        output=valid_ffprobe_output()
    )

    validator = RenderArtifactValidator(
        probe_runner=runner,
    )

    path = tmp_path / "video.mp4"

    result = validator.validate(path)

    assert result.valid is False
    assert result.output_path == str(path)
    assert result.duration_seconds is None
    assert result.video_stream_count == 0
    assert result.error == (
        "O artifact de renderização não existe."
    )

    assert runner.commands == []


def test_directory_is_rejected(tmp_path):
    runner = FakeProbeRunner(
        output=valid_ffprobe_output()
    )

    validator = RenderArtifactValidator(
        probe_runner=runner,
    )

    path = tmp_path / "video.mp4"
    path.mkdir()

    result = validator.validate(path)

    assert result.valid is False
    assert result.output_path == str(path)
    assert result.error == (
        "O artifact de renderização não é um arquivo."
    )

    assert runner.commands == []


def test_empty_file_is_rejected(tmp_path):
    runner = FakeProbeRunner(
        output=valid_ffprobe_output()
    )

    validator = RenderArtifactValidator(
        probe_runner=runner,
    )

    path = tmp_path / "video.mp4"
    path.touch()

    result = validator.validate(path)

    assert result.valid is False
    assert result.error == (
        "O artifact de renderização está vazio."
    )

    assert runner.commands == []


@pytest.mark.parametrize(
    "filename",
    [
        "video.mkv",
        "video.mov",
        "video.webm",
        "video.avi",
        "video.txt",
        "video",
    ],
)
def test_invalid_extension_is_rejected(
    tmp_path,
    filename,
):
    runner = FakeProbeRunner(
        output=valid_ffprobe_output()
    )

    validator = RenderArtifactValidator(
        probe_runner=runner,
    )

    path = create_non_empty_file(
        tmp_path / filename
    )

    result = validator.validate(path)

    assert result.valid is False
    assert result.error == (
        "O artifact de renderização não possui extensão .mp4."
    )

    assert runner.commands == []


def test_mp4_extension_is_case_insensitive(tmp_path):
    runner = FakeProbeRunner(
        output=valid_ffprobe_output()
    )

    validator = RenderArtifactValidator(
        probe_runner=runner,
    )

    path = create_non_empty_file(
        tmp_path / "VIDEO.MP4"
    )

    result = validator.validate(path)

    assert result.valid is True
    assert result.output_path == str(path)
    assert result.duration_seconds == pytest.approx(12.5)
    assert result.video_stream_count == 1


def test_invalid_ffprobe_json_is_rejected(tmp_path):
    runner = FakeProbeRunner(
        output="{not-valid-json"
    )

    validator = RenderArtifactValidator(
        probe_runner=runner,
    )

    path = create_non_empty_file(
        tmp_path / "video.mp4"
    )

    result = validator.validate(path)

    assert result.valid is False
    assert result.error is not None
    assert "JSON válido" in result.error

    assert len(runner.commands) == 1


def test_ffprobe_empty_output_is_rejected(tmp_path):
    runner = FakeProbeRunner(
        output=""
    )

    validator = RenderArtifactValidator(
        probe_runner=runner,
    )

    path = create_non_empty_file(
        tmp_path / "video.mp4"
    )

    result = validator.validate(path)

    assert result.valid is False
    assert result.error == (
        "O ffprobe não retornou dados sobre o MP4."
    )


def test_ffprobe_failure_is_rejected(tmp_path):
    runner = FakeProbeRunner(
        error=RuntimeError("codec inválido")
    )

    validator = RenderArtifactValidator(
        probe_runner=runner,
    )

    path = create_non_empty_file(
        tmp_path / "video.mp4"
    )

    result = validator.validate(path)

    assert result.valid is False
    assert result.error is not None
    assert "ffprobe" in result.error
    assert "codec inválido" in result.error


def test_missing_streams_field_is_rejected(tmp_path):
    runner = FakeProbeRunner(
        output=json.dumps(
            {
                "format": {
                    "duration": "10.0",
                }
            }
        )
    )

    validator = RenderArtifactValidator(
        probe_runner=runner,
    )

    path = create_non_empty_file(
        tmp_path / "video.mp4"
    )

    result = validator.validate(path)

    assert result.valid is False
    assert result.error == (
        "A resposta do ffprobe não contém uma lista de streams."
    )


def test_no_video_stream_is_rejected(tmp_path):
    runner = FakeProbeRunner(
        output=json.dumps(
            {
                "streams": [
                    {"codec_type": "audio"},
                ],
                "format": {
                    "duration": "10.0",
                },
            }
        )
    )

    validator = RenderArtifactValidator(
        probe_runner=runner,
    )

    path = create_non_empty_file(
        tmp_path / "video.mp4"
    )

    result = validator.validate(path)

    assert result.valid is False
    assert result.video_stream_count == 0
    assert result.error == (
        "O MP4 não contém stream de vídeo."
    )


def test_multiple_video_streams_are_supported(tmp_path):
    runner = FakeProbeRunner(
        output=valid_ffprobe_output(
            duration="20.25",
            video_streams=2,
        )
    )

    validator = RenderArtifactValidator(
        probe_runner=runner,
    )

    path = create_non_empty_file(
        tmp_path / "video.mp4"
    )

    result = validator.validate(path)

    assert result.valid is True
    assert result.video_stream_count == 2
    assert result.duration_seconds == pytest.approx(20.25)


def test_missing_format_is_rejected(tmp_path):
    runner = FakeProbeRunner(
        output=json.dumps(
            {
                "streams": [
                    {"codec_type": "video"},
                ]
            }
        )
    )

    validator = RenderArtifactValidator(
        probe_runner=runner,
    )

    path = create_non_empty_file(
        tmp_path / "video.mp4"
    )

    result = validator.validate(path)

    assert result.valid is False
    assert result.error == (
        "A resposta do ffprobe não contém informações de formato."
    )


@pytest.mark.parametrize(
    "duration",
    [
        None,
        "",
        "abc",
        "not-a-number",
    ],
)
def test_invalid_duration_is_rejected(
    tmp_path,
    duration,
):
    payload = {
        "streams": [
            {"codec_type": "video"},
        ],
        "format": {
            "duration": duration,
        },
    }

    runner = FakeProbeRunner(
        output=json.dumps(payload)
    )

    validator = RenderArtifactValidator(
        probe_runner=runner,
    )

    path = create_non_empty_file(
        tmp_path / "video.mp4"
    )

    result = validator.validate(path)

    assert result.valid is False
    assert result.error is not None

    if duration is None:
        assert "duração informada" in result.error
    else:
        assert "não é numérica" in result.error


@pytest.mark.parametrize(
    "duration",
    [
        "0",
        "0.0",
        "-1",
        "-10.5",
    ],
)
def test_non_positive_duration_is_rejected(
    tmp_path,
    duration,
):
    runner = FakeProbeRunner(
        output=valid_ffprobe_output(
            duration=duration
        )
    )

    validator = RenderArtifactValidator(
        probe_runner=runner,
    )

    path = create_non_empty_file(
        tmp_path / "video.mp4"
    )

    result = validator.validate(path)

    assert result.valid is False
    assert result.error == (
        "A duração do MP4 deve ser maior que zero."
    )


@pytest.mark.parametrize(
    "duration",
    [
        "nan",
        "inf",
        "-inf",
    ],
)
def test_non_finite_duration_is_rejected(
    tmp_path,
    duration,
):
    runner = FakeProbeRunner(
        output=valid_ffprobe_output(
            duration=duration
        )
    )

    validator = RenderArtifactValidator(
        probe_runner=runner,
    )

    path = create_non_empty_file(
        tmp_path / "video.mp4"
    )

    result = validator.validate(path)

    assert result.valid is False
    assert result.error == (
        "A duração do MP4 não é finita."
    )


def test_valid_mp4_artifact_is_accepted(tmp_path):
    runner = FakeProbeRunner(
        output=valid_ffprobe_output(
            duration="37.42",
            video_streams=1,
        )
    )

    validator = RenderArtifactValidator(
        probe_runner=runner,
    )

    path = create_non_empty_file(
        tmp_path / "video.mp4"
    )

    result = validator.validate(path)

    assert result.valid is True
    assert result.succeeded is True
    assert result.output_path == str(path)
    assert result.duration_seconds == pytest.approx(37.42)
    assert result.video_stream_count == 1
    assert result.error is None


def test_ffprobe_command_is_safe_and_explicit(tmp_path):
    runner = FakeProbeRunner(
        output=valid_ffprobe_output()
    )

    validator = RenderArtifactValidator(
        probe_runner=runner,
    )

    path = create_non_empty_file(
        tmp_path / "video.mp4"
    )

    validator.validate(path)

    assert runner.commands == [
        [
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
    ]


def test_requires_output_path():
    validator = RenderArtifactValidator(
        probe_runner=FakeProbeRunner()
    )

    with pytest.raises(
        ValueError,
        match="caminho do artifact",
    ):
        validator.validate("")


def test_default_probe_runner_is_configured():
    validator = RenderArtifactValidator()

    assert validator.probe_runner is not None
