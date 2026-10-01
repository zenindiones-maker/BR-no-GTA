from __future__ import annotations

import json

from scripts.openai_agents_dd2_live_canary import configuration_state, run_live_canary


def test_live_canary_missing_auth_is_typed_external_configuration(monkeypatch):
    for name in (
        "OPENAI_API_KEY",
        "OPENAI_WIF_AUDIENCE",
        "OPENAI_IDENTITY_PROVIDER_ID",
        "OPENAI_SERVICE_ACCOUNT_ID",
        "ACTIONS_ID_TOKEN_REQUEST_URL",
        "ACTIONS_ID_TOKEN_REQUEST_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)

    state=configuration_state()
    assert state["status"]=="EXTERNAL_CONFIGURATION_REQUIRED"
    assert state["credential_present"] is False
    assert state["credential_source_class"]=="NONE"

    result=run_live_canary()
    assert result["status"]=="EXTERNAL_CONFIGURATION_REQUIRED"
    assert result["model_state"]=="INELIGIBLE_WITH_REASON"
    assert result["agents_api_state"]=="EXTERNAL_CONFIGURATION_REQUIRED"
    assert result["secret_material_in_output"] is False
    assert all(
        value=="EXTERNAL_CONFIGURATION_REQUIRED"
        for key,value in result["gates"].items()
        if key not in {"OPENAI_WIF","OPENAI_PROJECT_API_KEY"}
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
    state=configuration_state(env)
    assert state["status"]=="PASS"
    assert state["authentication_mode"]=="WIF"
    assert state["credential_source_class"]=="GITHUB_OIDC_FEDERATED_IDENTITY"
    del env["OPENAI_SERVICE_ACCOUNT_ID"]
    state=configuration_state(env)
    assert state["status"]=="EXTERNAL_CONFIGURATION_REQUIRED"
    assert state["missing"]==("OPENAI_API_KEY",)
    assert state["reason"]=="OPENAI_PROJECT_CREDENTIAL_UNAVAILABLE"


def test_project_api_key_configuration_is_supported_without_wif_fields(monkeypatch):
    for name in (
        "OPENAI_WIF_AUDIENCE",
        "OPENAI_IDENTITY_PROVIDER_ID",
        "OPENAI_SERVICE_ACCOUNT_ID",
        "ACTIONS_ID_TOKEN_REQUEST_URL",
        "ACTIONS_ID_TOKEN_REQUEST_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-secret")
    state=configuration_state()
    assert state["status"]=="PASS"
    assert state["authentication_mode"]=="PROJECT_API_KEY"
    assert state["credential_present"] is True
    assert state["credential_source_class"]=="GITHUB_ACTIONS_SECRET"
    assert state["reason"]=="OPENAI_PROJECT_API_KEY_PRESENT"


def test_fully_configured_wif_precedes_project_key():
    env={
        "OPENAI_API_KEY":"test-project-key",
        "OPENAI_WIF_AUDIENCE":"https://api.openai.com/v1",
        "OPENAI_IDENTITY_PROVIDER_ID":"wip_123",
        "OPENAI_SERVICE_ACCOUNT_ID":"svc_123",
        "ACTIONS_ID_TOKEN_REQUEST_URL":"https://example.invalid/oidc",
        "ACTIONS_ID_TOKEN_REQUEST_TOKEN":"runtime-secret",
    }
    state=configuration_state(env)
    assert state["authentication_mode"]=="WIF"
    assert state["credential_source_class"]=="GITHUB_OIDC_FEDERATED_IDENTITY"
