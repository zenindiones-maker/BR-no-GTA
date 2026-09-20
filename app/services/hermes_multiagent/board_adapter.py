from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import sys
from typing import Any, Iterator


class HermesBoardAdapter:
    """Thin adapter over the exact pinned Hermes Kanban core."""

    def __init__(self, *, upstream_root: str | Path, hermes_home: str | Path, board_id: str) -> None:
        self.upstream_root = Path(upstream_root).resolve()
        self.hermes_home = Path(hermes_home).resolve()
        self.board_id = str(board_id).strip().lower()
        if not self.board_id:
            raise ValueError("board_id is required")
        if not (self.upstream_root / "hermes_cli" / "kanban_db.py").is_file():
            raise RuntimeError("pinned Hermes Kanban core is unavailable")
        self.hermes_home.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _runtime(self) -> Iterator[tuple[Any, Any, Any]]:
        old_home = os.environ.get("HERMES_KANBAN_HOME")
        old_runtime_home = os.environ.get("HERMES_HOME")
        old_board = os.environ.get("HERMES_KANBAN_BOARD")
        root = str(self.upstream_root)
        inserted = root not in sys.path
        if inserted:
            sys.path.insert(0, root)
        os.environ["HERMES_KANBAN_HOME"] = str(self.hermes_home)
        os.environ["HERMES_HOME"] = str(self.hermes_home)
        os.environ["HERMES_KANBAN_BOARD"] = self.board_id
        try:
            from hermes_cli import kanban_db as kb
            from hermes_cli import kanban_db_connect as kbc
            from hermes_cli import kanban_db_dispatch as kbd
            module_path = Path(kb.__file__).resolve()
            if self.upstream_root not in module_path.parents:
                raise RuntimeError("Hermes Kanban import escaped pinned upstream root")
            if self.board_id != "default" and not kb.board_exists(self.board_id):
                kb.create_board(
                    self.board_id,
                    name=f"BR mission {self.board_id}",
                    description="DeepSeek Harness delegated mission board",
                )
            kb.init_db(board=self.board_id)
            yield kb, kbc, kbd
        finally:
            if old_home is None:
                os.environ.pop("HERMES_KANBAN_HOME", None)
            else:
                os.environ["HERMES_KANBAN_HOME"] = old_home
            if old_runtime_home is None:
                os.environ.pop("HERMES_HOME", None)
            else:
                os.environ["HERMES_HOME"] = old_runtime_home
            if old_board is None:
                os.environ.pop("HERMES_KANBAN_BOARD", None)
            else:
                os.environ["HERMES_KANBAN_BOARD"] = old_board
            if inserted and sys.path and sys.path[0] == root:
                sys.path.pop(0)

    @contextmanager
    def connection(self):
        with self._runtime() as (kb, kbc, kbd):
            conn = kbc.connect(board=self.board_id)
            try:
                yield kb, kbd, conn
            finally:
                conn.close()

    def create_task(
        self,
        *,
        title: str,
        body: str,
        assignee: str,
        parents: tuple[str, ...] = (),
        idempotency_key: str | None = None,
        initial_status: str = "running",
    ) -> str:
        with self.connection() as (kb, _kbd, conn):
            return kb.create_task(
                conn,
                title=title,
                body=body,
                assignee=assignee,
                parents=parents,
                created_by="deepseek-harness",
                workspace_kind="scratch",
                idempotency_key=idempotency_key,
                initial_status=initial_status,
                max_retries=3,
            )

    def comment(self, task_id: str, *, author: str, body: str) -> int:
        with self.connection() as (kb, _kbd, conn):
            return kb.add_comment(conn, task_id, author=author, body=body)

    def claim(self, task_id: str, *, claimer: str):
        with self.connection() as (kb, _kbd, conn):
            task = kb.get_task(conn, task_id)
            if task is None:
                raise ValueError(f"unknown Hermes task: {task_id}")
            if task.status == "review":
                claimed = kb.claim_review_task(conn, task_id, claimer=claimer)
            else:
                claimed = kb.claim_task(conn, task_id, claimer=claimer)
            return claimed

    def heartbeat(self, task_id: str, *, run_id: int, note: str) -> bool:
        with self.connection() as (_kb, kbd, conn):
            return bool(kbd.heartbeat_worker(conn, task_id, note=note, expected_run_id=run_id))

    def request_review(
        self,
        task_id: str,
        *,
        summary: str,
        reviewer: str,
        run_id: int,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        with self.connection() as (kb, _kbd, conn):
            return bool(kb.request_review(
                conn,
                task_id,
                summary=summary,
                reviewer=reviewer,
                metadata=dict(metadata or {}),
                expected_run_id=run_id,
            ))

    def request_changes(self, task_id: str, *, reason: str, run_id: int) -> tuple[bool, str | None]:
        with self.connection() as (kb, _kbd, conn):
            ok, target = kb.request_changes(conn, task_id, reason=reason, expected_run_id=run_id)
            return bool(ok), target

    def complete(
        self,
        task_id: str,
        *,
        summary: str,
        run_id: int | None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        with self.connection() as (kb, _kbd, conn):
            return bool(kb.complete_task(
                conn,
                task_id,
                summary=summary,
                metadata=dict(metadata or {}),
                expected_run_id=run_id,
                force=run_id is None,
            ))

    def block(self, task_id: str, *, reason: str, run_id: int, kind: str = "needs_input") -> bool:
        with self.connection() as (kb, _kbd, conn):
            return bool(kb.block_task(
                conn, task_id, reason=reason, kind=kind, expected_run_id=run_id
            ))

    def unblock(self, task_id: str) -> bool:
        with self.connection() as (kb, _kbd, conn):
            return bool(kb.unblock_task(conn, task_id))

    def worker_context(self, task_id: str) -> str:
        with self.connection() as (kb, _kbd, conn):
            return kb.build_worker_context(conn, task_id)

    def get_task(self, task_id: str) -> dict[str, Any]:
        with self.connection() as (kb, _kbd, conn):
            task = kb.get_task(conn, task_id)
            if task is None:
                raise ValueError(f"unknown Hermes task: {task_id}")
            return dict(vars(task))

    def snapshot(self) -> dict[str, Any]:
        with self.connection() as (kb, _kbd, conn):
            tasks = kb.list_tasks(conn, include_archived=True, order_by="created")
            task_rows = [dict(vars(task)) for task in tasks]
            ids = [row["id"] for row in task_rows]
            comments: list[dict[str, Any]] = []
            runs: list[dict[str, Any]] = []
            for task_id in ids:
                comments.extend(dict(vars(row)) for row in kb.list_comments(conn, task_id))
                runs.extend(dict(vars(row)) for row in kb.list_runs(conn, task_id))
            events = [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM task_events ORDER BY id ASC"
                ).fetchall()
            ]
            links = [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM task_links ORDER BY parent_id, child_id"
                ).fetchall()
            ]
            return {
                "board_id": self.board_id,
                "db_path": str(kb.kanban_db_path(self.board_id)),
                "tasks": task_rows,
                "comments": comments,
                "runs": runs,
                "events": events,
                "links": links,
            }

    def export(self, path: str | Path) -> str:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(self.snapshot(), ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        return str(target)
