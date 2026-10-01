from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from app.services.development_checkpoint_capability_service import (
    execute_development_checkpoint_persist_capability,
)


def _read_json(path: str) -> dict:
    value=json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value,dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def main() -> int:
    p=argparse.ArgumentParser(description="Harness-authorized development recovery checkpoint")
    p.add_argument("--repo-root", default=".")
    p.add_argument("--ledger", required=True)
    p.add_argument("--request", required=True)
    p.add_argument("--authorization-id", required=True)
    args=p.parse_args()
    result=execute_development_checkpoint_persist_capability(
        authorization=args.authorization_id,
        repo_root=Path(args.repo_root),
        ledger=_read_json(args.ledger),
        checkpoint_request=_read_json(args.request),
    )
    print(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2))
    print("DEVELOPMENT_PROGRESS_DURABLE=" + (
        "PASS" if result.get("remote_readback_status")=="VERIFIED" else "FAIL"
    ))
    return 0


if __name__=="__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"DEVELOPMENT_CHECKPOINT=FAIL:{type(exc).__name__}:{exc}",file=sys.stderr)
        raise
