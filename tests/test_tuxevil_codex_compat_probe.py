from __future__ import annotations

from pathlib import Path

from scripts import tuxevil_codex_compat_probe as probe


def test_tuxevil_codex_compatibility_is_supported_when_ci_upstream_auth_is_missing(
    tmp_path: Path,
    monkeypatch,
):
    replies = iter(
        [
            {
                "reachable": True,
                "ok": True,
                "status": 200,
                "json": {
                    "data": [
                        {
                            "id": "gemini-3-flash",
                            "owned_by": "google-antigravity",
                        }
                    ]
                },
                "body_sha256": "models",
                "safe_error": {},
            },
        ]
    )

    monkeypatch.setattr(probe, "_request_json", lambda *args, **kwargs: next(replies))
    result = probe.run(
        output=tmp_path / "proof.json",
        base_url="http://127.0.0.1:51200",
        client_key="tuxevil",
        configured_model="gemini-3-flash",
        ci_credential_path="NONE",
        virtual_key_available=False,
        project_antigravity_configured=True,
        codex_action_endpoint_supported=True,
        process_ready=True,
        status_ready=True,
        runtime_account_count=0,
        antigravity_account_present=False,
        tuxevil_responses_endpoint_supported=True,
    )

    assert result["TUXEVIL_CODEX_COMPATIBILITY"] == "SUPPORTED"
    assert result["ANTIGRAVITY_RUNTIME_AUTH"] == (
        "BLOCKED_MISSING_CI_CREDENTIAL_MATERIALIZATION"
    )
    assert result["TUXEVIL_PROCESS_READY"] == "PASS"
    assert result["TUXEVIL_STATUS_ENDPOINT"] == "PASS"
    assert result["TUXEVIL_RUNTIME_ACCOUNT_COUNT"] == 0
    assert result["ANTIGRAVITY_ACCOUNT_PRESENT"] == "NO"
    assert result["TUXEVIL_MODELS_READY"] == "PASS"
    assert result["ANTIGRAVITY_UPSTREAM_AUTH"] == "NOT_ATTEMPTED"
    assert result["TUXEVIL_RESPONSES_API"] == "NOT_ATTEMPTED"
    assert result["OPENAI_PLATFORM_API_KEY_REQUIRED"] == "NOT_EVALUATED"
    assert result["AUTH_SECRET_LEAK"] == "NO"


def test_tuxevil_live_responses_and_tool_calling_remove_openai_platform_key_requirement(
    tmp_path: Path,
    monkeypatch,
):
    replies = iter(
        [
            {
                "reachable": True,
                "ok": True,
                "status": 200,
                "json": {
                    "data": [
                        {
                            "id": "gemini-3-flash",
                            "owned_by": "google-antigravity",
                        }
                    ]
                },
                "body_sha256": "models",
                "safe_error": {},
            },
            {
                "reachable": True,
                "ok": True,
                "status": 200,
                "json": {"output_text": "TUXEVIL_RESPONSES_OK"},
                "body_sha256": "responses",
                "safe_error": {},
            },
            {
                "reachable": True,
                "ok": True,
                "status": 200,
                "json": {
                    "output": [
                        {
                            "type": "function_call",
                            "name": "br_probe",
                            "arguments": "{\"value\":\"ok\"}",
                        }
                    ]
                },
                "body_sha256": "tools",
                "safe_error": {},
            },
        ]
    )

    monkeypatch.setattr(probe, "_request_json", lambda *args, **kwargs: next(replies))
    result = probe.run(
        output=tmp_path / "proof.json",
        base_url="http://127.0.0.1:51200",
        client_key="tuxevil",
        configured_model="gemini-3-flash",
        ci_credential_path="EXISTING_SECURE_MATERIALIZATION",
        virtual_key_available=False,
        project_antigravity_configured=True,
        codex_action_endpoint_supported=True,
        process_ready=True,
        status_ready=True,
        runtime_account_count=1,
        antigravity_account_present=True,
        tuxevil_responses_endpoint_supported=True,
    )

    assert result["TUXEVIL_PROCESS_READY"] == "PASS"
    assert result["TUXEVIL_STATUS_ENDPOINT"] == "PASS"
    assert result["TUXEVIL_RUNTIME_ACCOUNT_COUNT"] == 1
    assert result["ANTIGRAVITY_ACCOUNT_PRESENT"] == "YES"
    assert result["TUXEVIL_MODELS_READY"] == "PASS"
    assert result["TUXEVIL_RESPONSES_API"] == "PASS"
    assert result["ANTIGRAVITY_UPSTREAM_AUTH"] == "PASS"
    assert result["TUXEVIL_LIVE_INFERENCE"] == "PASS"
    assert result["TUXEVIL_TOOL_CALLING"] == "PASS"
    assert result["OPENAI_PLATFORM_API_KEY_REQUIRED"] == "NO"
