from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess

import pytest

from app.database import harness_learning_repository
from app.database.telegram_user_input_repository import upsert_telegram_user_input
from app.services.harness_authorization_service import issue_harness_authorization
from app.services.telegram_reasoning_incident_reconciler import (
    reconcile_specific_telegram_provider_failure,
)


RUN_ID = 35340487375
JOB_ID = 105585029658
PROVIDER = "opencode"
MODEL = "oc/big-pickle"
EXECUTOR = "app.services.omniroute_gateway_service.execute_omniroute_gateway"


def _iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seed_realistic_provenance():
    input_record = upsert_telegram_user_input(
        telegram_user_id=111,
        telegram_chat_id=111,
        telegram_message_id=222,
        telegram_update_id=333,
        input_kind="text",
        text_content="Teste real de raciocínio governado",
        classification="question",
        learning_status="captured",
        memory_event_id=444,
        provenance={"source": "telegram"},
    )
    authorization = issue_harness_authorization(
        authorized_action="DECISION",
        subject="provider:opencode",
        harness_decision_id="decision-telegram-real",
        execution_id="execution-telegram-real",
        lineage={
            "routing_id": "routing-telegram-real",
            "capability_id": "ai.reasoning.text",
            "selected_provider": PROVIDER,
            "selected_model": MODEL,
            "selected_executor_binding": EXECUTOR,
            "ingress": "telegram",
            "telegram_input_id": input_record["id"],
        },
    )
    return input_record, authorization


def _runner(command):
    command = list(command)
    joined = " ".join(command)
    now = _iso()
    if command[:2] == ["gh", "api"] and f"actions/runs/{RUN_ID}/jobs" not in joined:
        return json.dumps(
            {
                "id": RUN_ID,
                "status": "completed",
                "conclusion": "failure",
                "head_sha": "ed2309d07d3db35a41dd521b360af73e74c1677c",
                "path": ".github/workflows/omniroute.yml",
                "created_at": now,
                "updated_at": now,
                "run_started_at": now,
            }
        )
    if command[:2] == ["gh", "api"] and f"actions/runs/{RUN_ID}/jobs" in joined:
        return json.dumps(
            {
                "jobs": [
                    {
                        "id": JOB_ID,
                        "name": "omniroute",
                        "status": "completed",
                        "conclusion": "failure",
                        "started_at": now,
                        "completed_at": now,
                        "steps": [
                            {
                                "name": "Execute explicit free provider/model",
                                "status": "completed",
                                "conclusion": "failure",
                            }
                        ],
                    }
                ]
            }
        )
    if command[:4] == ["gh", "run", "view", str(RUN_ID)]:
        return (
            "PROVIDER: opencode\n"
            "MODEL: oc/big-pickle\n"
            "urllib.error.HTTPError: HTTP Error 403: Forbidden\n"
            "Process completed with exit code 1.\n"
        )
    raise AssertionError(f"unexpected command: {command}")


def test_specific_reconciliation_is_idempotent_for_episode_memory_and_competence():
    input_record, authorization = _seed_realistic_provenance()

    first = reconcile_specific_telegram_provider_failure(
        repository="zenindiones-maker/BR-no-GTA",
        run_id=RUN_ID,
        command_runner=_runner,
        expected_job_id=JOB_ID,
        expected_provider=PROVIDER,
        expected_model=MODEL,
        expected_http_status=403,
        expected_exit_code=1,
    )
    second = reconcile_specific_telegram_provider_failure(
        repository="zenindiones-maker/BR-no-GTA",
        run_id=RUN_ID,
        command_runner=_runner,
        expected_job_id=JOB_ID,
        expected_provider=PROVIDER,
        expected_model=MODEL,
        expected_http_status=403,
        expected_exit_code=1,
    )

    assert first["IDEMPOTENT"] is False
    assert second["IDEMPOTENT"] is True
    assert second["episode_id"] == first["episode_id"]
    assert second["failure_memory_id"] == first["failure_memory_id"]
    assert first["authorization_id"] == authorization.authorization_id
    assert first["telegram_input_id"] == input_record["id"]
    assert first["provider_error"]["status_code"] == 403
    assert first["provider_error"]["exit_code"] == 1
    assert first["provider_error"]["run_id"] == RUN_ID
    assert first["USER_GOAL_COMPLETED"] == "NO"

    episodes = harness_learning_repository.list_episodes(
        domain="ai",
        task_class="telegram-reasoning",
        capability_id="ai.reasoning.text",
        limit=20,
    )
    assert len(episodes) == 1
    assert episodes[0]["status"] == "FAILED"
    assert episodes[0]["actual_outcome"]["telegram_ingress"] == "PASS"
    assert episodes[0]["actual_outcome"]["harness_reasoning"] == "FAIL"
    assert episodes[0]["actual_outcome"]["user_goal_completed"] is False

    memories = harness_learning_repository.list_memories(
        status="ACTIVE",
        memory_type="FAILURE",
        domain="ai",
        task_class="telegram-reasoning",
        capability_id="ai.reasoning.text",
        limit=20,
    )
    assert len(memories) == 1
    assert memories[0]["support_count"] == 1
    assert memories[0]["source_episode_ids"] == [first["episode_id"]]

    competence = harness_learning_repository.list_competence(
        domain="ai",
        task_class="telegram-reasoning",
        capability_id="ai.reasoning.text",
        agent_id="provider:opencode",
        limit=20,
    )
    assert len(competence) == 1
    assert competence[0]["tested_cases"] == 1
    assert competence[0]["failure_count"] == 1


def test_specific_reconciliation_fails_closed_on_evidence_mismatch():
    _seed_realistic_provenance()

    with pytest.raises(PermissionError, match="evidence mismatch"):
        reconcile_specific_telegram_provider_failure(
            repository="zenindiones-maker/BR-no-GTA",
            run_id=RUN_ID,
            command_runner=_runner,
            expected_job_id=JOB_ID,
            expected_provider=PROVIDER,
            expected_model=MODEL,
            expected_http_status=401,
            expected_exit_code=1,
        )

    assert harness_learning_repository.list_episodes(
        domain="ai",
        task_class="telegram-reasoning",
        capability_id="ai.reasoning.text",
        limit=20,
    ) == []


def test_reconciliation_cli_uses_exact_evidence_contract(monkeypatch, capsys):
    _seed_realistic_provenance()
    import scripts.reconcile_telegram_reasoning_incident as cli

    monkeypatch.setattr(cli, "run_github_actions_command", _runner)
    rc = cli.main(
        [
            "--repository",
            "zenindiones-maker/BR-no-GTA",
            "--run-id",
            str(RUN_ID),
            "--job-id",
            str(JOB_ID),
            "--provider",
            PROVIDER,
            "--model",
            MODEL,
            "--http-status",
            "403",
            "--exit-code",
            "1",
        ]
    )
    assert rc == 0
    output = capsys.readouterr().out
    assert "TELEGRAM_INCIDENT_RECONCILIATION=PASS" in output
    assert "REAL_TELEGRAM_FAILURE_EPISODE=" in output
    assert "FAILURE_MEMORY_FROM_REAL_INCIDENT=" in output

def test_real_recovery_wrapper_is_syntax_valid_and_pins_observed_evidence():
    root = Path(__file__).resolve().parents[1]
    wrapper = root / "scripts" / "promote_real_telegram_recovery.sh"
    assert wrapper.is_file()

    checked = subprocess.run(
        ["bash", "-n", str(wrapper)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert checked.returncode == 0, checked.stderr

    source = wrapper.read_text(encoding="utf-8")
    assert 'BENCHMARK_RUN_ID="35346769369"' in source
    assert 'BENCHMARK_ARTIFACT_ID="10547072630"' in source
    assert 'BENCHMARK_ARTIFACT_NAME="telegram-opencode-executor-benchmark"' in source
    assert "bash scripts/reconcile_real_telegram_403.sh" in source
    assert "scripts/promote_telegram_opencode_executor_profile.py" in source
    assert "scripts/telegram_termux_control.sh" in source
    assert "gh run download" in source
    assert "--benchmark-run-id" in source
    assert "--benchmark-artifact-id" in source
    assert "TELEGRAM_REAL_RECOVERY=READY_FOR_NEXT_REAL_INTERACTION" in source

