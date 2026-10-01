from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from typing import Any


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()


@dataclass(frozen=True)
class AgentExecutionTrace:
    mission_ref: str
    task_ref: str
    blueprint_ref: str
    worker_ref: str
    environment_ref: str
    codex_session_ref: str
    skill_refs: tuple[str, ...]
    tool_calls: tuple[dict[str, str], ...]
    artifact_refs: tuple[str, ...]
    review_ref: str
    result_ref: str
    reducer_ref: str
    gen_ai_agent_id: str
    gen_ai_operation_name: str
    request_model: str
    response_model: str
    usage: dict[str, int]
    causal_chain: tuple[str, ...]
    content_sha256: str
    authority: str = "DEEPSEEK_HARNESS"
    schema: str = "AgentExecutionTrace/v1"

    @classmethod
    def create(cls, **raw: Any) -> "AgentExecutionTrace":
        tools = tuple(
            {
                "gen_ai.tool.call.id": str(item["gen_ai.tool.call.id"]),
                "gen_ai.tool.name": str(item["gen_ai.tool.name"]),
            }
            for item in raw.get("tool_calls", ())
        )
        chain = (
            str(raw["mission_ref"]),
            str(raw["task_ref"]),
            str(raw["blueprint_ref"]),
            str(raw["worker_ref"]),
            str(raw["environment_ref"]),
            str(raw["codex_session_ref"]),
            *(str(x) for x in raw.get("skill_refs", ())),
            *(item["gen_ai.tool.call.id"] for item in tools),
            *(str(x) for x in raw.get("artifact_refs", ())),
            str(raw["review_ref"]),
            str(raw["result_ref"]),
            str(raw["reducer_ref"]),
        )
        base = {
            "mission_ref": str(raw["mission_ref"]),
            "task_ref": str(raw["task_ref"]),
            "blueprint_ref": str(raw["blueprint_ref"]),
            "worker_ref": str(raw["worker_ref"]),
            "environment_ref": str(raw["environment_ref"]),
            "codex_session_ref": str(raw["codex_session_ref"]),
            "skill_refs": tuple(str(x) for x in raw.get("skill_refs", ())),
            "tool_calls": tools,
            "artifact_refs": tuple(str(x) for x in raw.get("artifact_refs", ())),
            "review_ref": str(raw["review_ref"]),
            "result_ref": str(raw["result_ref"]),
            "reducer_ref": str(raw["reducer_ref"]),
            "gen_ai_agent_id": str(raw["gen_ai_agent_id"]),
            "gen_ai_operation_name": str(raw["gen_ai_operation_name"]),
            "request_model": str(raw["request_model"]),
            "response_model": str(raw["response_model"]),
            "usage": {str(k): int(v) for k, v in dict(raw.get("usage", {})).items()},
            "causal_chain": chain,
            "authority": "DEEPSEEK_HARNESS",
            "schema": "AgentExecutionTrace/v1",
        }
        return cls(
            **{k: v for k, v in base.items() if k not in {"authority", "schema"}},
            content_sha256=sha256(_canonical(base)).hexdigest(),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
