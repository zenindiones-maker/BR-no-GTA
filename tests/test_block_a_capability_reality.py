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
    assert statuses["OPENAI_AGENTS_API"]=="HUMAN_CONFIGURATION_REQUIRED"
    assert statuses["OPENAI_NATIVE_DOTS"]=="NOT_AVAILABLE_ON_CURRENT_PLUS_PLAN"
    assert statuses["OPENAI_SPECIALIST_DOTS"]=="PRODUCT_NOT_AVAILABLE_FOR_CURRENT_ACCOUNT_CLASS"
    assert statuses["SPRITE_RUNTIME"]=="CONTRACT_PRESENT_BUT_LIVE_EXECUTOR_UNPROVEN"
    assert statuses["OPENAI_SELF_HOSTED_SPRITE"]=="NOT_PROVEN"
    assert statuses["GPT_6_1_SOL"]=="LIVE_ACCESS_NOT_PROVEN"
    assert report["system_operational"]=="NOT_CERTIFIED"
    assert report["block_a_status"]=="HUMAN_CONFIGURATION_REQUIRED"
    assert report["authority"]=="DEEPSEEK_HARNESS"


def test_block_a_report_never_serializes_project_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY","sk-proj-this-is-not-output")
    report=build_report(head="b"*40,chatgpt_plan="PLUS")
    raw=str(report)
    assert "sk-proj-this-is-not-output" not in raw
    assert report["statuses"]["OPENAI_AGENTS_API"]=="CONFIGURED_BUT_LIVE_NOT_PROVEN"
    assert report["block_a_status"]=="LIVE_CANARIES_REQUIRED"
    assert report["configuration"]["raw_key_serialized"] is False
