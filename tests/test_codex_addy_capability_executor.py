from __future__ import annotations

import json
from pathlib import Path
import subprocess

from app.services.codex_addy_capability_executor import (
    CodexCapabilityExecutionError,
    execute_codex_addy_capability,
)
from app.services.harness_capability_service import (
    CapabilityAuthorization,
    CapabilityDefinition,
    execute_capability,
)


def _capability() -> CapabilityDefinition:
    return CapabilityDefinition(
        capability_id="addy:code-review-and-quality",
        provider="addy-agent-skills",
        execution_kind="codex_native_skill",
        allowed_actions=("DEVELOPMENT",),
        tags=("code", "review", "quality"),
    )


def _repository(tmp_path: Path) -> Path:
    repository = tmp_path / "repo"
    repository.mkdir()
    subprocess.run(["git", "init"], cwd=repository, check=True, capture_output=True)
    (repository / "sample.py").write_text("VALUE = 1\n")
    subprocess.run(["git", "add", "sample.py"], cwd=repository, check=True)
    return repository


def test_executor_invokes_only_selected_skill_in_disposable_snapshot(tmp_path):
    repository = _repository(tmp_path)
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))

        if command == ["codex", "login", "status"]:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        snapshot = Path(kwargs["cwd"])
        assert snapshot != repository
        assert (snapshot / "sample.py").read_text() == "VALUE = 1\n"
        (snapshot / "temporary-change.txt").write_text("discarded\n")
        stdout = json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "type": "agent_message",
                    "text": "review complete",
                },
            }
        )
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    result = execute_codex_addy_capability(
        _capability(),
        {"task": "Review sample.py for correctness."},
        runner=runner,
        repository_root=repository,
    )

    assert calls[0][0] == ["codex", "login", "status"]
    command, kwargs = calls[1]
    assert command[:2] == ["codex", "exec"]
    assert "--ephemeral" in command
    assert command[command.index("--sandbox") + 1] == "read-only"
    prompt = command[-1]
    assert "@code-review-and-quality" in prompt
    assert "@using-agent-skills" not in prompt
    assert "Do not publish" in prompt
    assert kwargs["check"] is False
    assert not (repository / "temporary-change.txt").exists()
    assert result == {
        "output": "review complete",
        "exit_code": 0,
        "sandbox": "read-only",
        "workspace": "disposable_snapshot",
        "skill": "code-review-and-quality",
    }


def test_executor_rejects_payload_without_task(tmp_path):
    repository = _repository(tmp_path)

    try:
        execute_codex_addy_capability(
            _capability(),
            {},
            repository_root=repository,
        )
    except ValueError as exc:
        assert "non-empty 'task'" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_executor_failure_does_not_expose_stderr(tmp_path):
    repository = _repository(tmp_path)

    def runner(command, **kwargs):
        if command == ["codex", "login", "status"]:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        return subprocess.CompletedProcess(
            command,
            7,
            stdout="",
            stderr="SECRET=must-not-leak",
        )

    try:
        execute_codex_addy_capability(
            _capability(),
            {"task": "Review sample.py."},
            runner=runner,
            repository_root=repository,
        )
    except CodexCapabilityExecutionError as exc:
        assert str(exc) == "Codex capability execution failed"
        assert "SECRET" not in str(exc)
    else:
        raise AssertionError("expected CodexCapabilityExecutionError")


def test_harness_returns_failed_evidence_without_fallback():
    calls = []

    def failing_executor(capability, payload):
        calls.append(capability.capability_id)
        raise CodexCapabilityExecutionError("Codex capability execution failed")

    evidence = execute_capability(
        capability_id="addy:code-review-and-quality",
        authorization=CapabilityAuthorization(
            authority="deepseek_harness",
            authorized_action="DEVELOPMENT",
            harness_decision_id="decision-99",
            execution_id="execution-99",
        ),
        payload={"task": "Review sample.py."},
        executor=failing_executor,
    )

    assert calls == ["addy:code-review-and-quality"]
    assert evidence.status == "FAILED"
    assert evidence.active is False
    assert evidence.harness_decision_id == "decision-99"
    assert evidence.execution_id == "execution-99"
    assert evidence.result == {
        "error_type": "CodexCapabilityExecutionError",
        "error": "Codex capability execution failed",
    }
    assert evidence.boundary == "Capability executor failed; no fallback executed"
