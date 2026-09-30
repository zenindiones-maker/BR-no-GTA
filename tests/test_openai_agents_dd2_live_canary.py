from __future__ import annotations

import json

from scripts.openai_agents_dd2_live_canary import configuration_state, run_live_canary


def test_live_canary_missing_wif_is_typed_external_configuration(monkeypatch):
    for name in (
        "OPENAI_WIF_AUDIENCE",
        "OPENAI_IDENTITY_PROVIDER_ID",
        "OPENAI_SERVICE_ACCOUNT_ID",
        "ACTIONS_ID_TOKEN_REQUEST_URL",
        "ACTIONS_ID_TOKEN_REQUEST_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)

    state=configuration_state()
    assert state["status"]=="EXTERNAL_CONFIGURATION_REQUIRED"

    result=run_live_canary()
    assert result["status"]=="EXTERNAL_CONFIGURATION_REQUIRED"
    assert result["model_state"]=="INELIGIBLE_WITH_REASON"
    assert result["agents_api_state"]=="EXTERNAL_CONFIGURATION_REQUIRED"
    assert result["secret_material_in_output"] is False
    assert all(
        value=="EXTERNAL_CONFIGURATION_REQUIRED"
        for key,value in result["gates"].items()
        if key!="OPENAI_WIF"
    )
    serialized=json.dumps(result).lower()
    for forbidden in ("sk-","bearer ","runtime-secret"):
        assert forbidden not in serialized


def test_wif_configuration_requires_all_identity_fields():
    env={
        "OPENAI_WIF_AUDIENCE":"https://api.openai.com/v1",
        "OPENAI_IDENTITY_PROVIDER_ID":"wip_123",
        "OPENAI_SERVICE_ACCOUNT_ID":"svc_123",
        "ACTIONS_ID_TOKEN_REQUEST_URL":"https://example.invalid/oidc",
        "ACTIONS_ID_TOKEN_REQUEST_TOKEN":"runtime-secret",
    }
    assert configuration_state(env)["status"]=="PASS"
    del env["OPENAI_SERVICE_ACCOUNT_ID"]
    state=configuration_state(env)
    assert state["status"]=="EXTERNAL_CONFIGURATION_REQUIRED"
    assert state["missing"]==("OPENAI_SERVICE_ACCOUNT_ID",)
