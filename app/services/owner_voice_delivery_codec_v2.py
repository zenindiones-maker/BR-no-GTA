"""Convert a private, authenticated BR_OWNER_V1 WAV into a Telegram voice note.

No network access. No fallback model. Encode and validate before ledger SENDING.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile


MAX_TELEGRAM_VOICE_BYTES = 49_000_000


def encode_private_opus(source: Path, output_dir: Path, *, private_workspace: Path) -> Path:
    source = Path(source).expanduser().resolve()
    output_dir = Path(output_dir).expanduser().resolve()
    private_root = Path(private_workspace).expanduser().resolve()
    if not source.is_relative_to(private_root):
        raise ValueError("OWNER_AUDIO_OUTSIDE_PRIVATE_WORKSPACE")
    if not source.is_file() or source.suffix.lower() != ".wav" or source.stat().st_size <= 0:
        raise ValueError("OWNER_CLONE_WAV_REQUIRED")
    if output_dir.is_symlink() or output_dir == source.parent:
        raise ValueError("OWNER_AUDIO_PRIVATE_OUTPUT_INVALID")
    output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    output_dir.chmod(0o700)
    with tempfile.NamedTemporaryFile(
        prefix="owner-note-", suffix=".ogg", dir=output_dir, delete=False
    ) as handle:
        temporary = Path(handle.name)
    try:
        commands = [
            "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(source), "-vn", "-ac", "1", "-ar", "48000",
            "-c:a", "libopus", "-b:a", "48k", "-application", "voip", str(temporary),
        ]
        encoding = subprocess.run(
            commands, stdin=subprocess.DEVNULL,
            capture_output=True, timeout=90, check=False,
        )
        if encoding.returncode != 0 or not temporary.is_file():
            raise RuntimeError("OWNER_OPUS_ENCODING_FAILED")
        length = temporary.stat().st_size
        if not 0 < length <= MAX_TELEGRAM_VOICE_BYTES:
            raise RuntimeError("OWNER_OPUS_SIZE_INVALID")
        probing = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a:0",
             "-show_entries", "stream=codec_name,channels,sample_rate",
             "-of", "json", str(temporary)],
            stdin=subprocess.DEVNULL, capture_output=True, timeout=30, check=False,
        )
        if probing.returncode != 0:
            raise RuntimeError("OWNER_OPUS_VALIDATION_FAILED")
        try:
            streams = json.loads(probing.stdout).get("streams", [])
            assert len(streams) == 1
            assert streams[0].get("codec_name") == "opus"
            assert int(streams[0].get("channels") or 0) == 1
            assert int(streams[0].get("sample_rate") or 0) == 48000
        except (ValueError, TypeError, AssertionError, KeyError) as exc:
            raise RuntimeError("OWNER_OPUS_VALIDATION_FAILED") from exc
        output = output_dir / "owner-audition.ogg"
        temporary.chmod(0o600)
        temporary.replace(output)
        output.chmod(0o600)
        return output
    finally:
        temporary.unlink(missing_ok=True)
