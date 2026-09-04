from __future__ import annotations

import subprocess
from collections.abc import Sequence


def run_github_actions_command(
    command: Sequence[str],
) -> str:
    if not command:
        raise ValueError(
            "O comando GitHub Actions não pode ser vazio."
        )

    completed = subprocess.run(
        list(command),
        check=True,
        capture_output=True,
        text=True,
    )

    return completed.stdout
