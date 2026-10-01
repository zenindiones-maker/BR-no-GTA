from __future__ import annotations

from scripts.block_a_agent_execution_foundation_proof import build_report


def test_block_a_report_keeps_capability_realities_separate(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    for name in (
        "OPENAI_WIF_AUDIENCE",
        "OPENAI_IDENTITY_PROVIDER_ID",
        "OPENAI_SERVICE_ACCOUNT_ID",
        "ACTIONS_ID_TOKEN_REQUEST_URL",
        "ACTIONS_ID_TOKEN_REQUEST_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)
    report=build_report(head="a"*40,chatgpt_plan="PLUS")
    statuses=report["statuses"]
    assert statuses["BR_PERSISTENT_FORCE"]=="PROVEN"
    assert statuses["OPENAI_AGENTS_API"]=="DORMANT_BY_OWNER_COST_POLICY"
    assert statuses["OPENAI_NATIVE_DOTS"]=="NOT_AVAILABLE_ON_CURRENT_PLUS_PLAN"
    assert statuses["OPENAI_SPECIALIST_DOTS"]=="PRODUCT_NOT_AVAILABLE_FOR_CURRENT_ACCOUNT_CLASS"
    assert statuses["SPRITE_RUNTIME"]=="CONTRACT_PRESENT_BUT_LIVE_EXECUTOR_UNPROVEN"
    assert statuses["OPENAI_SELF_HOSTED_SPRITE"]=="NOT_PROVEN"
    assert statuses["GPT_6_1_SOL"]=="DORMANT_WITH_AGENTS_API"
    assert report["system_operational"]=="NOT_CERTIFIED"
    assert report["block_a_status"]=="CODEX_CHATGPT_LIVE_REQUIRED"
    assert report["authority"]=="DEEPSEEK_HARNESS"


def test_block_a_report_never_serializes_project_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY","sk-proj-this-is-not-output")
    report=build_report(head="b"*40,chatgpt_plan="PLUS")
    raw=str(report)
    assert "sk-proj-this-is-not-output" not in raw
    assert report["statuses"]["OPENAI_AGENTS_API"]=="DORMANT_BY_OWNER_COST_POLICY"
    assert report["block_a_status"]=="CODEX_CHATGPT_LIVE_REQUIRED"
    assert report["configuration"]["raw_key_serialized"] is False


def test_block_a_active_workflow_has_no_paid_openai_platform_fallback():
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    workflow=(root/".github/workflows/block-a-live-validation.yml").read_text(encoding="utf-8")
    assert "secrets.OPENAI_API_KEY" not in workflow
    assert "OPENAI_EXECUTOR_API_KEY" not in workflow
    assert "application-live:" not in workflow
    assert "OPENAI_AGENTS_API=DORMANT_BY_OWNER_COST_POLICY" in workflow
    assert "OPENAI_PLATFORM_API_SPEND=FORBIDDEN" in workflow
    assert "ACTIVE_OPENAI_EXECUTION_SURFACE=CODEX_CLI_CHATGPT_SUBSCRIPTION" in workflow
