from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any, Callable

from app.services.harness_capability_service import CapabilityDefinition


MAX_TASK_CHARS = 12_000
MAX_CONTEXT_CHARS = 16_000
MAX_OUTPUT_CHARS = 20_000


class CodexCapabilityExecutionError(RuntimeError):
    """Safe executor failure that can be returned to the Harness."""

    def __init__(self, safe_message: str):
        super().__init__(safe_message)
        self.safe_message = safe_message


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _tracked_files(repository_root: Path) -> list[Path]:
    completed = subprocess.run(
        ["git", "-C", str(repository_root), "ls-files", "-z"],
        check=True,
        capture_output=True,
    )
    return [
        Path(item.decode("utf-8"))
        for item in completed.stdout.split(b"\0")
        if item
    ]


def _copy_repository_snapshot(
    repository_root: Path,
    destination: Path,
) -> None:
    for relative_path in _tracked_files(repository_root):
        source = repository_root / relative_path
        if not source.is_file():
            continue
        target = destination / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def _payload_prompt(
    *,
    skill_name: str,
    payload: dict[str, Any],
) -> str:
    task = payload.get("task")
    if not isinstance(task, str) or not task.strip():
        raise ValueError("Codex/Addy payload requires a non-empty 'task'")
    if len(task) > MAX_TASK_CHARS:
        raise ValueError("Codex/Addy task exceeds the bounded input limit")

    context = payload.get("context")
    context_text = ""
    if context is not None:
        context_text = json.dumps(
            context,
            ensure_ascii=False,
            default=str,
            separators=(",", ":"),
        )
        if len(context_text) > MAX_CONTEXT_CHARS:
            raise ValueError("Codex/Addy context exceeds the bounded input limit")

    prompt = (
        f"Use only @{skill_name} for this Harness-authorized DEVELOPMENT task.\n"
        "Operate only inside the disposable snapshot provided as your working directory.\n"
        "Do not publish, deploy, authenticate to external services, or invoke other skills.\n"
        "Do not attempt to persist changes outside the disposable snapshot.\n"
        "Return a concise result for the DeepSeek Harness; do not take follow-up actions.\n\n"
        f"Task:\n{task.strip()}"
    )
    if context_text:
        prompt += f"\n\nContext JSON:\n{context_text}"
    return prompt


def _final_agent_text(stdout: str) -> str:
    final_text = ""
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        item = event.get("item")
        if not isinstance(item, dict):
            continue
        if item.get("type") != "agent_message":
            continue
        text = item.get("text")
        if isinstance(text, str):
            final_text = text
    return final_text[:MAX_OUTPUT_CHARS]


def execute_codex_addy_capability(
    capability: CapabilityDefinition,
    payload: dict[str, Any],
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    repository_root: Path | None = None,
) -> dict[str, Any]:
    """Execute one explicitly selected Addy skill in a disposable Codex snapshot."""
    if capability.provider != "addy-agent-skills":
        raise CodexCapabilityExecutionError(
            "Codex/Addy executor received an unsupported provider"
        )
    if capability.execution_kind != "codex_native_skill":
        raise CodexCapabilityExecutionError(
            "Codex/Addy executor received an unsupported execution kind"
        )
    if not capability.capability_id.startswith("addy:"):
        raise CodexCapabilityExecutionError(
            "Codex/Addy executor received an invalid capability id"
        )

    skill_name = capability.capability_id.removeprefix("addy:")
    prompt = _payload_prompt(skill_name=skill_name, payload=payload)
    source_root = (repository_root or _repository_root()).resolve()

    with tempfile.TemporaryDirectory(prefix="br-codex-capability-") as temp_dir:
        snapshot = Path(temp_dir) / "workspace"
        snapshot.mkdir()
        try:
            _copy_repository_snapshot(source_root, snapshot)
        except (OSError, subprocess.SubprocessError):
            raise CodexCapabilityExecutionError(
                "Could not create the disposable repository snapshot"
            ) from None

        command = [
            "codex",
            "exec",
            "--ephemeral",
            "--skip-git-repo-check",
            "--color",
            "never",
            "--json",
            "--sandbox",
            "read-only",
            "-C",
            str(snapshot),
            prompt,
        ]

        try:
            completed = runner(
                command,
                cwd=snapshot,
                check=False,
                capture_output=True,
                text=True,
            )
        except (OSError, subprocess.SubprocessError):
            raise CodexCapabilityExecutionError(
                "Codex executor could not be started"
            ) from None

        if completed.returncode != 0:
            raise CodexCapabilityExecutionError(
                "Codex capability execution failed"
            )

        return {
            "output": _final_agent_text(completed.stdout),
            "exit_code": 0,
            "sandbox": "read-only",
            "workspace": "disposable_snapshot",
            "skill": skill_name,
        }
