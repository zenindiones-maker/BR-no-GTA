from __future__ import annotations

import argparse
import json
import os

os.environ.setdefault("ZERO_COST_OPERATION", "TRUE")
os.environ.setdefault("GITHUB_ACTIONS_REPOSITORY", "zenindiones-maker/BR-no-GTA")
os.environ.setdefault("GITHUB_ACTIONS_RENDER_REF", "work/gate6f-analytics-learning")

from app.integrations.deepseek_harness.server import (
    br_youtube_pode_postar,
    br_youtube_publication_preview,
    br_youtube_publication_reconcile,
    br_youtube_publish,
    br_youtube_publish_reconcile,
)
from app.main import initialize_application


def _emit(value: str) -> None:
    parsed = json.loads(value)
    print(json.dumps(parsed, ensure_ascii=False, separators=(",", ":"), sort_keys=True), flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Exact YouTube Publication control through Harness boundaries. "
            "No 'next pending' queue operation is exposed here."
        )
    )
    parser.add_argument(
        "action",
        choices=(
            "preview",
            "private-upload",
            "private-reconcile",
            "public-reconcile",
            "pode-postar",
        ),
    )
    parser.add_argument("--publication-id", type=int, required=True)
    parser.add_argument(
        "--confirm",
        default="",
        help="Required only for 'pode-postar'; must be exactly PODE_POSTAR.",
    )
    args = parser.parse_args()
    if args.publication_id <= 0:
        raise ValueError("--publication-id must be a positive integer")

    initialize_application()

    if args.action == "preview":
        _emit(br_youtube_publication_preview(publication_id=args.publication_id))
        return 0
    if args.action == "private-upload":
        _emit(br_youtube_publish(publication_id=args.publication_id))
        return 0
    if args.action == "private-reconcile":
        _emit(br_youtube_publish_reconcile(publication_id=args.publication_id))
        return 0
    if args.action == "public-reconcile":
        _emit(br_youtube_publication_reconcile(publication_id=args.publication_id))
        return 0

    if args.confirm != "PODE_POSTAR":
        raise PermissionError(
            "Explicit user confirmation is required: --confirm PODE_POSTAR"
        )
    # This direct call still enters the official MCP/Harness boundary.  The
    # confirmation flag is only a CLI safety interlock; HarnessAuthorization
    # remains the sole operational authorization contract.
    _emit(br_youtube_pode_postar(publication_id=args.publication_id))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
