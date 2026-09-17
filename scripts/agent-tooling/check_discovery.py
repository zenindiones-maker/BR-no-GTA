"""Prove exact native Codex discovery of the pinned Addy skill pack without a model turn."""
from __future__ import annotations

import json
from pathlib import Path
import select
import subprocess
import sys
import time

from app.services.global_capability_registry_base import ADDY_SKILLS

PLUGIN_ID = "agent-skills@agent-skills"
SKILL_NAME_PREFIXES = (f"{PLUGIN_ID}:", "agent-skills:")


def _normalized_skill_name(raw_name: str) -> str:
    for prefix in SKILL_NAME_PREFIXES:
        if raw_name.startswith(prefix):
            return raw_name[len(prefix):]
    return raw_name


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    output_path = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    if mode not in {"all", "codex"}:
        raise SystemExit("Expected all or codex")

    process = subprocess.Popen(
        ["codex", "app-server", "--stdio"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )

    def request(identifier: int, method: str, params: dict) -> dict:
        assert process.stdin is not None
        assert process.stdout is not None
        process.stdin.write(
            json.dumps({"id": identifier, "method": method, "params": params}) + "\n"
        )
        process.stdin.flush()
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if not select.select([process.stdout], [], [], 1)[0]:
                continue
            line = process.stdout.readline()
            if not line:
                raise RuntimeError("Codex discovery process exited")
            response = json.loads(line)
            if response.get("id") == identifier:
                if "error" in response:
                    raise RuntimeError("Codex discovery request failed")
                return response["result"]
        raise TimeoutError("Codex discovery timed out")

    try:
        request(1, "initialize", {"clientInfo": {"name": "br_tooling_check", "version": "2"}})
        assert process.stdin is not None
        process.stdin.write('{"method":"initialized"}\n')
        process.stdin.flush()

        data = request(
            2,
            "skills/list",
            {"cwds": [str(Path.cwd())], "forceReload": True},
        )["data"][0]
        addy = [skill for skill in data["skills"] if skill.get("pluginId") == PLUGIN_ID]
        higgs = [
            skill for skill in data["skills"]
            if str(skill.get("name", "")).startswith("higgsfield-")
        ]

        expected = set(ADDY_SKILLS)
        discovered = {
            _normalized_skill_name(str(skill["name"]))
            for skill in addy
            if skill.get("enabled")
        }
        disabled = sorted(
            _normalized_skill_name(str(skill["name"]))
            for skill in addy
            if not skill.get("enabled")
        )
        duplicates = len(addy) != len(
            {_normalized_skill_name(str(skill["name"])) for skill in addy}
        )

        if len(ADDY_SKILLS) != 24 or len(expected) != 24:
            raise RuntimeError("Registry must define exactly 24 unique Addy skills")
        if disabled:
            raise RuntimeError(f"Disabled native Addy skills: {disabled}")
        if duplicates:
            raise RuntimeError("Duplicate native Addy skill discovery entries")
        if discovered != expected:
            missing = sorted(expected - discovered)
            unexpected = sorted(discovered - expected)
            raise RuntimeError(
                f"Native Addy discovery mismatch; missing={missing}, unexpected={unexpected}"
            )
        if "browser-testing-with-devtools" in discovered:
            raise RuntimeError("Unsupported browser skill found")

        higgs_expected = {
            "higgsfield-generate",
            "higgsfield-brandkit",
            "higgsfield-video-explainer",
            "higgsfield-youtube-thumbnail",
        }
        if mode == "all" and not higgs_expected <= {
            str(skill["name"]) for skill in higgs if skill.get("enabled")
        }:
            raise RuntimeError("Selected Higgsfield skills not discovered")

        per_skill = []
        for skill in sorted(addy, key=lambda item: _normalized_skill_name(str(item["name"]))):
            name = _normalized_skill_name(str(skill["name"]))
            path = Path(str(skill["path"]))
            body = path.read_text(encoding="utf-8")
            if not body.strip():
                raise RuntimeError(f"Discovered Addy skill is empty: {name}")
            per_skill.append(
                {
                    "skill": name,
                    "native_name": skill["name"],
                    "enabled": bool(skill["enabled"]),
                    "path": str(path),
                    "non_empty": True,
                }
            )

        report = {
            "schema_version": 1,
            "status": "PASS",
            "plugin_id": PLUGIN_ID,
            "expected_count": 24,
            "discovered_enabled_count": len(discovered),
            "expected_skills": sorted(expected),
            "discovered_skills": sorted(discovered),
            "skills": per_skill,
            "model_turns": 0,
            "generation_requests": 0,
        }
        if output_path is not None:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        print(json.dumps(report, ensure_ascii=False))
        print("ADDY_24_NATIVE_DISCOVERY=PASS")
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


if __name__ == "__main__":
    main()
