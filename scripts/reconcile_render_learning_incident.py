from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.main import initialize_application
from app.services.github_actions_command_runner import run_github_actions_command
from app.services.github_actions_learning_observer import (
    GitHubActionsLearningObserver,
    capture_observed_render_episode,
)


DEFAULT_REPOSITORY = "zenindiones-maker/BR-no-GTA"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Capture one terminal real GitHub audiovisual run into the Harness Learning Plane."
    )
    parser.add_argument("--render-job", required=True, type=Path)
    parser.add_argument("--run-id", required=True, type=int)
    parser.add_argument("--job-id", type=int)
    parser.add_argument("--timeout-minutes", type=int)
    parser.add_argument("--expected-head-sha")
    parser.add_argument("--repository", default=DEFAULT_REPOSITORY)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    initialize_application()
    job = json.loads(args.render_job.read_text(encoding="utf-8"))
    observer = GitHubActionsLearningObserver(run_github_actions_command)
    observation = observer.observe(
        repository=args.repository,
        run_id=args.run_id,
        job_id=args.job_id,
        expected_head_sha=args.expected_head_sha,
        timeout_minutes=args.timeout_minutes,
    )
    captured = capture_observed_render_episode(
        render_job=job,
        observation=observation,
    )
    episode = captured["episode"]
    failure = captured.get("failure_memory")
    result = {
        "REAL_RENDER_FAILURE_EPISODE": "PASS",
        "run_id": observation.run_id,
        "job_id": observation.job_id,
        "episode_id": episode["episode_id"],
        "failure_memory_id": failure["memory_id"] if failure else None,
        "failure_pattern": failure.get("failure_pattern") if failure else None,
        "status": episode["status"],
        "actual_outcome": episode["actual_outcome"],
        "duration_seconds": episode["duration_seconds"],
        "skill_version": episode["skill_version"],
        "evidence_refs": episode["evidence_refs"],
        "failure_support_count": failure.get("support_count") if failure else None,
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if episode["status"] == "COMPLETED":
        raise SystemExit("expected a failed/cancelled render incident")
    if failure is None:
        raise SystemExit("failed render incident did not produce failure memory")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
