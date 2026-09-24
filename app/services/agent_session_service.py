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
        self.restored = False
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
                and loaded.get("CAPABILITY_ID") == capability_id
                and loaded.get("AGENT_ID") == agent_id
            ):
                initial.update(loaded)
                self.restored = True
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

    def reserve_turn_window(
        self,
        *,
        default_max_agent_turns: int,
        max_resume_agent_turns: int,
        max_resume_segments: int,
        max_total_agent_turns: int,
    ) -> dict[str, Any]:
        current = int(self.state.get("TURN_INDEX") or 0)
        if not self.restored:
            return {
                "start_turn": 1,
                "end_turn": int(default_max_agent_turns),
                "resume": False,
                "resume_segment": 0,
                "historical_turns": current,
                "AGENT_RESUME_BUDGET_BOUNDED": True,
                "AGENT_RESUME_BUDGET_NOT_RESET_BLINDLY": True,
            }

        used = int(self.state.get("RESUME_SEGMENTS_USED") or 0)

        # A restored session may have reached the global turn bound only
        # because its latest provider attempt failed before producing a valid
        # AgentTurn/final output. Preserve that failed attempt as exhausted
        # routing evidence, but do not let the terminal budget state masquerade
        # as a completed agent interaction. Reclaim exactly one failed terminal
        # provider turn; the total bound itself remains unchanged.
        if (
            current >= int(max_total_agent_turns)
            and str(self.state.get("STATUS") or "").upper() == "FAILED"
            and self.state.get("FINAL_OUTPUT_VALID") is not True
            and self.state.get("FAILURE_TURN_CONSUMED") is True
        ):
            current -= 1
            self.state["TURN_INDEX"] = current
            self.state["FAILURE_TURN_CONSUMED"] = False
            if used > 0:
                used -= 1
                self.state["RESUME_SEGMENTS_USED"] = used
            self.state["FAILED_TERMINAL_PROVIDER_TURN_RECLAIMED"] = "PASS"
            self.state["FAILED_TERMINAL_PROVIDER_TURN_RECLAIMED_COUNT"] = (
                int(
                    self.state.get(
                        "FAILED_TERMINAL_PROVIDER_TURN_RECLAIMED_COUNT"
                    ) or 0
                )
                + 1
            )
            self._persist()

        if used >= int(max_resume_segments) or current >= int(
            max_total_agent_turns
        ):
            return {
                "start_turn": current + 1,
                "end_turn": current,
                "resume": True,
                "resume_segment": used,
                "historical_turns": current,
                "AGENT_RESUME_BUDGET_BOUNDED": True,
                "AGENT_RESUME_BUDGET_NOT_RESET_BLINDLY": True,
                "exhausted": True,
            }

        used += 1
        start_turn = current + 1
        end_turn = min(
            current + int(max_resume_agent_turns),
            int(max_total_agent_turns),
        )
        self.state["RESUME_SEGMENTS_USED"] = used
        self.state["MAX_RESUME_SEGMENTS"] = int(max_resume_segments)
        self.state["MAX_RESUME_AGENT_TURNS"] = int(
            max_resume_agent_turns
        )
        self.state["MAX_TOTAL_AGENT_TURNS"] = int(
            max_total_agent_turns
        )
        self.state["ACTIVE_RESUME_TURN_START"] = start_turn
        self.state["ACTIVE_RESUME_TURN_END"] = end_turn
        self._persist()
        return {
            "start_turn": start_turn,
            "end_turn": end_turn,
            "resume": True,
            "resume_segment": used,
            "historical_turns": current,
            "AGENT_RESUME_BUDGET_BOUNDED": True,
            "AGENT_RESUME_BUDGET_NOT_RESET_BLINDLY": True,
            "exhausted": False,
        }

    def _release_unconsumed_resume_segment(self) -> bool:
        active_start = self.state.get("ACTIVE_RESUME_TURN_START")
        active_end = self.state.get("ACTIVE_RESUME_TURN_END")
        used = int(self.state.get("RESUME_SEGMENTS_USED") or 0)
        if active_start is None or active_end is None or used <= 0:
            return False
        self.state["RESUME_SEGMENTS_USED"] = used - 1
        self.state["ACTIVE_RESUME_TURN_START"] = None
        self.state["ACTIVE_RESUME_TURN_END"] = None
        self.state["PRE_PROVIDER_SEGMENT_RECLAIMED_COUNT"] = (
            int(
                self.state.get(
                    "PRE_PROVIDER_SEGMENT_RECLAIMED_COUNT"
                ) or 0
            )
            + 1
        )
        return True

    def reclaim_unexecuted_pre_provider_turn(self) -> bool:
        if not self.restored:
            return False
        status = str(self.state.get("STATUS") or "").upper()
        failure_class = str(self.state.get("FAILURE_CLASS") or "")
        # A provider-routing exception can occur after begin_turn() persisted
        # RUNNING but before the broker persisted a terminal FAILED state.
        # Treat that checkpoint as interrupted recovery only when it still
        # carries a typed failure, no valid final output, and an explicitly
        # unconsumed provider turn.
        interrupted_recovery = bool(
            status == "RUNNING"
            and failure_class
            and not bool(self.state.get("FINAL_OUTPUT_VALID"))
            and self.state.get("FAILURE_TURN_CONSUMED") is False
        )
        if status != "FAILED" and not interrupted_recovery:
            return False
        provider_recovery = self.provider_recovery_state()
        has_failed_provider_history = bool(
            provider_recovery.get("EXHAUSTED_PROVIDER_MODEL_PAIRS")
        )
        causal_budget_exhaustion = bool(
            failure_class == "AgentToolBudgetExceeded"
            and has_failed_provider_history
            and not bool(self.state.get("FINAL_OUTPUT_VALID"))
        )
        if failure_class != "RoutingPolicyError" and not causal_budget_exhaustion:
            return False

        consumed = self.state.get("FAILURE_TURN_CONSUMED")
        if consumed is True:
            return False

        changed = False
        if consumed is None:
            current = int(self.state.get("TURN_INDEX") or 0)
            if current > 0:
                self.state["TURN_INDEX"] = current - 1
                changed = True
            # Legacy checkpoints predate ACTIVE_RESUME_TURN_* but their
            # RoutingPolicyError path incremented RESUME_SEGMENTS_USED before
            # the provider boundary. Reclaim exactly one paired segment.
            used = int(self.state.get("RESUME_SEGMENTS_USED") or 0)
            if used > 0:
                self.state["RESUME_SEGMENTS_USED"] = used - 1
                self.state["PRE_PROVIDER_SEGMENT_RECLAIMED_COUNT"] = (
                    int(
                        self.state.get(
                            "PRE_PROVIDER_SEGMENT_RECLAIMED_COUNT"
                        ) or 0
                    )
                    + 1
                )
                changed = True
        elif self._release_unconsumed_resume_segment():
            changed = True
        elif consumed is False and (causal_budget_exhaustion or interrupted_recovery):
            # The terminal budget check happened before a new provider call,
            # after the previous recovery turn had already persisted its
            # provider failure. Reclaim exactly that unconsumed recovery turn
            # and paired segment; bounds remain unchanged.
            current = int(self.state.get("TURN_INDEX") or 0)
            if current > 0:
                self.state["TURN_INDEX"] = current - 1
                changed = True
            used = int(self.state.get("RESUME_SEGMENTS_USED") or 0)
            if used > 0:
                self.state["RESUME_SEGMENTS_USED"] = used - 1
                self.state["PRE_PROVIDER_SEGMENT_RECLAIMED_COUNT"] = (
                    int(self.state.get("PRE_PROVIDER_SEGMENT_RECLAIMED_COUNT") or 0)
                    + 1
                )
                changed = True

        if not changed:
            return False

        self.state["FAILURE_TURN_CONSUMED"] = False
        self.state["PRE_PROVIDER_TURN_RECLAIMED"] = "PASS"
        self.state["PRE_PROVIDER_TURN_RECLAIMED_COUNT"] = (
            int(self.state.get("PRE_PROVIDER_TURN_RECLAIMED_COUNT") or 0)
            + (1 if consumed is None else 0)
        )
        self._persist()
        return True

    def begin_turn(self, turn_index: int) -> None:
        self.state["TURN_INDEX"] = int(turn_index)
        self.state["STATUS"] = "RUNNING"
        self.state["ACTIVE_RESUME_TURN_START"] = None
        self.state["ACTIVE_RESUME_TURN_END"] = None
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
        turn_consumed: bool | None = None,
    ) -> None:
        if evidence:
            self.record_provider_result(evidence)
        self.state["STATUS"] = "FAILED"
        self.state["FAILURE_CLASS"] = str(failure_class)
        if turn_consumed is not None:
            self.state["FAILURE_TURN_CONSUMED"] = bool(turn_consumed)
            if turn_consumed is False:
                self._release_unconsumed_resume_segment()
        if evidence:
            self.state["FAILURE_EVIDENCE"] = dict(evidence)
        self._persist()

    def provider_recovery_state(self) -> dict[str, Any]:
        def walk(value: Any):
            if isinstance(value, dict):
                yield value
                for child in value.values():
                    yield from walk(child)
            elif isinstance(value, (list, tuple)):
                for child in value:
                    yield from walk(child)

        attempted: list[dict[str, Any]] = []
        exhausted: list[dict[str, Any]] = []
        attempts: list[dict[str, Any]] = []
        for node in walk(self.state):
            for item in node.get("provider_attempts") or ():
                if isinstance(item, dict):
                    attempts.append(dict(item))
            for item in (
                node.get("ATTEMPTED_PROVIDER_MODEL_PAIRS")
                or node.get("attempted_provider_model_pairs")
                or ()
            ):
                if isinstance(item, dict):
                    attempted.append(dict(item))
            for item in (
                node.get("EXHAUSTED_PROVIDER_MODEL_PAIRS")
                or node.get("exhausted_provider_model_pairs")
                or ()
            ):
                if isinstance(item, dict):
                    exhausted.append(dict(item))

        def normalized_pair(item: dict[str, Any]) -> dict[str, Any] | None:
            provider_id = str(
                item.get("provider_id") or item.get("provider") or ""
            ).strip()
            model_id = str(
                item.get("model_id") or item.get("model") or ""
            ).strip()
            if not provider_id or not model_id:
                return None
            return {
                "provider_id": provider_id,
                "model_id": model_id,
                "routing_id": str(item.get("routing_id") or "").strip(),
                "attempt_id": str(item.get("attempt_id") or "").strip(),
                "failure_class": str(
                    item.get("failure_class") or ""
                ).strip(),
                "status": str(item.get("status") or "").strip().upper(),
            }

        attempted.extend(
            row for row in (
                normalized_pair(item) for item in attempts
            )
            if row is not None
        )
        exhausted.extend(
            row for row in (
                normalized_pair(item)
                for item in attempts
                if str(item.get("status") or "").strip().upper() == "FAILED"
            )
            if row is not None
        )

        def unique_pairs(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
            seen: set[tuple[str, str, str]] = set()
            out: list[dict[str, Any]] = []
            for item in rows:
                row = normalized_pair(item)
                if row is None:
                    continue
                key = (
                    row["provider_id"],
                    row["model_id"],
                    row["routing_id"],
                )
                if key in seen:
                    continue
                seen.add(key)
                out.append(row)
            return out

        attempted = unique_pairs(attempted)
        exhausted = unique_pairs(exhausted)
        attempted_routes = list(dict.fromkeys(
            row["routing_id"]
            for row in attempted
            if row["routing_id"]
        ))
        full_timeout = any(
            row.get("failure_class") == "TRANSIENT_PROVIDER_TIMEOUT"
            for row in exhausted
        )
        previous = exhausted[-1] if exhausted else (
            attempted[-1] if attempted else {}
        )
        attempt_ids = {
            str(item.get("attempt_id") or "").strip()
            for item in attempts
            if str(item.get("attempt_id") or "").strip()
        }
        provider_call_count = (
            len(attempt_ids)
            if attempt_ids
            else len(attempts)
        )
        return {
            "ATTEMPTED_PROVIDER_MODEL_PAIRS": attempted,
            "EXHAUSTED_PROVIDER_MODEL_PAIRS": exhausted,
            "ATTEMPTED_ROUTING_IDS": attempted_routes,
            "PREVIOUS_SELECTED_PROVIDER": previous.get("provider_id"),
            "PREVIOUS_SELECTED_MODEL": previous.get("model_id"),
            "SAME_MODEL_FULL_TIMEOUT_RETRY": (
                "FORBIDDEN" if full_timeout else None
            ),
            "RECOVERY_STRATEGY": (
                "LOCALIZED_PROVIDER_REPLAN" if exhausted else None
            ),
            "PROVIDER_CALL_COUNT": provider_call_count,
            "FAILED_PROVIDER_ATTEMPTS_PERSISTED": bool(exhausted),
        }

    def prior_tool_results(self) -> list[dict[str, Any]]:
        requests = {
            str(item.get("request_id") or ""): dict(item)
            for item in (self.state.get("TOOL_REQUESTS") or ())
            if isinstance(item, dict)
            and str(item.get("request_id") or "")
        }
        rows: list[dict[str, Any]] = []
        root = self.root.resolve()
        for execution in self.state.get("TOOL_EXECUTIONS") or ():
            if not isinstance(execution, dict):
                continue
            request_id = str(execution.get("request_id") or "")
            request = requests.get(request_id)
            if request is None:
                continue
            for ref in execution.get("output_refs") or ():
                value = str(ref or "").strip()
                if not value.startswith("artifact:"):
                    continue
                path = (self.root / value.split(":", 1)[1].lstrip("/")).resolve()
                if path != root and root not in path.parents:
                    continue
                if not path.is_file():
                    continue
                try:
                    envelope = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if not isinstance(envelope, dict):
                    continue
                if envelope.get("schema") != "ToolResultEnvelope/v1":
                    continue
                if envelope.get("mission_id") != self.state.get("MISSION_ID"):
                    continue
                if envelope.get("task_id") != self.state.get("TASK_ID"):
                    continue
                expected_hash = str(
                    execution.get("content_sha256") or ""
                ).strip()
                if (
                    expected_hash
                    and str(envelope.get("content_sha256") or "").strip()
                    != expected_hash
                ):
                    continue
                rows.append({
                    "request": request,
                    "result": envelope,
                })
        return rows

    def snapshot(self) -> dict[str, Any]:
        return json.loads(json.dumps(self.state, default=str))

    @property
    def artifact_ref(self) -> str:
        return str(self.state["CHECKPOINT_REF"])
