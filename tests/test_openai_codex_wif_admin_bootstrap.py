from __future__ import annotations

import pytest

from scripts import openai_codex_wif_admin_bootstrap as wif


def test_wif_reconcile_reuses_exact_provider_and_rule(monkeypatch):
    calls = []

    def fake_request(*, method, path, admin_key, payload=None):
        calls.append((method, path, payload))
        if path == "/providers":
            return {
                "object": "list",
                "data": [{
                    "id": "idp_existing",
                    "type": "oidc",
                    "issuer": wif.ISSUER,
                    "audience": wif.DEFAULT_AUDIENCE,
                    "enabled": True,
                }],
            }
        if path == "/providers/idp_existing/mappings":
            return {
                "object": "list",
                "data": [{
                    "id": "idpm_existing",
                    "enabled": True,
                    "claims": {
                        "repository": wif.REPOSITORY,
                        "ref": wif.REF,
                    },
                    "audiences": [wif.DEFAULT_AUDIENCE],
                }],
            }
        raise AssertionError(path)

    monkeypatch.setattr(wif, "_request", fake_request)
    result = wif.reconcile(
        admin_key="admin-test-only",
        audience=wif.DEFAULT_AUDIENCE,
        workspace_id="",
        principal_id="",
    )

    assert result["provider_id"] == "idp_existing"
    assert result["federation_rule_id"] == "idpm_existing"
    assert result["provider_created"] is False
    assert result["rule_created"] is False
    assert result["runtime_auth_variables"] == [
        "OPENAI_FEDERATION_RULE_ID",
        "OPENAI_IDENTITY_TOKEN_FILE",
    ]
    assert all(call[0] == "GET" for call in calls)


def test_wif_reconcile_creates_repo_branch_scoped_rule(monkeypatch):
    created = []

    def fake_request(*, method, path, admin_key, payload=None):
        if method == "GET" and path == "/providers":
            return {"object": "list", "data": []}
        if method == "POST" and path == "/providers":
            created.append(("provider", payload))
            return {
                "id": "idp_created",
                "type": "oidc",
                "issuer": payload["issuer"],
                "audience": payload["audience"],
                "enabled": True,
            }
        if method == "GET" and path == "/providers/idp_created/mappings":
            return {"object": "list", "data": []}
        if method == "POST" and path == "/providers/idp_created/mappings":
            created.append(("rule", payload))
            return {"id": "idpm_created", **payload}
        raise AssertionError((method, path))

    monkeypatch.setattr(wif, "_request", fake_request)
    result = wif.reconcile(
        admin_key="admin-test-only",
        audience=wif.DEFAULT_AUDIENCE,
        workspace_id="ws_real",
        principal_id="principal_real",
    )

    assert result["provider_created"] is True
    assert result["rule_created"] is True
    provider_payload = created[0][1]
    rule_payload = created[1][1]
    assert provider_payload["issuer"] == "https://token.actions.githubusercontent.com"
    assert provider_payload["audience"] == wif.DEFAULT_AUDIENCE
    assert rule_payload["claims"] == {
        "repository": "zenindiones-maker/BR-no-GTA",
        "ref": "refs/heads/work/gate6f-analytics-learning",
    }
    assert rule_payload["audiences"] == [wif.DEFAULT_AUDIENCE]
    assert rule_payload["workspace_id"] == "ws_real"
    assert rule_payload["principal_id"] == "principal_real"


def test_wif_reconcile_requires_real_workspace_and_principal_for_new_rule(monkeypatch):
    def fake_request(*, method, path, admin_key, payload=None):
        if path == "/providers":
            return {
                "object": "list",
                "data": [{
                    "id": "idp_existing",
                    "type": "oidc",
                    "issuer": wif.ISSUER,
                    "audience": wif.DEFAULT_AUDIENCE,
                    "enabled": True,
                }],
            }
        if path == "/providers/idp_existing/mappings":
            return {"object": "list", "data": []}
        raise AssertionError(path)

    monkeypatch.setattr(wif, "_request", fake_request)
    with pytest.raises(wif.AdminBootstrapRequired):
        wif.reconcile(
            admin_key="admin-test-only",
            audience=wif.DEFAULT_AUDIENCE,
            workspace_id="",
            principal_id="",
        )
