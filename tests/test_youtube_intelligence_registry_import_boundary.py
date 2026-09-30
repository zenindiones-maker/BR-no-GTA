from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


def test_global_registry_import_does_not_require_youtube_runtime_dependencies(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    blocker = tmp_path / "dotenv.py"
    blocker.write_text(
        'raise ImportError("dotenv intentionally unavailable for registry import proof")\n',
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join((str(tmp_path), str(repo_root)))

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from app.services.global_capability_registry import "
                "GLOBAL_CAPABILITY_REGISTRY; "
                "record=GLOBAL_CAPABILITY_REGISTRY.get('youtube.market-intelligence'); "
                "assert record is not None; "
                "print(record.capability_id)"
            ),
        ],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "youtube.market-intelligence"
