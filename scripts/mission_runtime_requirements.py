from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
from typing import Any

from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY


ADDY_EXECUTOR_BINDING = (
    "app.services.addy_harness_service.execute_authorized_addy_skill"
)


def classify_plan_runtime_requirements(mission_plan: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(mission_plan, dict):
        raise ValueError("Harness MissionPlan is required")
    if mission_plan.get("authority") != "DEEPSEEK_HARNESS":
        raise PermissionError("MissionPlan escaped DeepSeek Harness authority")
    collaboration = mission_plan.get("collaboration_plan")
    if not isinstance(collaboration, dict):
        raise ValueError("MissionPlan collaboration_plan is required")
    tasks = collaboration.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("MissionPlan contains no selected TaskEnvelope")

    capabilities: list[str] = []
    executor_bindings: list[str] = []
    semantic_provider_task_ids: list[str] = []
    required_tools: set[str] = set()
    tool_owners: dict[str, list[str]] = {}
    for task in tasks:
        if not isinstance(task, dict):
            raise ValueError("TaskEnvelope must be an object")
        capability_id = str(task.get("capability_id") or "").strip()
        executor = str(task.get("selected_executor_binding") or "").strip()
        if not capability_id or not executor:
            raise ValueError("TaskEnvelope lacks routed capability/executor metadata")
        capabilities.append(capability_id)
        executor_bindings.append(executor)
        task_id = str(task.get("task_id") or capability_id)
        record = GLOBAL_CAPABILITY_REGISTRY.get(capability_id)
        if (
            record is not None
            and str(record.health_policy or "")
            == "SEMANTIC_PROVIDER_REQUIRED"
        ):
            semantic_provider_task_ids.append(task_id)
        for raw_tool in task.get("allowed_tools") or ():
            tool = str(raw_tool or "").strip().lower()
            if not tool:
                continue
            required_tools.add(tool)
            tool_owners.setdefault(tool, []).append(task_id)

    return {
        "schema": "harness-selected-runtime-requirements/v1",
        "authority": "DEEPSEEK_HARNESS",
        "source": "HARNESS_ROUTED_TASK_ENVELOPE",
        "task_count": len(tasks),
        "selected_capability_ids": list(dict.fromkeys(capabilities)),
        "selected_executor_bindings": list(dict.fromkeys(executor_bindings)),
        "required_tools": sorted(required_tools),
        "tool_owners": {
            key: sorted(set(value))
            for key, value in sorted(tool_owners.items())
        },
        "codex_required": "codex" in required_tools,
        "tuxevil_required": "tuxevil" in required_tools,
        "addy_source_required": ADDY_EXECUTOR_BINDING in executor_bindings,
        "semantic_provider_required": bool(semantic_provider_task_ids),
        "semantic_provider_task_ids": sorted(
            set(semantic_provider_task_ids)
        ),
        "executor_bootstrap_mode": "LAZY_SELECTED_TASK_TOOLS",
        "global_provider_prerequisite": False,
    }


def _decode(value: str) -> dict[str, Any]:
    raw = base64.b64decode(value, validate=True)
    decoded = json.loads(raw.decode("utf-8"))
    if not isinstance(decoded, dict):
        raise ValueError("decoded MissionPlan must be an object")
    return decoded


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan-b64", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()

    report = classify_plan_runtime_requirements(_decode(args.plan_b64))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if args.github_output is not None:
        with args.github_output.open("a", encoding="utf-8") as handle:
            handle.write(
                "codex_required="
                + ("true" if report["codex_required"] else "false")
                + "\n"
            )
            handle.write(
                "tuxevil_required="
                + ("true" if report["tuxevil_required"] else "false")
                + "\n"
            )
            handle.write(
                "addy_source_required="
                + ("true" if report["addy_source_required"] else "false")
                + "\n"
            )
            handle.write(
                "semantic_provider_required="
                + (
                    "true"
                    if report["semantic_provider_required"]
                    else "false"
                )
                + "\n"
            )
    print("RUNTIME_REQUIREMENTS_FROM_TASK_ENVELOPE=PASS")
    print("CODEX_REQUIRED=" + ("YES" if report["codex_required"] else "NO"))
    print("TUXEVIL_REQUIRED=" + ("YES" if report["tuxevil_required"] else "NO"))
    print(
        "ADDY_SOURCE_REQUIRED="
        + ("YES" if report["addy_source_required"] else "NO")
    )
    print(
        "SEMANTIC_PROVIDER_REQUIRED="
        + (
            "YES"
            if report["semantic_provider_required"]
            else "NO"
        )
    )
    print("TUXEVIL_GLOBAL_PREREQUISITE=NO")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
