from __future__ import annotations

import argparse
import json
import sys

from app.main import initialize_application
from app.services.github_actions_command_runner import run_github_actions_command
from app.services.telegram_reasoning_incident_reconciler import (
    reconcile_specific_telegram_provider_failure,
)


DEFAULT_REPOSITORY = "zenindiones-maker/BR-no-GTA"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Reconcile one real Telegram -> Harness -> provider failure into the "
            "operational Learning Plane using persisted SQLite provenance plus GitHub evidence."
        )
    )
    parser.add_argument("--repository", default=DEFAULT_REPOSITORY)
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--job-id", type=int)
    parser.add_argument("--provider")
    parser.add_argument("--model")
    parser.add_argument("--http-status", type=int)
    parser.add_argument("--exit-code", type=int)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    initialize_application()
    result = reconcile_specific_telegram_provider_failure(
        repository=args.repository,
        run_id=args.run_id,
        command_runner=run_github_actions_command,
        expected_job_id=args.job_id,
        expected_provider=args.provider,
        expected_model=args.model,
        expected_http_status=args.http_status,
        expected_exit_code=args.exit_code,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    required = {
        "episode_id",
        "failure_memory_id",
        "execution_id",
        "routing_id",
        "telegram_input_id",
    }
    missing = sorted(key for key in required if not result.get(key))
    if missing:
        print(
            json.dumps(
                {
                    "TELEGRAM_INCIDENT_RECONCILIATION": "FAIL",
                    "missing": missing,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print("TELEGRAM_INCIDENT_RECONCILIATION=PASS")
    print(f"REAL_TELEGRAM_FAILURE_EPISODE={result['episode_id']}")
    print(f"FAILURE_MEMORY_FROM_REAL_INCIDENT={result['failure_memory_id']}")
    print(f"COMPETENCE_SOURCE_EXECUTION={result['execution_id']}")
    print(f"IDEMPOTENT={result.get('IDEMPOTENT')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
