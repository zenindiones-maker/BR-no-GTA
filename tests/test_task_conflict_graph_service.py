from datetime import datetime, timedelta, timezone

import pytest

from app.services.task_conflict_graph_service import (
    TaskResourceLockConflict,
    TaskResourceLockLedger,
    build_task_conflict_graph,
)


def _task(task_id, *, read=(), write=(), effects=(), deps=()):
    return {
        "task_id": task_id,
        "dependencies": list(deps),
        "read_scope": list(read),
        "write_scope": list(write),
        "allowed_side_effects": list(effects),
        "input_refs": [],
    }


def test_read_read_parallel_allowed():
    graph = build_task_conflict_graph(
        mission_id="m",
        tasks=[
            _task("a", read=("app/services",)),
            _task("b", read=("app/services",)),
        ],
    )
    assert graph.execution_levels == (("a", "b"),)
    assert graph.edges == ()


def test_read_write_serialized():
    graph = build_task_conflict_graph(
        mission_id="m",
        tasks=[
            _task("a", read=("app/services/x.py",)),
            _task("b", write=("app/services",)),
        ],
    )
    assert graph.execution_levels == (("a",), ("b",))
    assert any(
        edge.conflict_type == "READ_WRITE"
        for edge in graph.edges
    )


def test_write_write_serialized():
    graph = build_task_conflict_graph(
        mission_id="m",
        tasks=[
            _task("a", write=("app/services",)),
            _task("b", write=("app/services/x.py",)),
        ],
    )
    assert graph.execution_levels == (("a",), ("b",))
    assert any(
        edge.conflict_type == "WRITE_WRITE"
        for edge in graph.edges
    )


def test_disjoint_write_parallel_allowed():
    graph = build_task_conflict_graph(
        mission_id="m",
        tasks=[
            _task("a", write=("app/services/a.py",)),
            _task("b", write=("tests/test_b.py",)),
        ],
    )
    assert graph.execution_levels == (("a", "b"),)
    assert graph.edges == ()


def test_side_effect_conflict_is_serialized():
    graph = build_task_conflict_graph(
        mission_id="m",
        tasks=[
            _task("a", effects=("youtube-private-upload",)),
            _task("b", effects=("youtube-private-upload",)),
        ],
    )
    assert graph.execution_levels == (("a",), ("b",))
    assert graph.edges[0].conflict_type == "SIDE_EFFECT"


def test_conflict_graph_deterministic_under_input_reordering():
    tasks = [
        _task("c", write=("repo/c",)),
        _task("a", write=("repo/shared",)),
        _task("b", read=("repo/shared/file",)),
    ]
    one = build_task_conflict_graph(mission_id="m", tasks=tasks)
    two = build_task_conflict_graph(
        mission_id="m",
        tasks=list(reversed(tasks)),
    )
    assert one.content_sha256 == two.content_sha256
    assert one.to_dict() == two.to_dict()


def test_existing_dependency_direction_wins_over_lexical_order():
    graph = build_task_conflict_graph(
        mission_id="m",
        tasks=[
            _task("a", write=("shared",), deps=("z",)),
            _task("z", read=("shared",)),
        ],
    )
    assert graph.execution_levels == (("z",), ("a",))
    assert graph.augmented_dependencies["a"] == ("z",)


def test_lock_release_after_terminal_state():
    ledger = TaskResourceLockLedger()
    lease = ledger.acquire(
        mission_id="m",
        task_id="a",
        resources=("repo:b", "repo:a"),
        now=datetime(2026, 9, 27, tzinfo=timezone.utc),
    )
    assert lease["acquisition_order"] == ["repo:a", "repo:b"]
    assert ledger.snapshot()
    release = ledger.release(
        task_id="a",
        terminal_state="COMPLETED",
    )
    assert release["released_resources"] == ["repo:a", "repo:b"]
    assert ledger.snapshot() == {}


def test_stale_lease_recovery_bounded():
    ledger = TaskResourceLockLedger()
    start = datetime(2026, 9, 27, tzinfo=timezone.utc)
    ledger.acquire(
        mission_id="m",
        task_id="old",
        resources=("repo:a", "repo:b"),
        now=start,
        ttl_seconds=1,
    )
    with pytest.raises(TaskResourceLockConflict):
        ledger.acquire(
            mission_id="m",
            task_id="new",
            resources=("repo:a", "repo:b"),
            now=start + timedelta(seconds=2),
            max_stale_recoveries=1,
        )
    # One stale lock was recovered, one remains; no unbounded cleanup loop.
    assert len(ledger.snapshot()) == 1
    lease = ledger.acquire(
        mission_id="m",
        task_id="new",
        resources=("repo:a", "repo:b"),
        now=start + timedelta(seconds=2),
        max_stale_recoveries=2,
    )
    assert lease["stale_leases_recovered"] == 1
    assert set(ledger.snapshot()) == {"repo:a", "repo:b"}


def test_nonterminal_release_is_rejected():
    ledger = TaskResourceLockLedger()
    ledger.acquire(
        mission_id="m",
        task_id="a",
        resources=("repo:a",),
        now=datetime(2026, 9, 27, tzinfo=timezone.utc),
    )
    with pytest.raises(ValueError, match="terminal state"):
        ledger.release(task_id="a", terminal_state="RUNNING")



def test_canonical_lock_order_is_sorted_and_deterministic():
    ledger = TaskResourceLockLedger()
    lease = ledger.acquire(
        mission_id="mission-lock-order",
        task_id="task-a",
        resources=(
            "repo:zeta",
            "repo:alpha",
            "repo:middle",
            "repo:alpha",
        ),
    )

    assert lease["resources"] == [
        "repo:alpha",
        "repo:middle",
        "repo:zeta",
    ]
    assert lease["acquisition_order"] == [
        "repo:alpha",
        "repo:middle",
        "repo:zeta",
    ]
    assert lease["authority"] == "DEEPSEEK_HARNESS"


def test_canonical_lock_order_prevents_cross_order_deadlock():
    ledger = TaskResourceLockLedger()
    first = ledger.acquire(
        mission_id="mission-no-deadlock",
        task_id="task-a",
        resources=("repo:b", "repo:a"),
    )
    assert first["acquisition_order"] == ["repo:a", "repo:b"]

    with pytest.raises(
        TaskResourceLockConflict,
        match="TASK_RESOURCE_LOCK_CONFLICT",
    ):
        ledger.acquire(
            mission_id="mission-no-deadlock",
            task_id="task-b",
            resources=("repo:a", "repo:b"),
        )

    released = ledger.release(
        task_id="task-a",
        terminal_state="COMPLETED",
    )
    assert released["released_resources"] == ["repo:a", "repo:b"]

    second = ledger.acquire(
        mission_id="mission-no-deadlock",
        task_id="task-b",
        resources=("repo:b", "repo:a"),
    )
    assert second["acquisition_order"] == ["repo:a", "repo:b"]
