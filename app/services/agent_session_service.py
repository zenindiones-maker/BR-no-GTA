from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any


AGENT_SESSION_SCHEMA = "AgentSession/v1"
AGENT_OWNED_EXECUTION_KINDS = frozenset({
    "SEMANTIC_REASONER",
    "DETERMINISTIC_ANALYSIS_AGENT",
    "INDEPENDENT_REVIEWER",
})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_agent_instance_id(
    *,
    mission_id: str,
    task_id: str,
    capability_id: str,
    agent_id: str,
    skill_id: str | None,
) -> str:
    raw = "|".join([
        str(mission_id),
        str(task_id),
        str(capability_id),
        str(agent_id),
        str(skill_id or ""),
    ])
    return "agent-" + sha256(raw.encode("utf-8")).hexdigest()[:24]


def _unique_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        raw = json.dumps(
            row,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        key = sha256(raw.encode("utf-8")).hexdigest()
        if key in seen:
            continue
        seen.add(key)
        out.append(dict(row))
    return out


class AgentSessionRuntime:
    def __init__(
        self,
        *,
        artifact_dir: str | Path,
        mission_id: str,
        task_id: str,
        capability_id: str,
        agent_id: str,
        skill_id: str | None,
        functional_role: str,
        execution_kind: str,
        allowed_tools: tuple[str, ...],
        input_artifact_refs: tuple[str, ...],
        max_agent_turns: int,
        max_tool_calls: int,
        max_provider_calls: int,
        max_context_chars: int,
        max_wall_clock_seconds: float,
        mandatory_tool_requirements: tuple[str, ...] = (),
    ) -> None:
        self.root = Path(artifact_dir)
        self.dir = self.root / "agent-sessions"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.agent_instance_id = _stable_agent_instance_id(
            mission_id=mission_id,
            task_id=task_id,
            capability_id=capability_id,
            agent_id=agent_id,
            skill_id=skill_id,
        )
        self.path = self.dir / f"{task_id}-{self.agent_instance_id}.json"
        checkpoint_ref = (
            "artifact:agent-sessions/" + self.path.name
        )
        initial = {
            "schema": AGENT_SESSION_SCHEMA,
            "AGENT_INSTANCE_ID": self.agent_instance_id,
            "MISSION_ID": mission_id,
            "TASK_ID": task_id,
            "CAPABILITY_ID": capability_id,
            "AGENT_ID": agent_id,
            "SKILL_ID": skill_id,
            "FUNCTIONAL_ROLE": str(functional_role or "GENERAL").upper(),
            "EXECUTION_KIND": str(execution_kind or "").upper(),
            "PROVIDER_ID": None,
            "MODEL_ID": None,
            "ALLOWED_TOOLS": list(allowed_tools),
            "TOOLS_AVAILABLE": list(allowed_tools),
            "MANDATORY_TOOL_REQUIREMENTS": list(
                mandatory_tool_requirements
            ),
            "INPUT_ARTIFACT_REFS": list(input_artifact_refs),
            "OUTPUT_ARTIFACT_REFS": [],
            "TURN_INDEX": 0,
            "MAX_AGENT_TURNS": int(max_agent_turns),
            "MAX_TOOL_CALLS": int(max_tool_calls),
            "MAX_PROVIDER_CALLS": int(max_provider_calls),
            "MAX_CONTEXT": int(max_context_chars),
            "MAX_WALL_CLOCK_SECONDS": float(max_wall_clock_seconds),
            "CHECKPOINT_REF": checkpoint_ref,
            "STATUS": "READY",
            "TOOL_REQUESTS": [],
            "TOOL_EXECUTIONS": [],
            "TOOL_RESULTS_CONSUMED": [],
            "PROVIDER_ATTEMPTS": [],
            "FINAL_OUTPUT_SCHEMA": None,
            "FINAL_OUTPUT_VALID": False,
            "created_at": _now(),
            "updated_at": _now(),
        }
        if self.path.is_file():
            try:
                loaded = json.loads(
                    self.path.read_text(encoding="utf-8")
                )
            except (OSError, json.JSONDecodeError):
                loaded = {}
            if (
                loaded.get("schema") == AGENT_SESSION_SCHEMA
                and loaded.get("AGENT_INSTANCE_ID")
                == self.agent_instance_id
                and loaded.get("MISSION_ID") == mission_id
                and loaded.get("TASK_ID") == task_id
            ):
                initial.update(loaded)
        self.state = initial
        self._persist()

    def _persist(self) -> None:
        self.state["updated_at"] = _now()
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(
                self.state,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
                default=str,
            ) + "\n",
            encoding="utf-8",
        )
        tmp.replace(self.path)

    def begin_turn(self, turn_index: int) -> None:
        self.state["TURN_INDEX"] = int(turn_index)
        self.state["STATUS"] = "RUNNING"
        self._persist()

    def record_provider_result(self, result: Any) -> None:
        rows: list[dict[str, Any]] = []
        stack = [result]
        while stack:
            value = stack.pop()
            if hasattr(value, "to_dict") and callable(value.to_dict):
                value = value.to_dict()
            if isinstance(value, dict):
                attempts = value.get("provider_attempts")
                if isinstance(attempts, list):
                    rows.extend(
                        dict(item)
                        for item in attempts
                        if isinstance(item, dict)
                    )
                stack.extend(value.values())
            elif isinstance(value, (list, tuple)):
                stack.extend(value)
        if rows:
            self.state["PROVIDER_ATTEMPTS"] = _unique_rows([
                *list(self.state.get("PROVIDER_ATTEMPTS") or ()),
                *rows,
            ])
            last = rows[-1]
            self.state["PROVIDER_ID"] = str(
                last.get("provider_id")
                or last.get("provider")
                or ""
            ) or self.state.get("PROVIDER_ID")
            self.state["MODEL_ID"] = str(
                last.get("model_id")
                or last.get("model")
                or ""
            ) or self.state.get("MODEL_ID")
            self._persist()

    def record_tool_request(self, request: dict[str, Any]) -> None:
        self.state["STATUS"] = "WAITING_TOOL"
        self.state["TOOL_REQUESTS"] = _unique_rows([
            *list(self.state.get("TOOL_REQUESTS") or ()),
            dict(request),
        ])
        self._persist()

    def record_tool_result(self, result: dict[str, Any]) -> None:
        row = dict(result)
        self.state["TOOL_EXECUTIONS"] = _unique_rows([
            *list(self.state.get("TOOL_EXECUTIONS") or ()),
            {
                "request_id": row.get("request_id"),
                "tool_id": row.get("tool_id"),
                "operation": row.get("operation"),
                "authorization_id": row.get("authorization_id"),
                "status": row.get("status"),
                "output_refs": list(row.get("output_refs") or ()),
                "content_sha256": row.get("content_sha256"),
            },
        ])
        self._persist()

    def mark_tool_results_consumed(
        self,
        results: list[dict[str, Any]],
    ) -> None:
        consumed = [
            {
                "request_id": row.get("request_id"),
                "tool_id": row.get("tool_id"),
                "content_sha256": row.get("content_sha256"),
                "output_refs": list(row.get("output_refs") or ()),
            }
            for row in results
            if isinstance(row, dict)
        ]
        self.state["TOOL_RESULTS_CONSUMED"] = _unique_rows([
            *list(self.state.get("TOOL_RESULTS_CONSUMED") or ()),
            *consumed,
        ])
        self._persist()

    def complete(
        self,
        *,
        final_output_schema: str | None,
        output_artifact_ref: str,
        tool_results: list[dict[str, Any]],
    ) -> None:
        if tool_results:
            self.mark_tool_results_consumed(tool_results)
        outputs = list(self.state.get("OUTPUT_ARTIFACT_REFS") or ())
        if output_artifact_ref and output_artifact_ref not in outputs:
            outputs.append(output_artifact_ref)
        self.state["OUTPUT_ARTIFACT_REFS"] = outputs
        self.state["FINAL_OUTPUT_SCHEMA"] = final_output_schema
        self.state["FINAL_OUTPUT_VALID"] = True
        self.state["STATUS"] = "COMPLETED"
        self._persist()

    def fail(
        self,
        *,
        failure_class: str,
        evidence: dict[str, Any] | None = None,
    ) -> None:
        self.state["STATUS"] = "FAILED"
        self.state["FAILURE_CLASS"] = str(failure_class)
        if evidence:
            self.state["FAILURE_EVIDENCE"] = dict(evidence)
        self._persist()

    def snapshot(self) -> dict[str, Any]:
        return json.loads(json.dumps(self.state, default=str))

    @property
    def artifact_ref(self) -> str:
        return str(self.state["CHECKPOINT_REF"])
