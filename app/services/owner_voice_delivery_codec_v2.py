"""BR_OWNER_V1 Telegram voice-note format guard.

No Telegram requests or voice samples are used in this module.
"""
from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile


def encode_private_opus(source: Path, output_dir: Path) -> Path:
    source = source.resolve()
    output_dir = output_dir.resolve()
    if not source.is_file() or source.suffix.lower() != ".wav":
        raise ValueError("OWNER_CLONE_WAV_REQUIRED")
    output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile(dir=output_dir, suffix=".ogg", delete=False) as target:
        destination = Path(target.name)
    try:
        command = ["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(source),
                   "-vn", "-ac", "1", "-ar", "48000", "-c:a", "libopus",
                   "-b:a", "48k", "-application", "voip", str(destination)]
        completed = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, timeout=90)
        if completed.returncode or destination.stat().st_size <= 0:
            raise RuntimeError("OWNER_OPUS_ENCODING_FAILED")
        result = output_dir / "owner-audition.ogg"
        destination.chmod(0o600)
        destination.replace(result)
        return result
    finally:
        destination.unlink(missing_ok=True)
