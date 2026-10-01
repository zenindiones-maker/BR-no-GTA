from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.openai_agents_dd2_live_canary import configuration_state


MODEL_ID = "gpt-6.1-sol"
REASONING_EFFORT = "low"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dump(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return dict(value.model_dump())
    if isinstance(value, dict):
        return dict(value)
    return {}


def _safe_failure(exc: Exception) -> dict[str, str]:
    from scripts.block_a_openai_application_live_canary import classify_live_failure
    code, message = classify_live_failure(exc)
    return {
        "code": code,
        "exception_type": type(exc).__name__,
        "message": message,
    }


def _client():
    from scripts.block_a_openai_application_live_canary import _client as application_client
    return application_client()


def _environment_metadata(session: Any) -> tuple[str, str]:
    payload = _dump(session)
    env = payload.get("environment")
    if not isinstance(env, dict):
        env = {}
    environment_id = str(env.get("id") or env.get("environment_id") or "")
    remote_url = str(
        env.get("remote_url")
        or (env.get("connect") or {}).get("remote_url")
        or ""
    )
    if not environment_id:
        environment_id = str(payload.get("environment_id") or "")
    if not remote_url:
        remote_url = str((payload.get("connect") or {}).get("remote_url") or "")
    return environment_id, remote_url


def _session_required_actions(session: Any) -> list[dict[str, Any]]:
    actions = []
    for action in list(getattr(session, "required_actions", ()) or ()):
        actions.append(_dump(action))
    return actions


def _print_coordination(session_id: str, environment_id: str, remote_url: str) -> None:
    print("BLOCK_A_SELF_HOSTED_SESSION_ID=" + session_id, flush=True)
    print("BLOCK_A_SELF_HOSTED_ENVIRONMENT_ID=" + environment_id, flush=True)
    print("BLOCK_A_SELF_HOSTED_REMOTE_URL=" + remote_url, flush=True)


def _artifact_digest_if_retrievable(client: Any, session_id: str, artifact_id: str) -> tuple[str | None, str]:
    try:
        response = client.beta.agents.sessions.artifacts.content(
            artifact_id,
            session_id=session_id,
        )
        raw = response.read()
        if raw:
            return sha256(raw).hexdigest(), "RETRIEVED"
    except Exception:
        pass
    return None, "NOT_RETRIEVABLE_DURING_ACTIVE_ENVIRONMENT"


def run_base(*, output: Path, timeout_seconds: int) -> dict[str, Any]:
    config = configuration_state()
    proof: dict[str, Any] = {
        "schema": "BlockASelfHostedOpenAISpriteLiveCanary/v1",
        "generated_at": _now(),
        "head": os.environ.get("GITHUB_SHA", "UNKNOWN"),
        "auth": {
            "auth_mode": config.get("authentication_mode", "NONE"),
            "credential_present": bool(config.get("credential_present")),
            "credential_source_class": config.get("credential_source_class", "NONE"),
        },
        "model": MODEL_ID,
        "reasoning_effort": REASONING_EFFORT,
        "workspace_directory": "/workspace/BR",
        "capability_directories": [],
        "gates": {
            "AGENTS_SELF_HOSTED_SESSION_CREATED": "NOT_PROVEN",
            "SPRITE_EXECUTOR_CONNECTED": "NOT_PROVEN",
            "SELF_HOSTED_TASK_RESULT": "NOT_PROVEN",
            "SPRITE_ARTIFACT_LINEAGE": "NOT_PROVEN",
        },
        "status": "NOT_PROVEN",
        "blocker": None,
    }
    if config.get("status") != "PASS":
        proof["status"] = "EXTERNAL_CONFIGURATION_REQUIRED"
        proof["blocker"] = {
            "code": "EXTERNAL_CONFIGURATION_REQUIRED",
            "reason": config.get("reason"),
        }
        output.write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return proof

    client = _client()
    session = None
    try:
        session = client.beta.agents.sessions.create(
            agent={
                "model": MODEL_ID,
                "reasoning": {"effort": REASONING_EFFORT},
                "instructions": (
                    "You are a subordinate Block A execution worker. "
                    "Use only the connected self-hosted workspace. "
                    "Do not access the network. Do not mutate the repository. "
                    "Create only the requested JSON artifact outside tracked source files. "
                    "Verify it before completing."
                ),
                "multi_agent": {"enabled": False},
            },
            environment={
                "type": "self_hosted",
                "workspace_directory": "/workspace/BR",
                "capability_directories": [],
            },
            input=(
                "Create /workspace/block-a-output/self_hosted_canary.json containing exactly "
                '{"task_id":"block-a-self-hosted-1","value":42,"kind":"sprite-canary"}. '
                "Read it back and verify all fields. Do not edit any repository file."
            ),
        )
        session_id = str(getattr(session, "id", "") or "")
        environment_id, remote_url = _environment_metadata(session)
        if not session_id:
            raise RuntimeError("AGENTS_API_SESSION_ID_MISSING")
        if not environment_id or not remote_url:
            raise RuntimeError("SELF_HOSTED_ENVIRONMENT_CONNECTION_METADATA_MISSING")
        proof["session_id"] = session_id
        proof["environment_id"] = environment_id
        proof["remote_url"] = remote_url
        proof["gates"]["AGENTS_SELF_HOSTED_SESSION_CREATED"] = "PASS"
        _print_coordination(session_id, environment_id, remote_url)

        deadline = time.monotonic() + timeout_seconds
        last_status = None
        observed_environment_connection = False
        while time.monotonic() < deadline:
            current = client.beta.agents.sessions.retrieve(session_id)
            status = str(getattr(current, "status", "") or "")
            actions = _session_required_actions(current)
            if status != last_status:
                print("BLOCK_A_SELF_HOSTED_SESSION_STATUS=" + status, flush=True)
                last_status = status
            for action in actions:
                action_type = str(action.get("type") or "")
                if action_type == "environment_connection":
                    observed_environment_connection = True
                    print("BLOCK_A_SELF_HOSTED_WAITING_FOR_EXECUTOR=1", flush=True)
                elif action_type:
                    raise RuntimeError("UNEXPECTED_SELF_HOSTED_REQUIRED_ACTION:" + action_type)
            if status == "idle":
                session = current
                break
            if status == "failed":
                raise RuntimeError("SELF_HOSTED_AGENT_SESSION_FAILED")
            time.sleep(2)
        else:
            raise TimeoutError("SELF_HOSTED_AGENT_SESSION_TIMEOUT")

        proof["observed_environment_connection"] = observed_environment_connection
        proof["gates"]["SPRITE_EXECUTOR_CONNECTED"] = "PASS"

        page = client.beta.agents.sessions.artifacts.list(session_id, limit=50)
        artifacts = list(getattr(page, "data", ()) or ())
        target_path = "/workspace/block-a-output/self_hosted_canary.json"
        matches = [a for a in artifacts if str(getattr(a, "path", "") or "") == target_path]
        if len(matches) != 1:
            raise RuntimeError("SELF_HOSTED_EXPECTED_ARTIFACT_NOT_PUBLISHED")
        artifact = matches[0]
        artifact_id = str(getattr(artifact, "id", "") or "")
        turn_id = str(getattr(artifact, "turn_id", "") or "")
        size_bytes = int(getattr(artifact, "size_bytes", 0) or 0)
        if not artifact_id or not turn_id or size_bytes <= 0:
            raise RuntimeError("SELF_HOSTED_ARTIFACT_METADATA_INCOMPLETE")
        digest, digest_state = _artifact_digest_if_retrievable(
            client, session_id, artifact_id
        )
        proof["turn_id"] = turn_id
        proof["artifact"] = {
            "artifact_id": artifact_id,
            "path": target_path,
            "size_bytes": size_bytes,
            "digest": digest,
            "digest_state": digest_state,
            "environment_id": str(getattr(artifact, "environment_id", "") or ""),
        }
        if proof["artifact"]["environment_id"] != environment_id:
            raise RuntimeError("SELF_HOSTED_ARTIFACT_ENVIRONMENT_LINEAGE_MISMATCH")
        proof["gates"]["SELF_HOSTED_TASK_RESULT"] = "PASS"
        proof["gates"]["SPRITE_ARTIFACT_LINEAGE"] = "PASS"
        proof["status"] = "PASS"
    except Exception as exc:
        proof["status"] = "FAIL"
        proof["blocker"] = _safe_failure(exc)
        if str(exc).startswith("SELF_HOSTED_") or str(exc).startswith("UNEXPECTED_SELF_HOSTED"):
            proof["blocker"]["code"] = str(exc).split(":", 1)[0]
    finally:
        raw = json.dumps(proof, ensure_ascii=False, sort_keys=True)
        lowered = raw.lower()
        for forbidden in (
            "sk-proj-",
            "bearer ",
            '"openai_api_key"',
            '"openai_executor_api_key"',
            '"codex_api_key"',
            '"api_key"',
        ):
            if forbidden in lowered:
                raise PermissionError("self-hosted live proof contains secret material")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(proof, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
    return proof


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--timeout-seconds", type=int, default=900)
    args = parser.parse_args()

    result = run_base(
        output=Path(args.output),
        timeout_seconds=args.timeout_seconds,
    )
    print("OPENAI_SELF_HOSTED_SPRITE=" + result["status"])
    for key, value in sorted(result["gates"].items()):
        print(f"{key}={value}")
    if result.get("blocker"):
        print("BLOCK_A_SELF_HOSTED_TYPED_BLOCKER=" + str(result["blocker"]["code"]))
    return 0 if result["status"] == "PASS" else 3


if __name__ == "__main__":
    raise SystemExit(main())
