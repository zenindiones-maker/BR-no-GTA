from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from typing import Any, Iterable, Mapping


CONFLICT_GRAPH_SCHEMA = "TaskConflictGraph/v1"
CONFLICT_EDGE_SCHEMA = "TaskConflictEdge/v1"
RESOURCE_LEASE_SCHEMA = "TaskResourceLease/v1"

_TERMINAL_STATES = frozenset({
    "COMPLETED",
    "FAILED",
    "CANCELLED",
    "BLOCKED",
    "REJECTED",
    "ESCALATION_REQUIRED",
})


def _canon(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def _texts(values: Any) -> tuple[str, ...]:
    return tuple(dict.fromkeys(
        str(item).strip()
        for item in (values or ())
        if str(item).strip()
    ))


def _task_value(task: Any, key: str, default: Any = None) -> Any:
    if isinstance(task, Mapping):
        return task.get(key, default)
    return getattr(task, key, default)


def _normalize_path(value: str) -> str:
    text = str(value or "").strip().replace("\\", "/")
    if not text:
        return ""
    if text.startswith(("artifact:", "state:", "runtime:", "external:")):
        return text
    text = text.strip("/")
    if any(part == ".." for part in text.split("/")):
        raise ValueError("task resource scope contains traversal")
    return f"repo:{text}" if text else ""


def _read_resources(task: Any) -> tuple[str, ...]:
    values: list[str] = []
    for raw in _texts(_task_value(task, "read_scope", ())):
        value = _normalize_path(raw)
        if value and value not in values:
            values.append(value)
    for raw in _texts(_task_value(task, "input_refs", ())):
        value = raw if ":" in raw else f"artifact:{raw}"
        value = f"input:{value}"
        if value not in values:
            values.append(value)
    return tuple(sorted(values))


def _write_resources(task: Any) -> tuple[str, ...]:
    values: list[str] = []
    for raw in _texts(_task_value(task, "write_scope", ())):
        value = _normalize_path(raw)
        if value and value not in values:
            values.append(value)
    return tuple(sorted(values))


def _side_effect_resources(task: Any) -> tuple[str, ...]:
    return tuple(sorted(
        f"side-effect:{value}"
        for value in _texts(_task_value(task, "allowed_side_effects", ()))
    ))


def _namespace(value: str) -> str:
    return value.split(":", 1)[0] if ":" in value else ""


def _body(value: str) -> str:
    return value.split(":", 1)[1] if ":" in value else value


def _overlap(left: str, right: str) -> bool:
    if left == right:
        return True
    if _namespace(left) != _namespace(right):
        return False
    namespace = _namespace(left)
    if namespace in {"side-effect", "input"}:
        return False
    a = _body(left).rstrip("/")
    b = _body(right).rstrip("/")
    return bool(a and b and (a.startswith(b + "/") or b.startswith(a + "/")))


def _reaches(
    dependencies: Mapping[str, set[str]],
    *,
    source: str,
    target: str,
) -> bool:
    stack = list(dependencies.get(source, set()))
    seen: set[str] = set()
    while stack:
        item = stack.pop()
        if item == target:
            return True
        if item in seen:
            continue
        seen.add(item)
        stack.extend(dependencies.get(item, set()))
    return False


def _topological_levels(
    dependencies: Mapping[str, set[str]],
) -> tuple[tuple[str, ...], ...]:
    known = set(dependencies)
    remaining = set(known)
    resolved: set[str] = set()
    levels: list[tuple[str, ...]] = []
    while remaining:
        ready = tuple(sorted(
            task_id
            for task_id in remaining
            if dependencies[task_id] <= resolved
        ))
        if not ready:
            raise ValueError("task conflict graph contains a dependency cycle")
        levels.append(ready)
        resolved.update(ready)
        remaining.difference_update(ready)
    return tuple(levels)


@dataclass(frozen=True)
class TaskConflictEdge:
    before_task_id: str
    after_task_id: str
    conflict_type: str
    resource: str
    reason: str
    schema: str = CONFLICT_EDGE_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TaskConflictGraph:
    mission_id: str
    edges: tuple[TaskConflictEdge, ...]
    augmented_dependencies: dict[str, tuple[str, ...]]
    execution_levels: tuple[tuple[str, ...], ...]
    lock_order_by_task: dict[str, tuple[str, ...]]
    authority: str
    content_sha256: str
    schema: str = CONFLICT_GRAPH_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "mission_id": self.mission_id,
            "edges": [edge.to_dict() for edge in self.edges],
            "augmented_dependencies": {
                key: list(value)
                for key, value in sorted(
                    self.augmented_dependencies.items()
                )
            },
            "execution_levels": [
                list(level) for level in self.execution_levels
            ],
            "lock_order_by_task": {
                key: list(value)
                for key, value in sorted(
                    self.lock_order_by_task.items()
                )
            },
            "authority": self.authority,
            "content_sha256": self.content_sha256,
        }


def build_task_conflict_graph(
    *,
    mission_id: str,
    tasks: Iterable[Any],
) -> TaskConflictGraph:
    mission_id = str(mission_id or "").strip()
    rows = tuple(tasks)
    if not mission_id:
        raise ValueError("TaskConflictGraph requires mission_id")
    by_id = {
        str(_task_value(task, "task_id") or "").strip(): task
        for task in rows
    }
    if not by_id or "" in by_id or len(by_id) != len(rows):
        raise ValueError("TaskConflictGraph requires unique task_id values")

    dependencies: dict[str, set[str]] = {}
    for task_id, task in by_id.items():
        deps = set(_texts(_task_value(task, "dependencies", ())))
        unknown = deps - set(by_id)
        if unknown:
            raise ValueError(
                f"unknown dependencies for {task_id}: {sorted(unknown)}"
            )
        if task_id in deps:
            raise ValueError("task cannot depend on itself")
        dependencies[task_id] = deps

    # Validate the original graph before introducing deterministic conflict
    # edges. This distinguishes caller cycles from scheduler decisions.
    _topological_levels(dependencies)

    resources = {
        task_id: {
            "read": _read_resources(task),
            "write": _write_resources(task),
            "side_effect": _side_effect_resources(task),
        }
        for task_id, task in by_id.items()
    }

    edges: list[TaskConflictEdge] = []
    ids = tuple(sorted(by_id))
    for index, left_id in enumerate(ids):
        for right_id in ids[index + 1:]:
            left = resources[left_id]
            right = resources[right_id]
            conflicts: list[tuple[str, str]] = []

            for resource in left["write"]:
                for candidate in right["write"]:
                    if _overlap(resource, candidate):
                        conflicts.append(("WRITE_WRITE", resource))
                for candidate in right["read"]:
                    if _overlap(resource, candidate):
                        conflicts.append(("WRITE_READ", resource))
            for resource in right["write"]:
                for candidate in left["read"]:
                    if _overlap(resource, candidate):
                        conflicts.append(("READ_WRITE", resource))
            for resource in left["side_effect"]:
                if resource in set(right["side_effect"]):
                    conflicts.append(("SIDE_EFFECT", resource))

            if not conflicts:
                continue

            # Respect existing dependency direction. Otherwise orient the edge
            # by stable task_id order so every replay produces the same DAG.
            if _reaches(dependencies, source=right_id, target=left_id):
                before, after = left_id, right_id
            elif _reaches(dependencies, source=left_id, target=right_id):
                before, after = right_id, left_id
            else:
                before, after = left_id, right_id

            for conflict_type, resource in sorted(set(conflicts)):
                edges.append(TaskConflictEdge(
                    before_task_id=before,
                    after_task_id=after,
                    conflict_type=conflict_type,
                    resource=resource,
                    reason=(
                        "deterministic resource conflict serialization"
                    ),
                ))
            dependencies[after].add(before)

    execution_levels = _topological_levels(dependencies)
    lock_order_by_task = {
        task_id: tuple(sorted(set(
            resources[task_id]["write"]
            + resources[task_id]["side_effect"]
        )))
        for task_id in sorted(by_id)
    }
    logical = {
        "schema": CONFLICT_GRAPH_SCHEMA,
        "mission_id": mission_id,
        "edges": [edge.to_dict() for edge in edges],
        "augmented_dependencies": {
            task_id: sorted(values)
            for task_id, values in sorted(dependencies.items())
        },
        "execution_levels": [list(level) for level in execution_levels],
        "lock_order_by_task": {
            task_id: list(values)
            for task_id, values in lock_order_by_task.items()
        },
        "authority": "DEEPSEEK_HARNESS",
    }
    return TaskConflictGraph(
        mission_id=mission_id,
        edges=tuple(edges),
        augmented_dependencies={
            task_id: tuple(sorted(values))
            for task_id, values in sorted(dependencies.items())
        },
        execution_levels=execution_levels,
        lock_order_by_task=lock_order_by_task,
        authority="DEEPSEEK_HARNESS",
        content_sha256=sha256(_canon(logical)).hexdigest(),
    )


class TaskResourceLockConflict(RuntimeError):
    pass


class TaskResourceLockLedger:
    """Mission-local lock ledger used as defense in depth after DAG analysis.

    Conflict edges are the primary scheduling mechanism. The ledger prevents
    an executor from violating the planned serialization and is deliberately
    deterministic: all resources are acquired in sorted order.
    """

    def __init__(self) -> None:
        self._leases: dict[str, dict[str, Any]] = {}

    @staticmethod
    def _now(value: datetime | None) -> datetime:
        return value or datetime.now(timezone.utc)

    def acquire(
        self,
        *,
        mission_id: str,
        task_id: str,
        resources: Iterable[str],
        now: datetime | None = None,
        ttl_seconds: int = 300,
        max_stale_recoveries: int = 16,
    ) -> dict[str, Any]:
        now = self._now(now)
        if ttl_seconds <= 0 or max_stale_recoveries < 0:
            raise ValueError("invalid task resource lock policy")
        ordered = tuple(sorted(dict.fromkeys(
            str(item).strip()
            for item in resources
            if str(item).strip()
        )))
        recovered = 0
        for resource in ordered:
            lease = self._leases.get(resource)
            if lease is None:
                continue
            expires = datetime.fromisoformat(
                str(lease["expires_at"]).replace("Z", "+00:00")
            )
            if expires <= now and recovered < max_stale_recoveries:
                self._leases.pop(resource, None)
                recovered += 1

        blocked = [
            resource
            for resource in ordered
            if resource in self._leases
            and self._leases[resource]["task_id"] != task_id
        ]
        if blocked:
            raise TaskResourceLockConflict(
                "TASK_RESOURCE_LOCK_CONFLICT:"
                + ",".join(blocked)
            )

        expires_at = now + timedelta(seconds=ttl_seconds)
        lease_id = "task-resource-lock:" + sha256(_canon({
            "mission_id": mission_id,
            "task_id": task_id,
            "resources": list(ordered),
        })).hexdigest()
        payload = {
            "schema": RESOURCE_LEASE_SCHEMA,
            "lease_id": lease_id,
            "mission_id": str(mission_id),
            "task_id": str(task_id),
            "resources": list(ordered),
            "acquisition_order": list(ordered),
            "acquired_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
            "stale_leases_recovered": recovered,
            "status": "ACTIVE",
            "authority": "DEEPSEEK_HARNESS",
        }
        for resource in ordered:
            self._leases[resource] = dict(payload)
        return payload

    def release(
        self,
        *,
        task_id: str,
        terminal_state: str,
    ) -> dict[str, Any]:
        state = str(terminal_state or "").strip().upper()
        if state not in _TERMINAL_STATES:
            raise ValueError("resource lock release requires terminal state")
        released = sorted(
            resource
            for resource, lease in self._leases.items()
            if lease["task_id"] == task_id
        )
        for resource in released:
            self._leases.pop(resource, None)
        return {
            "schema": "TaskResourceLockRelease/v1",
            "task_id": str(task_id),
            "terminal_state": state,
            "released_resources": released,
            "authority": "DEEPSEEK_HARNESS",
        }

    def snapshot(self) -> dict[str, Any]:
        return {
            resource: dict(lease)
            for resource, lease in sorted(self._leases.items())
        }
