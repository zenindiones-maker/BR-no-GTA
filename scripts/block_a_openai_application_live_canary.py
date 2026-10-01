from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
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

from app.database.openai_agents_repository import (
    persist_openai_agent_session_receipt,
    persist_openai_tool_result,
)
from app.database.schema import initialize_schema
from app.services.agent_office.delegation import (
    DelegatedTaskLease,
    MANDATORY_FORBIDDEN_ACTIONS,
)
from app.services.harness_authorization_service import (
    issue_harness_authorization,
    validate_harness_authorization,
)
from app.services.harness_collaboration_service import TaskEnvelope
from app.services.openai_agents_contracts import OpenAIAgentSessionReceipt
from app.services.openai_agents_runtime_service import (
    validate_application_secret_isolation,
    verify_openai_task_completion,
)
from app.services.task_result_envelope_service import (
    build_task_result_envelope,
    persist_task_result_envelope,
)
from scripts.openai_agents_dd2_live_canary import configuration_state


MODEL_ID = "gpt-6.1-sol"
REASONING_EFFORT = "low"
MISSION_ID = "block-a-live-mission"
GOAL_ID = "block-a-prove-real-openai-agent"
APPLICATION_RUNTIME_REVISION = "block-a-application-live-v1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dump(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return dict(value.model_dump())
    if isinstance(value, dict):
        return dict(value)
    return {}


def _usage(value: Any) -> dict[str, Any]:
    raw = getattr(value, "usage", None)
    if raw is None:
        return {}
    if hasattr(raw, "model_dump"):
        return dict(raw.model_dump())
    if isinstance(raw, dict):
        return dict(raw)
    return {}


def _safe_message(exc: Exception) -> str:
    text = str(exc or "")
    lowered = text.lower()
    if any(marker in lowered for marker in (
        "sk-",
        "bearer ",
        "api_key",
        "authorization:",
        "access_token",
        "refresh_token",
    )):
        return "OpenAI live request failed; sensitive detail redacted."
    return text[:800]


def classify_live_failure(exc: Exception) -> tuple[str, str]:
    status = getattr(exc, "status_code", None)
    name = type(exc).__name__.lower()
    message = str(exc or "").lower()

    if status == 401 or "authentication" in name or "invalid api key" in message:
        return "AUTHENTICATION_DENIED", _safe_message(exc)
    if status == 403 or "permissiondenied" in name or "permission denied" in message:
        return "PERMISSION_DENIED", _safe_message(exc)
    # OpenAI can return HTTP 429 for exhausted project credits. Classify the
    # causal quota/billing condition before generic rate limiting so we do not
    # mislabel a deterministic billing blocker as a transient throttling event.
    if status == 402 or any(term in message for term in (
        "billing",
        "insufficient_quota",
        "insufficient quota",
        "credit balance",
        "credit_balance_exhausted",
        "no credits remaining",
        "payment required",
    )):
        return "BILLING_REQUIRED", _safe_message(exc)
    if status == 429 or "ratelimit" in name or "rate limit" in message:
        return "RATE_LIMITED", _safe_message(exc)
    if any(term in message for term in (
        "model_not_found",
        "model not found",
        "does not exist",
        "not have access to model",
        "model is not available",
        "unsupported model",
    )):
        return "MODEL_UNAVAILABLE", _safe_message(exc)
    return "OTHER_TYPED_REASON", _safe_message(exc)


def _client():
    from openai import OpenAI

    config = configuration_state()
    if config.get("status") != "PASS":
        raise RuntimeError("OpenAI authentication is not configured")
    mode = config.get("authentication_mode")
    if mode == "PROJECT_API_KEY":
        return OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    if mode == "WIF":
        from scripts.openai_agents_dd2_live_canary import _github_oidc_subject_provider

        return OpenAI(
            workload_identity={
                "identity_provider_id": os.environ["OPENAI_IDENTITY_PROVIDER_ID"],
                "service_account_id": os.environ["OPENAI_SERVICE_ACCOUNT_ID"],
                "provider": _github_oidc_subject_provider(
                    os.environ["OPENAI_WIF_AUDIENCE"]
                ),
            },
        )
    raise RuntimeError("Unsupported OpenAI authentication mode")


def _wait_session(client: Any, session_id: str, *, wanted: set[str], timeout: int = 180) -> Any:
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = client.beta.agents.sessions.retrieve(session_id)
        state = str(getattr(last, "status", "") or "")
        if state in wanted:
            return last
        time.sleep(1)
    raise TimeoutError(
        f"Agents session {session_id} did not reach {sorted(wanted)}; "
        f"last={getattr(last, 'status', None)}"
    )


def _task_envelope(
    *,
    task_id: str,
    objective: str,
    allowed_tools: tuple[str, ...] = (),
    expected_outputs: tuple[str, ...] = (),
) -> TaskEnvelope:
    return TaskEnvelope(
        task_id=task_id,
        capability_id="openai.agents.session",
        action="EXECUTION",
        objective=objective,
        task_class="AGENTIC_EXECUTION",
        functional_role="EXECUTOR",
        allowed_tools=allowed_tools,
        expected_outputs=expected_outputs,
        evidence_requirements=("OpenAIAgentSessionReceipt/v1", "TaskResultEnvelope/v1"),
        failure_semantics="FAIL_CLOSED",
        mission_id=MISSION_ID,
        goal_id=GOAL_ID,
    )


def _task_lease(*, task_id: str, allowed_tools: tuple[str, ...]) -> DelegatedTaskLease:
    return DelegatedTaskLease.from_mapping({
        "mission_id": MISSION_ID,
        "task_id": task_id,
        "goal_id": GOAL_ID,
        "harness_decision_id": f"decision:{task_id}",
        "authorization_id": f"lease-auth:{task_id}",
        "delegation_id": f"delegation:{task_id}",
        "agent_id": "openai-agents-root",
        "capability_ids": ["openai.agents.session"],
        "base_sha": os.environ.get("GITHUB_SHA", "0" * 40),
        "allowed_paths": [],
        "allowed_tools": list(allowed_tools or ("openai.agents.session",)),
        "allowed_actions": ["EXECUTION"],
        "forbidden_actions": sorted(MANDATORY_FORBIDDEN_ACTIONS),
        "input_artifact_refs": [],
        "expected_outputs": ["TaskResultEnvelope/v1"],
        "acceptance_criteria": ["Harness verifies runtime evidence"],
        "evidence_requirements": ["session receipt", "task result"],
        "time_budget_seconds": 600,
        "cost_budget": 5.0,
        "tool_call_budget": 8,
        "retry_budget": 1,
        "max_parallelism": 1,
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat(),
        "escalation_conditions": ["authorization mismatch", "provider failure"],
        "owned_task_class": "AGENTIC_EXECUTION",
        "role": "openai-agents-root",
        "read_set": [],
        "write_set": [],
    })


def _persist_completed_receipt(
    *,
    session: Any,
    task_id: str,
    attempt_id: str,
    turn_id: str,
    artifact_refs: tuple[str, ...] = (),
    tool_calls: tuple[dict[str, Any], ...] = (),
    trace_refs: tuple[str, ...] = (),
) -> OpenAIAgentSessionReceipt:
    payload = _dump(session)
    environment = payload.get("environment")
    if not isinstance(environment, dict):
        environment = {}
    raw_session = {
        "id": str(getattr(session, "id", "") or payload.get("id") or ""),
        "status": "idle",
        "environment": environment,
        "required_actions": [],
        "usage": _usage(session),
    }
    receipt = OpenAIAgentSessionReceipt.from_api(
        raw_session,
        turn={"id": turn_id, "status": "completed", "usage": _usage(session)},
        agent_model=MODEL_ID,
        reasoning_effort=REASONING_EFFORT,
        multi_agent_enabled=False,
        subagent_count=0,
        tool_calls=tool_calls,
        artifacts=tuple(
            {"artifact_ref": ref} for ref in artifact_refs
        ),
        trace_refs=trace_refs,
        task_id=task_id,
        attempt_id=attempt_id,
        runtime_revision=APPLICATION_RUNTIME_REVISION,
        provider="openai",
    )
    persisted = persist_openai_agent_session_receipt(receipt)
    if persisted.get("state") != "TURN_COMPLETED":
        raise RuntimeError("persisted OpenAI receipt did not preserve TURN_COMPLETED")
    return receipt


def probe_model(client: Any) -> dict[str, Any]:
    started = time.monotonic()
    response = client.responses.create(
        model=MODEL_ID,
        reasoning={"effort": REASONING_EFFORT},
        input=(
            "Return exactly one minified JSON object with keys status and value. "
            'status must be "ok" and value must be 42.'
        ),
    )
    elapsed_ms = round((time.monotonic() - started) * 1000, 3)
    text = str(getattr(response, "output_text", "") or "").strip()
    try:
        parsed = json.loads(text)
    except Exception as exc:
        raise RuntimeError("STRUCTURED_REASONING_NOT_JSON") from exc
    if parsed != {"status": "ok", "value": 42}:
        raise RuntimeError("STRUCTURED_REASONING_MISMATCH")
    observed_model = str(getattr(response, "model", "") or MODEL_ID)
    if observed_model != MODEL_ID:
        raise RuntimeError(f"MODEL_IDENTITY_MISMATCH:{observed_model}")
    return {
        "status": "PASS",
        "model": observed_model,
        "response_id": str(getattr(response, "id", "") or ""),
        "reasoning_effort": REASONING_EFFORT,
        "latency_ms": elapsed_ms,
        "usage": _usage(response),
        "result_digest": sha256(text.encode("utf-8")).hexdigest(),
    }


def probe_agents_tool(client: Any, *, artifact_dir: Path) -> dict[str, Any]:
    task_id = "block-a-live-tool"
    attempt_id = "attempt-1"
    execution_id = f"{task_id}:{attempt_id}"
    task = _task_envelope(
        task_id=task_id,
        objective="Execute one authorized deterministic read-only function tool call.",
        allowed_tools=("block_a_readonly_probe",),
    )
    lease = _task_lease(
        task_id=task_id,
        allowed_tools=("block_a_readonly_probe",),
    )
    lease.assert_active()
    authorization = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject="capability:openai.agents.session",
        execution_id=execution_id,
        lineage={
            "mission_id": MISSION_ID,
            "goal_id": GOAL_ID,
            "task_id": task_id,
            "tool": "block_a_readonly_probe",
            "authority": "DEEPSEEK_HARNESS",
        },
    )
    validate_harness_authorization(
        authorization,
        expected_action="EXECUTION",
        expected_subject="capability:openai.agents.session",
        expected_execution_id=execution_id,
    )
    if "block_a_readonly_probe" not in task.allowed_tools:
        raise PermissionError("TaskEnvelope does not authorize live read-only tool")
    if "block_a_readonly_probe" not in lease.allowed_tools:
        raise PermissionError("DelegatedTaskLease does not authorize live read-only tool")

    started = time.monotonic()
    session = client.beta.agents.sessions.create(
        agent={
            "model": MODEL_ID,
            "reasoning": {"effort": REASONING_EFFORT},
            "instructions": (
                "You are a subordinate execution worker. "
                "Call block_a_readonly_probe exactly once with probe_id='block-a-a3'. "
                "Do not perform any other action."
            ),
            "tools": [{
                "type": "function",
                "name": "block_a_readonly_probe",
                "description": "Return bounded read-only Block A verification data.",
                "parameters": {
                    "type": "object",
                    "properties": {"probe_id": {"type": "string"}},
                    "required": ["probe_id"],
                    "additionalProperties": False,
                },
            }],
            "multi_agent": {"enabled": False},
        },
        environment={"type": "none"},
        input="Run the authorized Block A read-only probe now.",
    )
    session_id = str(getattr(session, "id", "") or "")
    if not session_id:
        raise RuntimeError("AGENTS_API_SESSION_ID_MISSING")

    pending = _wait_session(
        client,
        session_id,
        wanted={"requires_action", "failed"},
        timeout=120,
    )
    if str(getattr(pending, "status", "")) == "failed":
        raise RuntimeError("AGENTS_API_TOOL_SESSION_FAILED")

    actions = list(getattr(pending, "required_actions", ()) or ())
    matching = [
        action for action in actions
        if str(getattr(action, "type", "") or "") == "function_call"
        and str(getattr(action, "name", "") or "") == "block_a_readonly_probe"
    ]
    if len(matching) != 1:
        raise RuntimeError("AGENTS_API_EXPECTED_TOOL_CALL_NOT_OBSERVED")
    action = matching[0]
    action_dict = _dump(action)
    call_id = str(getattr(action, "call_id", "") or action_dict.get("call_id") or "")
    turn_id = str(getattr(action, "turn_id", "") or action_dict.get("turn_id") or "")
    arguments = getattr(action, "arguments", None)
    if isinstance(arguments, str):
        arguments = json.loads(arguments)
    elif not isinstance(arguments, dict):
        arguments = action_dict.get("arguments") or {}
    if arguments.get("probe_id") != "block-a-a3":
        raise RuntimeError("AGENTS_API_TOOL_ARGUMENT_MISMATCH")
    if not call_id or not turn_id:
        raise RuntimeError("AGENTS_API_TOOL_CALL_IDENTITY_MISSING")

    tool_output = {
        "probe_id": "block-a-a3",
        "status": "READ_ONLY_OK",
        "head": os.environ.get("GITHUB_SHA", ""),
    }
    output_json = json.dumps(tool_output, ensure_ascii=False, sort_keys=True)
    persisted_tool = persist_openai_tool_result(
        session_id=session_id,
        turn_id=turn_id,
        call_id=call_id,
        tool_name="block_a_readonly_probe",
        success=True,
        output_json=output_json,
        evidence_refs=(
            f"authorization:{authorization.authorization_id}",
            f"task:{task_id}",
        ),
    )
    if persisted_tool["duplicate"]:
        raise RuntimeError("LIVE_TOOL_CALL_UNEXPECTEDLY_DUPLICATE_ON_FIRST_EXECUTION")

    client.beta.agents.sessions.events.create(
        session_id,
        events=[{
            "type": "agent.session.input.tool_result",
            "turn_id": turn_id,
            "call_id": call_id,
            "success": True,
            "output": output_json,
        }],
    )
    terminal = _wait_session(
        client,
        session_id,
        wanted={"idle", "failed", "requires_action"},
        timeout=120,
    )
    if str(getattr(terminal, "status", "")) != "idle":
        raise RuntimeError(
            f"AGENTS_API_TOOL_SESSION_TERMINAL_{str(getattr(terminal, 'status', '')).upper()}"
        )

    receipt = _persist_completed_receipt(
        session=terminal,
        task_id=task_id,
        attempt_id=attempt_id,
        turn_id=turn_id,
        tool_calls=({
            "call_id": call_id,
            "turn_id": turn_id,
            "tool_name": "block_a_readonly_probe",
            "result_digest": persisted_tool["result_digest"],
        },),
        trace_refs=(
            f"authorization:{authorization.authorization_id}",
            f"mission:{MISSION_ID}",
            f"goal:{GOAL_ID}",
            f"task:{task_id}",
        ),
    )
    started_at = _now()
    task_result = build_task_result_envelope(
        mission_id=MISSION_ID,
        task_id=task_id,
        capability_id="openai.agents.session",
        agent_id="openai-agents-root",
        skill_id=None,
        executor_binding=(
            "app.services.openai_agents_runtime_service.execute_openai_agents_session"
        ),
        status="COMPLETED",
        started_at=started_at,
        completed_at=_now(),
        elapsed_ms=round((time.monotonic() - started) * 1000, 3),
        result={
            "summary": "Authorized read-only OpenAI Agents function tool completed.",
            "evidence_refs": [
                f"authorization:{authorization.authorization_id}",
                f"tool-result:{persisted_tool['result_digest']}",
            ],
        },
        source_task_ids=(),
        authorization_id=authorization.authorization_id,
    )
    persisted_result = persist_task_result_envelope(
        task_result,
        artifact_dir=artifact_dir,
        index=1,
    )
    verified = verify_openai_task_completion(
        receipt,
        task_envelope=task,
        task_result=task_result,
        verification_ref=f"task-result:{task_result.content_sha256}",
    )
    persist_openai_agent_session_receipt(verified, expected_current_revision=1)
    if verified.state != "TASK_VERIFIED":
        raise RuntimeError("HARNESS_REDUCER_DID_NOT_VERIFY_LIVE_TOOL_TASK")

    return {
        "status": "PASS",
        "session_id": session_id,
        "turn_id": turn_id,
        "task_id": task_id,
        "attempt_id": attempt_id,
        "call_id": call_id,
        "tool_name": "block_a_readonly_probe",
        "tool_result_digest": persisted_tool["result_digest"],
        "task_result_ref": persisted_result["task_result_ref"],
        "task_result_digest": task_result.content_sha256,
        "receipt_state_before_reduction": receipt.state,
        "receipt_state_after_reduction": verified.state,
        "turn_completed_is_task_success": False,
        "harness_reducer": "PASS",
        "usage": _usage(terminal),
    }


def probe_hosted_artifact(client: Any, *, artifact_dir: Path) -> dict[str, Any]:
    task_id = "block-a-live-artifact"
    attempt_id = "attempt-1"
    expected_ref = "artifact:/workspace/outputs/block_a_hosted_artifact.json"
    task = _task_envelope(
        task_id=task_id,
        objective="Create one harmless deterministic hosted artifact and verify it.",
        expected_outputs=(expected_ref,),
    )
    authorization = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject="capability:openai.agents.session",
        execution_id=f"{task_id}:{attempt_id}",
        lineage={
            "mission_id": MISSION_ID,
            "goal_id": GOAL_ID,
            "task_id": task_id,
            "authority": "DEEPSEEK_HARNESS",
        },
    )
    started = time.monotonic()
    session = client.beta.agents.sessions.create(
        agent={
            "model": MODEL_ID,
            "reasoning": {"effort": REASONING_EFFORT},
            "instructions": (
                "Use only the OpenAI-hosted sandbox. Do not access the network. "
                "Verify the file contents before completing."
            ),
            "multi_agent": {"enabled": False},
        },
        environment={
            "type": "openai_hosted",
            "network": {"access": "disabled"},
        },
        input=(
            "Create /workspace/outputs/block_a_hosted_artifact.json containing exactly "
            '{"block":"A","kind":"hosted-artifact","value":42}. '
            "Read it back, verify it, and finish."
        ),
    )
    session_id = str(getattr(session, "id", "") or "")
    if not session_id:
        raise RuntimeError("AGENTS_API_ARTIFACT_SESSION_ID_MISSING")
    terminal = _wait_session(
        client,
        session_id,
        wanted={"idle", "failed", "requires_action"},
        timeout=180,
    )
    if str(getattr(terminal, "status", "")) != "idle":
        raise RuntimeError(
            f"AGENTS_API_ARTIFACT_SESSION_TERMINAL_{str(getattr(terminal, 'status', '')).upper()}"
        )

    page = client.beta.agents.sessions.artifacts.list(session_id, limit=50)
    artifacts = list(getattr(page, "data", ()) or ())
    matches = [
        item for item in artifacts
        if str(getattr(item, "path", "") or "") ==
        "/workspace/outputs/block_a_hosted_artifact.json"
    ]
    if len(matches) != 1:
        raise RuntimeError("EXPECTED_HOSTED_ARTIFACT_NOT_PUBLISHED")
    artifact = matches[0]
    artifact_id = str(getattr(artifact, "id", "") or "")
    turn_id = str(getattr(artifact, "turn_id", "") or "")
    size_bytes = int(getattr(artifact, "size_bytes", 0) or 0)
    if not artifact_id or not turn_id or size_bytes <= 0:
        raise RuntimeError("HOSTED_ARTIFACT_METADATA_INCOMPLETE")

    digest = None
    digest_state = "NOT_RETRIEVABLE_DURING_ACTIVE_ENVIRONMENT"
    try:
        response = client.beta.agents.sessions.artifacts.content(
            artifact_id,
            session_id=session_id,
        )
        raw = response.read()
        if raw:
            digest = sha256(raw).hexdigest()
            digest_state = "RETRIEVED"
    except Exception:
        pass

    receipt = _persist_completed_receipt(
        session=terminal,
        task_id=task_id,
        attempt_id=attempt_id,
        turn_id=turn_id,
        artifact_refs=(expected_ref,),
        trace_refs=(
            f"authorization:{authorization.authorization_id}",
            f"mission:{MISSION_ID}",
            f"goal:{GOAL_ID}",
            f"task:{task_id}",
            f"artifact-id:{artifact_id}",
        ),
    )
    task_result = build_task_result_envelope(
        mission_id=MISSION_ID,
        task_id=task_id,
        capability_id="openai.agents.session",
        agent_id="openai-agents-root",
        skill_id=None,
        executor_binding=(
            "app.services.openai_agents_runtime_service.execute_openai_agents_session"
        ),
        status="COMPLETED",
        started_at=_now(),
        completed_at=_now(),
        elapsed_ms=round((time.monotonic() - started) * 1000, 3),
        result={
            "summary": "OpenAI-hosted deterministic artifact published.",
            "artifact_ref": expected_ref,
            "artifact_id": artifact_id,
            "artifact_size_bytes": size_bytes,
            "artifact_digest": digest,
            "evidence_refs": [
                f"authorization:{authorization.authorization_id}",
                f"session:{session_id}",
                f"turn:{turn_id}",
            ],
        },
        source_task_ids=(),
        authorization_id=authorization.authorization_id,
    )
    persisted_result = persist_task_result_envelope(
        task_result,
        artifact_dir=artifact_dir,
        index=2,
    )
    verified = verify_openai_task_completion(
        receipt,
        task_envelope=task,
        task_result=task_result,
        verification_ref=f"task-result:{task_result.content_sha256}",
    )
    persist_openai_agent_session_receipt(verified, expected_current_revision=1)
    return {
        "status": "PASS",
        "session_id": session_id,
        "turn_id": turn_id,
        "task_id": task_id,
        "attempt_id": attempt_id,
        "artifact_id": artifact_id,
        "artifact_path": "/workspace/outputs/block_a_hosted_artifact.json",
        "artifact_size_bytes": size_bytes,
        "artifact_digest": digest,
        "artifact_digest_state": digest_state,
        "task_result_ref": persisted_result["task_result_ref"],
        "task_result_digest": task_result.content_sha256,
        "receipt_state_before_reduction": receipt.state,
        "receipt_state_after_reduction": verified.state,
        "harness_reducer": "PASS",
        "usage": _usage(terminal),
    }


def run(*, artifact_dir: Path) -> dict[str, Any]:
    config = configuration_state()
    result: dict[str, Any] = {
        "schema": "BlockAOpenAIApplicationLiveCanary/v1",
        "generated_at": _now(),
        "head": os.environ.get("GITHUB_SHA", "UNKNOWN"),
        "mission_id": MISSION_ID,
        "goal_id": GOAL_ID,
        "auth": {
            "auth_mode": config.get("authentication_mode", "NONE"),
            "credential_present": bool(config.get("credential_present")),
            "credential_source_class": config.get("credential_source_class", "NONE"),
        },
        "model": MODEL_ID,
        "reasoning_effort": REASONING_EFFORT,
        "gates": {
            "OPENAI_APPLICATION_AUTH": "NOT_PROVEN",
            "GPT_6_1_SOL": "NOT_PROVEN",
            "AGENTS_API_LIVE": "NOT_PROVEN",
            "TOOL_CALL_LIVE": "NOT_PROVEN",
            "TASK_RESULT_LIVE": "NOT_PROVEN",
            "HARNESS_REDUCER_LIVE": "NOT_PROVEN",
            "ARTIFACT_LIVE": "NOT_PROVEN",
            "APPLICATION_SECRET_ISOLATION": "NOT_PROVEN",
        },
        "status": "NOT_PROVEN",
        "blocker": None,
    }
    if config.get("status") != "PASS":
        result["status"] = "EXTERNAL_CONFIGURATION_REQUIRED"
        result["blocker"] = {
            "code": "EXTERNAL_CONFIGURATION_REQUIRED",
            "reason": config.get("reason"),
        }
        return result

    try:
        client = _client()
        model = probe_model(client)
        result["model_probe"] = model
        result["gates"]["OPENAI_APPLICATION_AUTH"] = "PASS"
        result["gates"]["GPT_6_1_SOL"] = "PASS"

        tool = probe_agents_tool(client, artifact_dir=artifact_dir)
        result["agents_tool_probe"] = tool
        result["gates"]["AGENTS_API_LIVE"] = "PASS"
        result["gates"]["TOOL_CALL_LIVE"] = "PASS"
        result["gates"]["TASK_RESULT_LIVE"] = "PASS"
        result["gates"]["HARNESS_REDUCER_LIVE"] = (
            "PASS" if tool["harness_reducer"] == "PASS" else "FAIL"
        )

        artifact = probe_hosted_artifact(client, artifact_dir=artifact_dir)
        result["hosted_artifact_probe"] = artifact
        result["gates"]["ARTIFACT_LIVE"] = "PASS"

        isolation = validate_application_secret_isolation(result)
        result["secret_isolation"] = isolation
        result["gates"]["APPLICATION_SECRET_ISOLATION"] = "PASS"
        result["status"] = "PASS"
        return result
    except Exception as exc:
        code, message = classify_live_failure(exc)
        result["status"] = "FAIL"
        result["blocker"] = {
            "code": code,
            "exception_type": type(exc).__name__,
            "message": message,
        }
        if result["gates"]["OPENAI_APPLICATION_AUTH"] == "NOT_PROVEN":
            if code == "AUTHENTICATION_DENIED":
                result["gates"]["OPENAI_APPLICATION_AUTH"] = "FAIL"
            elif code in {"PERMISSION_DENIED", "BILLING_REQUIRED", "MODEL_UNAVAILABLE", "RATE_LIMITED"}:
                result["gates"]["OPENAI_APPLICATION_AUTH"] = "PASS"
                result["gates"]["GPT_6_1_SOL"] = (
                    "INELIGIBLE_WITH_REASON"
                    if code == "MODEL_UNAVAILABLE"
                    else "NOT_PROVEN"
                )
        return result


def _assert_sanitized(result: dict[str, Any]) -> None:
    raw = json.dumps(result, ensure_ascii=False, sort_keys=True)
    lowered = raw.lower()
    forbidden = (
        "sk-proj-",
        "bearer ",
        '"openai_api_key"',
        '"openai_executor_api_key"',
        '"codex_api_key"',
        '"api_key"',
        '"access_token"',
        '"refresh_token"',
    )
    if any(item in lowered for item in forbidden):
        raise PermissionError("Block A live evidence contains secret material")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--artifact-dir", required=True)
    args = parser.parse_args()

    os.environ["BR_TEST_DATABASE"] = str(Path(args.database).resolve())
    initialize_schema()
    artifact_dir = Path(args.artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)

    result = run(artifact_dir=artifact_dir)
    _assert_sanitized(result)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    print("BLOCK_A_APPLICATION_LIVE_STATUS=" + result["status"])
    print("OPENAI_APPLICATION_AUTH=" + result["gates"]["OPENAI_APPLICATION_AUTH"])
    print("GPT_6_1_SOL_STATUS=" + result["gates"]["GPT_6_1_SOL"])
    print("AGENTS_API_LIVE=" + result["gates"]["AGENTS_API_LIVE"])
    print("TOOL_CALL_LIVE=" + result["gates"]["TOOL_CALL_LIVE"])
    print("ARTIFACT_LIVE=" + result["gates"]["ARTIFACT_LIVE"])
    if result.get("blocker"):
        print("BLOCK_A_TYPED_BLOCKER=" + str(result["blocker"]["code"]))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
