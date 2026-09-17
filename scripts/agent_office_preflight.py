from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT / "integrations/munder_difflin/UPSTREAM.lock"
POLICY_PATH = ROOT / "integrations/munder_difflin/config/policy.json"


def _digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def validate(upstream_dir: Path | None = None) -> dict[str, object]:
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    assert lock["repository"] == "https://github.com/chaitanyagiri/munder-difflin"
    assert len(lock["commit"]) == 40
    assert lock["license"].startswith("MIT")
    assert lock["audit_review"]["runtime_reachable_from_br"] is False
    assert lock["audit_review"]["critical_count"] == 0
    assert policy["role"] == "AGENT_OFFICE_COORDINATOR"
    assert policy["authority"] == "DELEGATED_ONLY"
    for disabled in (
        "autonomous_scheduling",
        "scheduled_missions",
        "heartbeat_creates_work",
        "slack_trigger",
        "webhook_trigger",
        "auto_mode",
        "auto_publish",
        "desktop_ui_required",
        "secret_persistence",
    ):
        assert policy[disabled] is False, disabled

    if upstream_dir is not None:
        upstream_dir = upstream_dir.resolve()
        commit = subprocess.run(
            ["git", "-C", str(upstream_dir), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert commit == lock["commit"], (commit, lock["commit"])
        package = json.loads((upstream_dir / "package.json").read_text(encoding="utf-8"))
        assert package["version"] == lock["version"]
        assert _digest(upstream_dir / "package-lock.json") == lock["package_lock_sha256"]
        for relative, expected in lock["core_source_sha256"].items():
            assert _digest(upstream_dir / relative) == expected, relative
        assert (upstream_dir / "LICENSE").read_text(encoding="utf-8").startswith("MIT License")

    return {
        "status": "PASS",
        "upstream_commit": lock["commit"],
        "upstream_version": lock["version"],
        "coordinator_role": policy["role"],
        "authority": policy["authority"],
        "autonomous_triggers": "DISABLED",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream-dir", type=Path)
    args = parser.parse_args()
    print(json.dumps(validate(args.upstream_dir), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
