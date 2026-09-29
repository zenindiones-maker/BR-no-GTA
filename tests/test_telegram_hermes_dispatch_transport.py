from __future__ import annotations

import base64
import json
from pathlib import Path

from app.services.telegram_hermes_dispatch_service import (
    HERMES_TELEGRAM_LAUNCHER_WORKFLOW,
    _build_launcher_inputs,
)


ROOT = Path(__file__).resolve().parents[1]


def test_telegram_hermes_uses_default_branch_registered_launcher():
    assert HERMES_TELEGRAM_LAUNCHER_WORKFLOW == "dynamic-system-improvement.yml"
    assert HERMES_TELEGRAM_LAUNCHER_WORKFLOW != "telegram-hermes-control-mission.yml"


def test_launcher_payload_preserves_exact_branch_and_mission_contract():
    inputs = _build_launcher_inputs(
        dispatch_id="tg-hermes--1001-abc-start-deadbeef",
        mode="start",
        mission_id="tg-hermes--1001-abc",
        goal_id="telegram-editorial-review",
        chat_id=-1001,
        target_ref="work/gate6f-analytics-learning",
        target_sha="a" * 40,
        artifact_ref="script:8",
        request_text="Crie roteiros atualizados do gta 6",
        artifact_text_b64="YWJj",
        artifact_sha256="b" * 64,
        parent_run_id="",
        human_answer="",
    )

    assert set(inputs) == {
        "dispatch_id",
        "target_ref",
        "target_sha",
        "plan_b64",
        "human_goal_b64",
        "telegram_chat_id",
    }
    assert inputs["target_ref"] == "work/gate6f-analytics-learning"
    assert inputs["target_sha"] == "a" * 40
    assert inputs["telegram_chat_id"] == "-1001"
    assert base64.b64decode(inputs["human_goal_b64"]).decode("utf-8") == (
        "Crie roteiros atualizados do gta 6"
    )

    plan = json.loads(base64.b64decode(inputs["plan_b64"]).decode("utf-8"))
    assert plan["schema"] == "TelegramHermesLauncherPlan/v1"
    assert plan["kind"] == "TELEGRAM_HERMES_CONTROL"
    assert plan["mode"] == "start"
    assert plan["mission_id"] == "tg-hermes--1001-abc"
    assert plan["goal_id"] == "telegram-editorial-review"
    assert plan["artifact_ref"] == "script:8"
    assert plan["artifact_text_b64"] == "YWJj"
    assert plan["artifact_sha256"] == "b" * 64


def test_registered_launcher_contains_dedicated_telegram_hermes_route():
    workflow = (
        ROOT / ".github/workflows/dynamic-system-improvement.yml"
    ).read_text(encoding="utf-8")

    assert "telegram-hermes:" in workflow
    assert "TELEGRAM_HERMES_CONTROL" in workflow
    assert "scripts/telegram_hermes_control_mission.py" in workflow
    assert "telegram-hermes-control-${{ github.run_id }}" in workflow
    assert "startsWith(inputs.dispatch_id, 'tg-hermes-')" in workflow
