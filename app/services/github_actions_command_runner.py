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
        check=False,
        capture_output=True,
        text=True,
    )

    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        stdout = (completed.stdout or "").strip()
        detail = stderr or stdout or "sem detalhe retornado pelo GitHub CLI"
        if len(detail) > 1200:
            detail = detail[:1200] + "..."
        raise RuntimeError(
            f"GitHub Actions command failed with exit code {completed.returncode}: {detail}"
        )

    return completed.stdout
