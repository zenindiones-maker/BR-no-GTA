from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

from app.services.recovery_manifest_service import FOCUSED_TESTS, build_recovery_manifest


class CheckpointSaveError(RuntimeError):
    pass


def run(*args: str, capture: bool = True) -> str:
    result=subprocess.run(
        list(args),
        text=True,
        capture_output=capture,
        check=False,
    )
    if result.returncode != 0:
        detail=(result.stderr or result.stdout or "").strip()
        raise CheckpointSaveError(f"command failed ({result.returncode}): {' '.join(args)}: {detail[:500]}")
    return (result.stdout or "").strip()


def remote_branch_sha(remote: str, branch: str) -> str:
    output=run("git","ls-remote",remote,f"refs/heads/{branch}")
    if not output:
        raise CheckpointSaveError(f"remote branch not found: {branch}")
    return output.split()[0]


def tracked_tree_clean() -> bool:
    a=subprocess.run(["git","diff","--quiet"],check=False)
    b=subprocess.run(["git","diff","--cached","--quiet"],check=False)
    return a.returncode == 0 and b.returncode == 0


def main() -> int:
    parser=argparse.ArgumentParser(description="Canonical fail-closed BR-no-GTA durable checkpoint save barrier.")
    parser.add_argument("--branch", required=True)
    parser.add_argument("--remote", default="origin")
    parser.add_argument("--checkpoint-type", default="operational-human-milestone")
    parser.add_argument("--runtime-state", type=Path)
    args=parser.parse_args()

    if not tracked_tree_clean():
        raise CheckpointSaveError("tracked working tree must be clean before checkpoint save")

    source_sha=run("git","rev-parse","HEAD")
    remote_before=remote_branch_sha(args.remote,args.branch)
    if remote_before != source_sha:
        raise CheckpointSaveError(f"remote HEAD mismatch before tests: local={source_sha} remote={remote_before}")

    test_cmd=[sys.executable,"-m","pytest","-q",*FOCUSED_TESTS]
    test_result=subprocess.run(test_cmd,text=True,check=False)
    if test_result.returncode != 0:
        raise CheckpointSaveError("focused deterministic tests failed")

    if not tracked_tree_clean():
        raise CheckpointSaveError("focused tests changed tracked repository state")

    remote_after_tests=remote_branch_sha(args.remote,args.branch)
    if remote_after_tests != source_sha:
        raise CheckpointSaveError(
            f"remote HEAD advanced during checkpoint tests: source={source_sha} remote={remote_after_tests}"
        )

    now=datetime.now(timezone.utc)
    stamp=now.strftime("%Y%m%dT%H%M%SZ")
    short=source_sha[:10]
    tag=f"br-recovery-{stamp}-{short}"
    current=Path(".checkpoints/current-system-state.json")
    history=Path(".checkpoints/history")/f"{stamp}-{short}.json"
    manifest=build_recovery_manifest(
        repo_root=Path.cwd(),
        branch=args.branch,
        head_sha=source_sha,
        checkpoint_type=args.checkpoint_type,
        git_tag=tag,
        tests_passed=list(FOCUSED_TESTS),
        created_at=now.isoformat(),
        runtime_state_path=args.runtime_state,
    )
    current.parent.mkdir(parents=True,exist_ok=True)
    history.parent.mkdir(parents=True,exist_ok=True)
    payload=json.dumps(manifest,ensure_ascii=False,indent=2,sort_keys=True)+"\n"
    current.write_text(payload,encoding="utf-8")
    history.write_text(payload,encoding="utf-8")

    run("git","config","user.name","br-no-gta-checkpoint-bot")
    run("git","config","user.email","br-no-gta-checkpoint-bot@users.noreply.github.com")
    run("git","add",str(current),str(history))

    # Final race check: do not persist a manifest derived from a superseded branch head.
    remote_precommit=remote_branch_sha(args.remote,args.branch)
    if remote_precommit != source_sha:
        raise CheckpointSaveError(
            f"remote HEAD advanced before checkpoint commit: source={source_sha} remote={remote_precommit}"
        )

    run("git","commit","-m",f"checkpoint: save {args.checkpoint_type} {stamp}")
    checkpoint_sha=run("git","rev-parse","HEAD")
    run("git","push",args.remote,f"HEAD:refs/heads/{args.branch}")
    pushed=remote_branch_sha(args.remote,args.branch)
    if pushed != checkpoint_sha:
        raise CheckpointSaveError(f"remote branch verification failed: expected={checkpoint_sha} actual={pushed}")

    run("git","tag","-a",tag,checkpoint_sha,"-m",f"BR-no-GTA recovery checkpoint {args.checkpoint_type} {stamp}")
    run("git","push",args.remote,f"refs/tags/{tag}")
    peeled=run("git","ls-remote",args.remote,f"refs/tags/{tag}^{{}}")
    if not peeled:
        raise CheckpointSaveError("annotated remote tag did not expose peeled commit")
    tag_commit=peeled.split()[0]
    if tag_commit != checkpoint_sha:
        raise CheckpointSaveError(f"remote tag verification failed: expected={checkpoint_sha} actual={tag_commit}")

    print("CHECKPOINT_SAVE=PASS")
    print(f"CHECKPOINT_SHA={checkpoint_sha}")
    print(f"CHECKPOINT_TAG={tag}")
    print(f"RECOVERY_MANIFEST={current}")
    print(f"RECOVERY_HISTORY_SNAPSHOT={history}")
    return 0


if __name__=="__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("CHECKPOINT_SAVE=FAIL")
        print(f"CHECKPOINT_ERROR={type(exc).__name__}:{exc}")
        raise
