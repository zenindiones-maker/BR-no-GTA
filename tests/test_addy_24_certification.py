from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from app.services.codex_addy_capability_executor import execute_codex_addy_capability
from app.services.global_capability_registry_base import (
    ADDY_SKILLS,
    GLOBAL_CAPABILITY_REGISTRY,
)
from app.services.harness_authorization_service import issue_harness_authorization
from app.services.harness_capability_service import execute_capability


@pytest.fixture()
def tiny_repository(tmp_path: Path) -> Path:
    repository = tmp_path / "repo"
    repository.mkdir()
    subprocess.run(
        ["git", "init"],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    (repository / "proof.txt").write_text("addy-24-certification\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "proof.txt"],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    return repository


@pytest.mark.parametrize("skill_name", ADDY_SKILLS)
def test_each_addy_skill_has_governed_harness_execution_contract(
    skill_name: str,
    tiny_repository: Path,
):
    capability_id = f"addy:{skill_name}"
    record = GLOBAL_CAPABILITY_REGISTRY.get(capability_id)
    assert record is not None
    assert record.available is True
    assert record.execution_enabled is True
    assert record.agent_id == "codex"
    assert record.skill_id == skill_name

    decision_id = f"addy-24-decision-{skill_name}"
    execution_id = f"addy-24-execution-{skill_name}"
    authorization = issue_harness_authorization(
        authorized_action="DEVELOPMENT",
        subject=f"capability:{capability_id}",
        harness_decision_id=decision_id,
        execution_id=execution_id,
        lineage={
            "certification": "addy-24",
            "skill": skill_name,
        },
    )

    calls: list[tuple[list[str], dict]] = []

    def runner(command, **kwargs):
        calls.append((list(command), kwargs))
        if command == ["codex", "login", "status"]:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        stdout = json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "type": "agent_message",
                    "text": f"certified:{skill_name}",
                },
            }
        )
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    evidence = execute_capability(
        capability_id=capability_id,
        authorization=authorization,
        payload={"task": f"Certification probe for {skill_name}."},
        executor=lambda capability, payload: execute_codex_addy_capability(
            capability,
            payload,
            runner=runner,
            repository_root=tiny_repository,
        ),
    )

    assert evidence.status == "EXECUTED"
    assert evidence.active is True
    assert evidence.authority == "deepseek_harness"
    assert evidence.harness_decision_id == decision_id
    assert evidence.execution_id == execution_id
    assert evidence.result["skill"] == skill_name
    assert evidence.result["sandbox"] == "read-only"
    assert evidence.result["workspace"] == "disposable_snapshot"

    assert calls[0][0] == ["codex", "login", "status"]
    command = calls[1][0]
    assert command[:2] == ["codex", "exec"]
    assert "--ephemeral" in command
    assert command[command.index("--sandbox") + 1] == "read-only"

    prompt = command[-1]
    assert f"@{skill_name}" in prompt
    for other_skill in ADDY_SKILLS:
        if other_skill != skill_name:
            assert f"@{other_skill}" not in prompt


def test_addy_certification_inventory_is_exactly_24_unique_skills():
    assert len(ADDY_SKILLS) == 24
    assert len(set(ADDY_SKILLS)) == 24
    assert "browser-testing-with-devtools" not in ADDY_SKILLS
