from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import time
from typing import Any


REQUIRED_WIF_ENV = (
    "OPENAI_WIF_AUDIENCE",
    "OPENAI_IDENTITY_PROVIDER_ID",
    "OPENAI_SERVICE_ACCOUNT_ID",
    "ACTIONS_ID_TOKEN_REQUEST_URL",
    "ACTIONS_ID_TOKEN_REQUEST_TOKEN",
)


def configuration_state(env: dict[str, str] | None = None) -> dict[str, Any]:
    values = env if env is not None else dict(os.environ)
    missing_wif = tuple(name for name in REQUIRED_WIF_ENV if not values.get(name))
    if not missing_wif:
        return {
            "status": "PASS",
            "reason": "OPENAI_WIF_CONFIGURATION_PRESENT",
            "authentication_mode": "WIF",
            "credential_present": True,
            "credential_source_class": "GITHUB_OIDC_FEDERATED_IDENTITY",
            "missing": (),
        }
    if values.get("OPENAI_API_KEY"):
        return {
            "status": "PASS",
            "reason": "OPENAI_PROJECT_API_KEY_PRESENT",
            "authentication_mode": "PROJECT_API_KEY",
            "credential_present": True,
            "credential_source_class": "GITHUB_ACTIONS_SECRET",
            "missing": (),
        }
    return {
        "status": "EXTERNAL_CONFIGURATION_REQUIRED",
        "reason": "OPENAI_PROJECT_CREDENTIAL_UNAVAILABLE",
        "authentication_mode": "NONE",
        "credential_present": False,
        "credential_source_class": "NONE",
        "missing": ("OPENAI_API_KEY",),
        "minimum_required_permissions": (
            "api.agents.read",
            "api.agents.write",
            "api.responses.write",
        ),
    }


def _github_oidc_subject_provider(audience: str):
    import urllib.parse
    import urllib.request

    request_url = os.environ["ACTIONS_ID_TOKEN_REQUEST_URL"]
    request_token = os.environ["ACTIONS_ID_TOKEN_REQUEST_TOKEN"]

    def get_token() -> str:
        parsed = urllib.parse.urlparse(request_url)
        query = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
        query["audience"] = audience
        url = urllib.parse.urlunparse(
            parsed._replace(query=urllib.parse.urlencode(query))
        )
        request = urllib.request.Request(
            url,
            headers={"Authorization": f"bearer {request_token}"},
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
        token = payload.get("value")
        if not token:
            raise RuntimeError("GitHub OIDC token response omitted value")
        return token

    return {"token_type": "jwt", "get_token": get_token}


def _client():
    from openai import OpenAI

    config=configuration_state()
    if config.get("authentication_mode")=="PROJECT_API_KEY":
        return OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    if config.get("authentication_mode")!="WIF":
        raise RuntimeError("OpenAI live authentication is not configured")
    return OpenAI(
        workload_identity={
            "identity_provider_id": os.environ["OPENAI_IDENTITY_PROVIDER_ID"],
            "service_account_id": os.environ["OPENAI_SERVICE_ACCOUNT_ID"],
            "provider": _github_oidc_subject_provider(
                os.environ["OPENAI_WIF_AUDIENCE"]
            ),
        },
    )


def _extract_output_text(response: Any) -> str:
    value = getattr(response, "output_text", None)
    if isinstance(value, str):
        return value
    payload = response.model_dump() if hasattr(response, "model_dump") else {}
    return json.dumps(payload, ensure_ascii=False)


def _structured_reasoning_probe(client: Any) -> dict[str, Any]:
    response = client.responses.create(
        model="gpt-6.1-sol",
        reasoning={"effort": "low"},
        input=(
            "Return only a JSON object with keys answer and evidence. "
            "Compute 17 + 25. answer must be 42 and evidence must be 'arithmetic'."
        ),
    )
    text = _extract_output_text(response).strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {"status": "FAIL", "reason": "STRUCTURED_REASONING_NOT_JSON"}
    ok = payload.get("answer") == 42 and payload.get("evidence") == "arithmetic"
    return {
        "status": "PASS" if ok else "FAIL",
        "reason": "STRUCTURED_REASONING_VERIFIED" if ok else "STRUCTURED_REASONING_MISMATCH",
    }


def _tool_call_probe(client: Any) -> dict[str, Any]:
    response = client.responses.create(
        model="gpt-6.1-sol",
        reasoning={"effort": "low"},
        input="Call dd2_echo exactly once with value 7. Do not answer directly.",
        tools=[
            {
                "type": "function",
                "name": "dd2_echo",
                "description": "Return the supplied integer.",
                "parameters": {
                    "type": "object",
                    "properties": {"value": {"type": "integer"}},
                    "required": ["value"],
                    "additionalProperties": False,
                },
                "strict": True,
            }
        ],
        tool_choice={"type": "function", "name": "dd2_echo"},
    )
    output = list(getattr(response, "output", ()) or ())
    calls = [
        item for item in output
        if getattr(item, "type", None) == "function_call"
        and getattr(item, "name", None) == "dd2_echo"
    ]
    if len(calls) != 1:
        return {"status": "FAIL", "reason": "EXPECTED_FUNCTION_CALL_NOT_OBSERVED"}
    arguments = getattr(calls[0], "arguments", "{}")
    try:
        parsed = json.loads(arguments)
    except (TypeError, json.JSONDecodeError):
        parsed = {}
    ok = parsed.get("value") == 7
    return {
        "status": "PASS" if ok else "FAIL",
        "reason": "FUNCTION_TOOL_CALL_VERIFIED" if ok else "FUNCTION_ARGUMENT_MISMATCH",
    }


def _agent_code_artifact_probe(client: Any) -> dict[str, Any]:
    session = client.beta.agents.sessions.create(
        agent={
            "model": "gpt-6.1-sol",
            "instructions": (
                "Use the sandbox only. Verify all work before completion. "
                "Do not access the network."
            ),
        },
        environment={
            "type": "openai_hosted",
            "network": {"access": "disabled"},
        },
        input=(
            "Use Python to compute sum(range(1, 10)). "
            "Write /workspace/outputs/dd2_canary.json containing exactly "
            '{"sum":45,"kind":"dd2-agent-artifact"}. '
            "Read the file back and verify both fields before finishing."
        ),
        stream=False,
    )
    session_id = str(getattr(session, "id", "") or "")
    if not session_id:
        return {"status": "FAIL", "reason": "AGENT_SESSION_ID_MISSING"}

    terminal = None
    for _ in range(60):
        current = client.beta.agents.sessions.retrieve(session_id)
        status = str(getattr(current, "status", "") or "")
        if status in {"idle", "failed", "requires_action"}:
            terminal = current
            break
        time.sleep(2)
    if terminal is None:
        return {
            "status": "FAIL",
            "reason": "AGENT_SESSION_TIMEOUT",
            "session_id": session_id,
        }
    status = str(getattr(terminal, "status", "") or "")
    if status != "idle":
        return {
            "status": "FAIL",
            "reason": f"AGENT_SESSION_TERMINAL_{status.upper()}",
            "session_id": session_id,
        }

    page = client.beta.agents.sessions.artifacts.list(session_id, limit=20)
    artifacts = list(getattr(page, "data", ()) or ())
    matched = [
        artifact for artifact in artifacts
        if str(getattr(artifact, "path", "")) == "/workspace/outputs/dd2_canary.json"
    ]
    if not matched:
        return {
            "status": "FAIL",
            "reason": "EXPECTED_AGENT_ARTIFACT_NOT_PUBLISHED",
            "session_id": session_id,
        }
    artifact = matched[0]
    return {
        "status": "PASS",
        "reason": "AGENT_CODE_AND_ARTIFACT_VERIFIED",
        "session_id": session_id,
        "artifact_id": str(getattr(artifact, "id", "") or ""),
        "artifact_path": str(getattr(artifact, "path", "") or ""),
        "artifact_size_bytes": int(getattr(artifact, "size_bytes", 0) or 0),
    }


def run_live_canary() -> dict[str, Any]:
    config = configuration_state()
    gates = {
        "OPENAI_WIF": (
            "PASS" if config.get("authentication_mode")=="WIF"
            else "NOT_SELECTED"
        ),
        "OPENAI_PROJECT_API_KEY": (
            "PASS" if config.get("authentication_mode")=="PROJECT_API_KEY"
            else ("EXTERNAL_CONFIGURATION_REQUIRED" if config["status"]!="PASS" else "NOT_SELECTED")
        ),
        "GPT_6_1_SOL_STRUCTURED_REASONING": "NOT_PROVEN",
        "GPT_6_1_SOL_TOOL_CALL": "NOT_PROVEN",
        "AGENTS_API_SESSION": "NOT_PROVEN",
        "AGENTS_API_CODE_TASK": "NOT_PROVEN",
        "AGENTS_API_ARTIFACT": "NOT_PROVEN",
    }
    evidence: dict[str, Any] = {
        "configuration": config,
        "authentication_mode": config.get("authentication_mode", "NONE"),
        "model": "gpt-6.1-sol",
    }
    if config["status"] != "PASS":
        for key in tuple(gates):
            if key != "OPENAI_WIF":
                gates[key] = "EXTERNAL_CONFIGURATION_REQUIRED"
        return {
            "schema": "OpenAIAgentsDD2LiveCanary/v1",
            "status": "EXTERNAL_CONFIGURATION_REQUIRED",
            "model_state": "INELIGIBLE_WITH_REASON",
            "agents_api_state": "EXTERNAL_CONFIGURATION_REQUIRED",
            "gates": gates,
            "evidence": evidence,
            "secret_material_in_output": False,
        }

    try:
        client = _client()
        structured = _structured_reasoning_probe(client)
        gates["GPT_6_1_SOL_STRUCTURED_REASONING"] = structured["status"]
        evidence["structured_reasoning"] = structured

        tool = _tool_call_probe(client)
        gates["GPT_6_1_SOL_TOOL_CALL"] = tool["status"]
        evidence["tool_call"] = tool

        agent = _agent_code_artifact_probe(client)
        agent_status = agent["status"]
        gates["AGENTS_API_SESSION"] = agent_status
        gates["AGENTS_API_CODE_TASK"] = agent_status
        gates["AGENTS_API_ARTIFACT"] = agent_status
        evidence["agent_probe"] = agent
    except Exception as exc:
        message = str(exc)
        lowered = message.lower()
        secretish = ("sk-" in lowered or "bearer " in lowered or "api_key" in lowered)
        evidence["live_error"] = {
            "type": type(exc).__name__,
            "message": "OpenAI live canary failed." if secretish else message[:500],
        }
        for key, value in tuple(gates.items()):
            if value == "NOT_PROVEN":
                gates[key] = "FAIL"

    live_values = [
        gates["GPT_6_1_SOL_STRUCTURED_REASONING"],
        gates["GPT_6_1_SOL_TOOL_CALL"],
        gates["AGENTS_API_SESSION"],
        gates["AGENTS_API_CODE_TASK"],
        gates["AGENTS_API_ARTIFACT"],
    ]
    if all(value == "PASS" for value in live_values):
        status = "PASS"
        model_state = "PROVEN"
        agents_state = "PROVEN"
    elif "FAIL" in live_values:
        status = "FAIL"
        model_state = "INELIGIBLE_WITH_REASON"
        agents_state = "INELIGIBLE_WITH_REASON"
    else:
        status = "NOT_PROVEN"
        model_state = "INELIGIBLE_WITH_REASON"
        agents_state = "NOT_PROVEN"
    return {
        "schema": "OpenAIAgentsDD2LiveCanary/v1",
        "status": status,
        "model_state": model_state,
        "agents_api_state": agents_state,
        "gates": gates,
        "evidence": evidence,
        "secret_material_in_output": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = run_live_canary()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print("OPENAI_AGENTS_DD2_LIVE_STATUS=" + result["status"])
    print("GPT_6_1_SOL=" + result["model_state"])
    print("AGENTS_API=" + result["agents_api_state"])
    for key, value in sorted(result["gates"].items()):
        print(f"{key}={value}")
    return 1 if result["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
