"""Deterministically certify Addy provisioning and BR-no-GTA registry alignment."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from app.services.global_capability_registry_base import (
    ADDY_SKILLS,
    AVAILABLE,
    FUNCTIONAL,
    GLOBAL_CAPABILITY_REGISTRY,
)

SOURCE_URL = "https://github.com/addyosmani/agent-skills.git"
EXCLUDED_SKILLS = {"browser-testing-with-devtools"}


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _bootstrap_pin(repository_root: Path) -> str:
    text = (repository_root / "scripts/agent-tooling/bootstrap.sh").read_text(
        encoding="utf-8"
    )
    match = re.search(r"(?m)^  addy_sha=([0-9a-f]{40})$", text)
    if not match:
        raise RuntimeError("Pinned Addy SHA was not found in bootstrap.sh")
    return match.group(1)


def _tooling_root() -> Path:
    explicit = os.environ.get("BR_AGENT_TOOLING_ROOT")
    if explicit:
        return Path(explicit).expanduser().resolve()
    base = os.environ.get("XDG_DATA_HOME")
    if base:
        return (Path(base).expanduser() / "br-agent-tooling").resolve()
    return (Path.home() / ".local/share/br-agent-tooling").resolve()


def _git_head(path: Path) -> str:
    completed = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    repository_root = _repository_root()
    source_sha = _bootstrap_pin(repository_root)
    expected = tuple(ADDY_SKILLS)
    expected_set = set(expected)

    if len(expected) != 24 or len(expected_set) != 24:
        raise RuntimeError("ADDY_SKILLS must contain exactly 24 unique skills")

    tooling_root = _tooling_root()
    source_checkout = tooling_root / f"addy-{source_sha}"
    codex_view = tooling_root / f"addy-codex-{source_sha}"
    skills_root = codex_view / "skills"

    if not source_checkout.is_dir():
        raise RuntimeError(f"Pinned Addy source checkout is missing: {source_checkout}")
    if _git_head(source_checkout) != source_sha:
        raise RuntimeError("Pinned Addy source checkout HEAD mismatch")
    if not skills_root.is_dir():
        raise RuntimeError(f"Codex Addy compatibility view is missing: {skills_root}")

    materialized = {
        path.parent.name
        for path in skills_root.glob("*/SKILL.md")
        if path.is_file()
    }
    if materialized != expected_set:
        raise RuntimeError(
            "Materialized Addy skill set mismatch; "
            f"missing={sorted(expected_set - materialized)}, "
            f"unexpected={sorted(materialized - expected_set)}"
        )
    if EXCLUDED_SKILLS & materialized:
        raise RuntimeError("Excluded browser-dependent Addy skill was materialized")

    records = []
    for name in expected:
        capability_id = f"addy:{name}"
        record = GLOBAL_CAPABILITY_REGISTRY.get(capability_id)
        if record is None:
            raise RuntimeError(f"Registry capability missing: {capability_id}")
        checks = {
            "availability": record.availability == AVAILABLE,
            "maturity": record.maturity == FUNCTIONAL,
            "execution_enabled": record.execution_enabled,
            "provider": record.provider == "addy-agent-skills",
            "execution_kind": (
                record.resolved_execution_kind
                == (
                    "INDEPENDENT_REVIEWER"
                    if name == "code-review-and-quality"
                    else "SEMANTIC_REASONER"
                )
            ),
            "allowed_action": record.allowed_actions == ("DEVELOPMENT",),
            "agent_id": record.agent_id == "addy-agent-skills",
            "skill_id": record.skill_id == name,
            "executor_binding": (
                record.executor_binding
                == "app.services.addy_harness_service.execute_authorized_addy_skill"
            ),
        }
        if not all(checks.values()):
            failed = sorted(key for key, passed in checks.items() if not passed)
            raise RuntimeError(
                f"Registry contract mismatch for {capability_id}: {failed}"
            )

        skill_file = skills_root / name / "SKILL.md"
        if not skill_file.read_text(encoding="utf-8").strip():
            raise RuntimeError(f"Materialized Addy skill is empty: {name}")

        records.append(
            {
                "skill": name,
                "capability_id": capability_id,
                "source_sha": source_sha,
                "skill_sha256": _sha256(skill_file),
                "materialized": True,
                "registry_available": True,
                "registry_functional": True,
                "execution_enabled": True,
                "executor": "deepseek-harness-semantic-provider",
                "execution_kind": record.resolved_execution_kind,
                "agent_id": "addy-agent-skills",
                "authorized_actions": ["DEVELOPMENT"],
            }
        )

    report = {
        "schema_version": 1,
        "status": "PASS",
        "source": SOURCE_URL,
        "source_sha": source_sha,
        "expected_count": 24,
        "materialized_count": len(materialized),
        "registry_count": len(records),
        "excluded_skills": sorted(EXCLUDED_SKILLS),
        "skills": records,
        "model_turns": 0,
        "generation_requests": 0,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print("ADDY_24_PROVISIONING=PASS")
    print("ADDY_24_REGISTRY_ALIGNMENT=PASS")
    print(f"ADDY_24_SOURCE_SHA={source_sha}")


if __name__ == "__main__":
    main()
