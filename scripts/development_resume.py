from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.development_recovery_checkpoint_service import DevelopmentRecoveryCheckpointService


def main() -> int:
    p=argparse.ArgumentParser(description="Read-only development recovery resume verifier")
    p.add_argument("--repo-root", default=".")
    p.add_argument("--recovery-ref", required=True)
    p.add_argument("--canonical-branch", default="work/gate6f-analytics-learning")
    args=p.parse_args()
    result=DevelopmentRecoveryCheckpointService(Path(args.repo_root)).resume(
        args.recovery_ref,canonical_branch=args.canonical_branch
    )
    print(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2))
    print("DEVELOPMENT_RESUME_OUTCOME=" + str(result["outcome"]))
    return 0 if result["outcome"]=="RESUME_READY" else 2


if __name__=="__main__":
    raise SystemExit(main())
