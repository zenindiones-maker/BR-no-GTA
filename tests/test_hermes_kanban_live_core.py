from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.services.hermes_multiagent.board_adapter import HermesBoardAdapter


pytestmark = pytest.mark.skipif(
    not os.getenv("BR_HERMES_UPSTREAM_ROOT"),
    reason="pinned Hermes upstream runtime is required",
)


def _board(tmp_path: Path, suffix: str) -> HermesBoardAdapter:
    upstream = Path(os.environ["BR_HERMES_UPSTREAM_ROOT"])
    home = tmp_path / f"home-{suffix}"
    for profile in ("hermes-worker", "hermes-reviewer"):
        p = home / "profiles" / profile
        p.mkdir(parents=True, exist_ok=True)
        (p / "config.yaml").write_text(
            f"profile_name: {profile}\nauthority: DELEGATED_ONLY\n",
            encoding="utf-8",
        )
    return HermesBoardAdapter(
        upstream_root=upstream,
        hermes_home=home,
        board_id=f"test-{suffix}",
    )


def test_real_hermes_block_human_unblock_resume(tmp_path):
    board = _board(tmp_path, "human")
    task_id = board.create_task(
        title="human gate",
        body="wait for explicit human input",
        assignee="hermes-worker",
        idempotency_key="human-gate",
    )
    claimed = board.claim(task_id, claimer="hermes-worker")
    assert claimed is not None
    run_id = int(claimed.current_run_id)
    assert board.block(
        task_id,
        reason="needs human script decision",
        run_id=run_id,
        kind="needs_input",
    )
    assert board.get_task(task_id)["status"] == "blocked"
    assert board.unblock(task_id)
    assert board.get_task(task_id)["status"] == "ready"
    resumed = board.claim(task_id, claimer="hermes-worker")
    assert resumed is not None
    assert board.complete(
        task_id,
        summary="resumed only after external unblock",
        run_id=int(resumed.current_run_id),
    )
    assert board.get_task(task_id)["status"] == "done"


def test_real_hermes_handoff_is_visible_in_downstream_context(tmp_path):
    board = _board(tmp_path, "handoff")
    parent = board.create_task(
        title="A",
        body="produce finding",
        assignee="hermes-worker",
        idempotency_key="a",
    )
    child = board.create_task(
        title="B",
        body="consume finding",
        assignee="hermes-worker",
        parents=(parent,),
        idempotency_key="b",
    )
    a = board.claim(parent, claimer="hermes-worker")
    assert a is not None
    board.comment(
        child,
        author="hermes-worker",
        body="HANDOFF_FROM=A FINDING=EL022_GAP",
    )
    assert board.complete(
        parent,
        summary="A_RESULT=EL022_GAP",
        run_id=int(a.current_run_id),
    )
    # Dispatcher would promote todo -> ready; direct DB recompute gives the same
    # durable dependency semantics without introducing another scheduler.
    with board.connection() as (kb, _kbd, conn):
        kb.recompute_ready(conn)
    ctx = board.worker_context(child)
    assert "HANDOFF_FROM=A" in ctx
    assert "A_RESULT=EL022_GAP" in ctx


def test_real_hermes_review_request_changes_retry_complete(tmp_path):
    board = _board(tmp_path, "review")
    task_id = board.create_task(
        title="critic",
        body="review loop",
        assignee="hermes-worker",
        idempotency_key="critic",
    )
    implementer = board.claim(task_id, claimer="hermes-worker")
    assert implementer is not None
    assert board.request_review(
        task_id,
        summary="UNRESOLVED_GAP=EL022",
        reviewer="hermes-reviewer",
        run_id=int(implementer.current_run_id),
    )
    reviewer = board.claim(task_id, claimer="hermes-reviewer")
    assert reviewer is not None
    ok, target = board.request_changes(
        task_id,
        reason="classify EL022 before acceptance",
        run_id=int(reviewer.current_run_id),
    )
    assert ok and target == "hermes-worker"

    retry = board.claim(task_id, claimer="hermes-worker")
    assert retry is not None
    assert board.request_review(
        task_id,
        summary="EL022_GAP_CLASSIFIED=YES",
        reviewer="hermes-reviewer",
        run_id=int(retry.current_run_id),
    )
    reviewer2 = board.claim(task_id, claimer="hermes-reviewer")
    assert reviewer2 is not None
    assert board.complete(
        task_id,
        summary="REVIEW_ACCEPTED=YES",
        run_id=int(reviewer2.current_run_id),
    )
    snapshot = board.snapshot()
    assert board.get_task(task_id)["status"] == "done"
    assert sum(1 for e in snapshot["events"] if e["kind"] == "review_requested") == 2
    assert any(e["kind"] == "changes_requested" for e in snapshot["events"])
