from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import re
from typing import Any


TOOL_REQUEST_SCHEMA = "ToolRequestEnvelope/v1"
TOOL_RESULT_SCHEMA = "ToolResultEnvelope/v1"

MAX_AGENT_TURNS = 4
MAX_TOOL_CALLS = 4
MAX_PROVIDER_CALLS = 8
MAX_AGENT_CONTEXT_CHARS = 15000
MAX_TOOL_RESULT_CHARS = 9000

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,96}$")
_FORBIDDEN_ARGUMENT_KEYS = frozenset({
    "authorization",
    "authorization_id",
    "authorized_action",
    "executor",
    "executor_binding",
    "agent_id",
    "authority",
    "routing_id",
    "publication_authority",
    "policy_override",
})


class AgentToolRequestError(RuntimeError):
    pass


class AgentToolAuthorizationError(RuntimeError):
    pass


class AgentToolBudgetExceeded(RuntimeError):
    pass


def _jsonable(value: Any) -> Any:
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _jsonable(value.to_dict())
    if is_dataclass(value):
        return {
            str(name): _jsonable(getattr(value, name))
            for name in value.__dataclass_fields__
        }
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return value


def _embedded_json_objects(text: str):
    raw = str(text or "")
    decoder = json.JSONDecoder()
    cursor = 0
    while cursor < len(raw):
        start = raw.find("{", cursor)
        if start < 0:
            return
        try:
            value, consumed = decoder.raw_decode(raw[start:])
        except json.JSONDecodeError:
            cursor = start + 1
            continue
        cursor = start + max(1, consumed)
        if isinstance(value, dict):
            yield value


def _iter_dicts(value: Any):
    normalized = _jsonable(value)
    if isinstance(normalized, dict):
        yield normalized
        for child in normalized.values():
            yield from _iter_dicts(child)
    elif isinstance(normalized, list):
        for child in normalized:
            yield from _iter_dicts(child)
    elif isinstance(normalized, str):
        for parsed in _embedded_json_objects(normalized):
            yield parsed
            yield from _iter_dicts(parsed)


def _normalize_refs(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        source = (value,)
    elif isinstance(value, (list, tuple, set)):
        source = value
    else:
        source = ()
    return tuple(dict.fromkeys(
        str(item).strip()
        for item in source
        if str(item).strip()
    ))


def _validated_request_id(value: Any) -> str:
    request_id = str(value or "").strip()
    if not _REQUEST_ID_RE.fullmatch(request_id):
        raise AgentToolRequestError("TOOL_REQUEST_INVALID_REQUEST_ID")
    return request_id


def _validated_arguments(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise AgentToolRequestError("TOOL_REQUEST_ARGUMENTS_MUST_BE_OBJECT")
    arguments = _jsonable(value)
    if any(str(key).casefold() in _FORBIDDEN_ARGUMENT_KEYS for key in arguments):
        raise AgentToolAuthorizationError("TOOL_REQUEST_ARGUMENT_AUTHORITY_OVERRIDE")
    return dict(arguments)


@dataclass(frozen=True)
class ToolRequestEnvelope:
    schema: str
    request_id: str
    mission_id: str
    task_id: str
    agent_id: str
    capability_id: str
    tool_or_capability_id: str
    operation: str
    arguments: dict[str, Any]
    input_refs: tuple[str, ...]
    reason: str
    authorization_context: dict[str, Any]
    source_format: str = "CANONICAL"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["input_refs"] = list(self.input_refs)
        return payload


@dataclass(frozen=True)
class ToolResultEnvelope:
    schema: str
    request_id: str
    mission_id: str
    task_id: str
    tool_id: str
    operation: str
    authorization_id: str
    input_refs: tuple[str, ...]
    output_refs: tuple[str, ...]
    content_sha256: str
    status: str
    started_at: str
    finished_at: str
    error: dict[str, Any] | None
    result_payload: Any
    content_truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["input_refs"] = list(self.input_refs)
        payload["output_refs"] = list(self.output_refs)
        return payload


def extract_tool_request(
    provider_result: Any,
    *,
    mission_id: str,
    task_id: str,
    agent_id: str,
    capability_id: str,
) -> ToolRequestEnvelope | None:
    for item in _iter_dicts(provider_result):
        schema = str(item.get("schema") or "").strip()
        if schema.startswith("ToolRequestEnvelope") and schema != TOOL_REQUEST_SCHEMA:
            raise AgentToolRequestError("TOOL_REQUEST_SCHEMA_UNSUPPORTED")
        if schema == TOOL_REQUEST_SCHEMA:
            required_identity = {
                "mission_id": mission_id,
                "task_id": task_id,
                "agent_id": agent_id,
                "capability_id": capability_id,
            }
            for key, expected in required_identity.items():
                if str(item.get(key) or "").strip() != str(expected):
                    raise AgentToolAuthorizationError(
                        f"TOOL_REQUEST_IDENTITY_MISMATCH:{key}"
                    )
            target = str(item.get("tool_or_capability_id") or "").strip()
            operation = str(item.get("operation") or "").strip().upper()
            reason = " ".join(str(item.get("reason") or "").split()).strip()
            auth_context = item.get("authorization_context")
            if not target:
                raise AgentToolRequestError("TOOL_REQUEST_TARGET_REQUIRED")
            if not operation:
                raise AgentToolRequestError("TOOL_REQUEST_OPERATION_REQUIRED")
            if not reason:
                raise AgentToolRequestError("TOOL_REQUEST_REASON_REQUIRED")
            if not isinstance(auth_context, dict):
                raise AgentToolRequestError(
                    "TOOL_REQUEST_AUTHORIZATION_CONTEXT_REQUIRED"
                )
            return ToolRequestEnvelope(
                schema=TOOL_REQUEST_SCHEMA,
                request_id=_validated_request_id(item.get("request_id")),
                mission_id=mission_id,
                task_id=task_id,
                agent_id=agent_id,
                capability_id=capability_id,
                tool_or_capability_id=target,
                operation=operation,
                arguments=_validated_arguments(item.get("arguments")),
                input_refs=_normalize_refs(item.get("input_refs")),
                reason=reason[:1200],
                authorization_context=_jsonable(auth_context),
                source_format="CANONICAL",
            )

        if str(item.get("tool") or "").strip() == "br_harness_capability_request":
            target = str(item.get("capability_id") or "").strip()
            if not target:
                raise AgentToolRequestError(
                    "LEGACY_TOOL_REQUEST_CAPABILITY_REQUIRED"
                )
            arguments = _validated_arguments(item.get("args"))
            refs = _normalize_refs(
                arguments.get("artifact_refs")
                or arguments.get("input_refs")
            )
            return ToolRequestEnvelope(
                schema=TOOL_REQUEST_SCHEMA,
                request_id=_validated_request_id(item.get("request_id")),
                mission_id=mission_id,
                task_id=task_id,
                agent_id=agent_id,
                capability_id=capability_id,
                tool_or_capability_id=target,
                operation="EXECUTE_CAPABILITY",
                arguments=arguments,
                input_refs=refs,
                reason="legacy structured Harness capability request",
                authorization_context={
                    "authority": "DEEPSEEK_HARNESS",
                    "source": "legacy-br-harness-capability-request",
                },
                source_format="LEGACY_STRUCTURED_CAPABILITY_REQUEST",
            )
    return None


def provider_call_count(provider_result: Any) -> int:
    observed = 0
    for item in _iter_dicts(provider_result):
        attempts = item.get("provider_attempts")
        if isinstance(attempts, list):
            observed = max(observed, len(attempts))
    return observed


def extract_agent_output_text(provider_result: Any, *, max_chars: int = 2400) -> str:
    normalized = _jsonable(provider_result)
    candidates: list[str] = []
    for item in _iter_dicts(normalized):
        value = item.get("output")
        if isinstance(value, str) and value.strip():
            candidates.append(value.strip())
    if not candidates:
        return ""
    return candidates[0][:max_chars]


def bounded_tool_result(value: Any) -> tuple[Any, str, bool]:
    normalized = _jsonable(value)
    raw = json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    digest = sha256(raw.encode("utf-8")).hexdigest()
    if len(raw) <= MAX_TOOL_RESULT_CHARS:
        return normalized, digest, False
    return {
        "truncated": True,
        "original_chars": len(raw),
        "excerpt": raw[:MAX_TOOL_RESULT_CHARS],
    }, digest, True


def build_tool_result_envelope(
    *,
    request: ToolRequestEnvelope,
    tool_id: str,
    operation: str,
    authorization_id: str,
    output_refs: tuple[str, ...],
    result_payload: Any,
    status: str,
    started_at: str,
    finished_at: str,
    error: dict[str, Any] | None = None,
) -> ToolResultEnvelope:
    bounded, digest, truncated = bounded_tool_result(result_payload)
    return ToolResultEnvelope(
        schema=TOOL_RESULT_SCHEMA,
        request_id=request.request_id,
        mission_id=request.mission_id,
        task_id=request.task_id,
        tool_id=tool_id,
        operation=operation,
        authorization_id=authorization_id,
        input_refs=request.input_refs,
        output_refs=output_refs,
        content_sha256=digest,
        status=str(status or "").upper(),
        started_at=started_at,
        finished_at=finished_at,
        error=_jsonable(error) if error else None,
        result_payload=bounded,
        content_truncated=truncated,
    )


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()
