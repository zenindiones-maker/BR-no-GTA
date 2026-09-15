from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str, label: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"{label}: anchor changed")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def patch_script_generator() -> None:
    path = "app/services/script_generator_service.py"
    replace_once(
        path,
        """def _build_ai_prompt(\n    *,\n    title: str,\n    description: str,\n    research_context: dict[str, Any] | None,\n) -> str:\n""",
        """def _build_ai_prompt(\n    *,\n    title: str,\n    description: str,\n    research_context: dict[str, Any] | None,\n    target_duration_seconds: float | None = None,\n) -> str:\n""",
        "script prompt signature",
    )
    replace_once(
        path,
        """    if research_context is not None:\n        research_text = (\n            f\"Título da pesquisa: {research_context.get('title', '')}\\n\"\n            f\"Conteúdo da pesquisa: {research_context.get('content', '')}\\n\"\n            f\"URL: {research_context.get('url', '')}\"\n        )\n\n    return f\"\"\"\n""",
        """    if research_context is not None:\n        research_text = (\n            f\"Título da pesquisa: {research_context.get('title', '')}\\n\"\n            f\"Conteúdo da pesquisa: {research_context.get('content', '')}\\n\"\n            f\"URL: {research_context.get('url', '')}\"\n        )\n\n    duration_instruction = \"\"\n    if target_duration_seconds is not None:\n        target_words = max(300, int(round(float(target_duration_seconds) * 2.0)))\n        target_minutes = float(target_duration_seconds) / 60.0\n        duration_instruction = (\n            \"\\nDURAÇÃO ALVO\\n\"\n            f\"- Aproximadamente {target_minutes:.1f} minutos de narração.\\n\"\n            f\"- Mire aproximadamente {target_words} palavras no roteiro completo.\\n\"\n            \"- Distribua o desenvolvimento em blocos suficientes para sustentar a duração \"\n            \"sem repetição artificial de frases.\\n\"\n        )\n\n    return f\"\"\"\n""",
        "script duration prompt",
    )
    replace_once(
        path,
        """CONTEXTO DE PESQUISA\n{research_text}\n\nREGRAS\n""",
        """CONTEXTO DE PESQUISA\n{research_text}\n{duration_instruction}\n\nREGRAS\n""",
        "script prompt body",
    )
    replace_once(
        path,
        """def _generate_ai_structure(\n    *,\n    title: str,\n    description: str,\n    research_context: dict[str, Any] | None,\n    ai_provider: AIProvider,\n) -> dict[str, Any]:\n    prompt = _build_ai_prompt(\n        title=title,\n        description=description,\n        research_context=research_context,\n    )\n""",
        """def _generate_ai_structure(\n    *,\n    title: str,\n    description: str,\n    research_context: dict[str, Any] | None,\n    ai_provider: AIProvider,\n    target_duration_seconds: float | None = None,\n) -> dict[str, Any]:\n    prompt = _build_ai_prompt(\n        title=title,\n        description=description,\n        research_context=research_context,\n        target_duration_seconds=target_duration_seconds,\n    )\n""",
        "AI structure signature",
    )
    replace_once(
        path,
        """def generate_script_structure(\n    idea_id: int,\n    *,\n    ai_provider: AIProvider | None = None,\n) -> dict[str, Any]:\n""",
        """def generate_script_structure(\n    idea_id: int,\n    *,\n    ai_provider: AIProvider | None = None,\n    target_duration_seconds: float | None = None,\n) -> dict[str, Any]:\n""",
        "script structure signature",
    )
    replace_once(
        path,
        """        ai_structure = _generate_ai_structure(\n            title=title,\n            description=normalized_description,\n            research_context=research_context,\n            ai_provider=ai_provider,\n        )\n""",
        """        ai_structure = _generate_ai_structure(\n            title=title,\n            description=normalized_description,\n            research_context=research_context,\n            ai_provider=ai_provider,\n            target_duration_seconds=target_duration_seconds,\n        )\n""",
        "AI structure call",
    )
    replace_once(
        path,
        """def generate_and_save_script(\n    idea_id: int,\n    *,\n    ai_provider: AIProvider | None = None,\n) -> int:\n""",
        """def generate_and_save_script(\n    idea_id: int,\n    *,\n    ai_provider: AIProvider | None = None,\n    target_duration_seconds: float | None = None,\n) -> int:\n""",
        "save script signature",
    )
    replace_once(
        path,
        """    structure = generate_script_structure(\n        idea_id,\n        ai_provider=ai_provider,\n    )\n""",
        """    structure = generate_script_structure(\n        idea_id,\n        ai_provider=ai_provider,\n        target_duration_seconds=target_duration_seconds,\n    )\n""",
        "save script call",
    )


def patch_editorial_consumer() -> None:
    path = "app/services/editorial_queue_consumer.py"
    replace_once(path, "from typing import Any\n", "from typing import Any\nimport math\n", "editorial import")
    replace_once(
        path,
        """    execution_context = authorization_to_context(authorization)\n\n    lineage_goal_id = authorization.lineage.get(\"goal_id\")\n""",
        """    execution_context = authorization_to_context(authorization)\n\n    target_duration_seconds = authorization.lineage.get(\"target_duration_seconds\")\n    if target_duration_seconds is not None:\n        if (\n            isinstance(target_duration_seconds, bool)\n            or not isinstance(target_duration_seconds, (int, float))\n            or not math.isfinite(float(target_duration_seconds))\n            or float(target_duration_seconds) <= 0\n        ):\n            raise PermissionError(\"Harness target_duration_seconds must be finite and positive\")\n        target_duration_seconds = float(target_duration_seconds)\n\n    lineage_goal_id = authorization.lineage.get(\"goal_id\")\n""",
        "editorial duration lineage",
    )
    replace_once(
        path,
        """    if ai_provider is None:\n        script_id = generate_and_save_script(idea_id)\n    else:\n        script_id = generate_and_save_script(\n            idea_id,\n            ai_provider=ai_provider,\n        )\n""",
        """    if ai_provider is None:\n        script_id = generate_and_save_script(\n            idea_id,\n            target_duration_seconds=target_duration_seconds,\n        )\n    else:\n        script_id = generate_and_save_script(\n            idea_id,\n            ai_provider=ai_provider,\n            target_duration_seconds=target_duration_seconds,\n        )\n""",
        "editorial script generation",
    )
    replace_once(
        path,
        """    script_spec = generate_script_spec(script_id)\n    content_item = create_content_item(script_spec)\n""",
        """    script_spec = generate_script_spec(script_id)\n    if target_duration_seconds is not None:\n        script_spec = dict(script_spec)\n        script_spec[\"estimated_duration_seconds\"] = target_duration_seconds\n    content_item = create_content_item(script_spec)\n""",
        "editorial script spec duration",
    )


def patch_server() -> None:
    path = "app/integrations/deepseek_harness/server.py"
    anchor = """def _normalize_optional_goal_id(goal_id: str | None) -> str | None:\n    if goal_id is None:\n        return None\n    if not isinstance(goal_id, str) or not goal_id.strip():\n        raise ValueError(\"goal_id must be a non-empty string or None\")\n    return goal_id.strip()\n"""
    replacement = anchor + """\n\ndef _normalize_optional_target_duration_seconds(\n    target_duration_seconds: float | None,\n) -> float | None:\n    if target_duration_seconds is None:\n        return None\n    if isinstance(target_duration_seconds, bool) or not isinstance(\n        target_duration_seconds, (int, float)\n    ):\n        raise ValueError(\"target_duration_seconds must be numeric or None\")\n    value = float(target_duration_seconds)\n    if value <= 0 or value > 7200:\n        raise ValueError(\"target_duration_seconds must be in (0, 7200]\")\n    return value\n"""
    replace_once(path, anchor, replacement, "duration normalizer")
    replace_once(
        path,
        """def _route_editorial_provider(goal_id: str | None = None):\n    \"\"\"Route editorial AI under Harness policy before provider construction.\"\"\"\n    goal_id = _normalize_optional_goal_id(goal_id)\n""",
        """def _route_editorial_provider(\n    goal_id: str | None = None,\n    target_duration_seconds: float | None = None,\n):\n    \"\"\"Route editorial AI under Harness policy before provider construction.\"\"\"\n    goal_id = _normalize_optional_goal_id(goal_id)\n    target_duration_seconds = _normalize_optional_target_duration_seconds(\n        target_duration_seconds\n    )\n""",
        "editorial provider signature",
    )
    replace_once(
        path,
        """    if goal_id is not None:\n        lineage[\"goal_id\"] = goal_id\n    authorization = issue_harness_authorization(\n        authorized_action=\"EDITORIAL\",\n        subject=f\"provider:{decision.selected_provider}\",\n        lineage=lineage,\n    )\n""",
        """    if goal_id is not None:\n        lineage[\"goal_id\"] = goal_id\n    if target_duration_seconds is not None:\n        lineage[\"target_duration_seconds\"] = target_duration_seconds\n    authorization = issue_harness_authorization(\n        authorized_action=\"EDITORIAL\",\n        subject=f\"provider:{decision.selected_provider}\",\n        lineage=lineage,\n    )\n""",
        "provider duration lineage",
    )
    replace_once(
        path,
        """@mcp.tool()\ndef br_editorial_process_next(goal_id: str | None = None) -> str:\n    \"\"\"Process the next editorial queue item through Harness routing/policy.\"\"\"\n    goal_id = _normalize_optional_goal_id(goal_id)\n    routing, provider_authorization, ai_provider = _route_editorial_provider(goal_id)\n""",
        """@mcp.tool()\ndef br_editorial_process_next(\n    goal_id: str | None = None,\n    target_duration_seconds: float | None = None,\n) -> str:\n    \"\"\"Process the next editorial queue item through Harness routing/policy.\"\"\"\n    goal_id = _normalize_optional_goal_id(goal_id)\n    target_duration_seconds = _normalize_optional_target_duration_seconds(\n        target_duration_seconds\n    )\n    routing, provider_authorization, ai_provider = _route_editorial_provider(\n        goal_id,\n        target_duration_seconds,\n    )\n""",
        "editorial MCP signature",
    )
    old = """    if goal_id is not None:\n        lineage[\"goal_id\"] = goal_id\n    authorization = issue_harness_authorization(\n        authorized_action=\"EDITORIAL\",\n        subject=\"action:EDITORIAL\",\n        lineage=lineage,\n    )\n"""
    new = """    if goal_id is not None:\n        lineage[\"goal_id\"] = goal_id\n    if target_duration_seconds is not None:\n        lineage[\"target_duration_seconds\"] = target_duration_seconds\n    authorization = issue_harness_authorization(\n        authorized_action=\"EDITORIAL\",\n        subject=\"action:EDITORIAL\",\n        lineage=lineage,\n    )\n"""
    replace_once(path, old, new, "action duration lineage")


def patch_production_plan() -> None:
    path = "app/services/production_plan_service.py"
    replace_once(path, "import math\n", "import math\n\nMAX_SCENE_DURATION_SECONDS = 30.0\n", "scene constant")
    anchor = """    if not scenes:\n        raise ValueError(\n            \"Não foi possível criar cenas a partir dos blocos narrativos.\"\n        )\n\n    audio_requirements = [\n"""
    replacement = """    if not scenes:\n        raise ValueError(\n            \"Não foi possível criar cenas a partir dos blocos narrativos.\"\n        )\n\n    expanded_scenes: list[dict[str, Any]] = []\n    scene_order = 0\n    for scene in scenes:\n        duration = float(scene[\"duration_seconds\"])\n        part_count = max(1, int(math.ceil(duration / MAX_SCENE_DURATION_SECONDS)))\n        part_duration = duration / part_count\n        narration = str(scene[\"narration\"])\n        words = narration.split()\n        for part_index in range(part_count):\n            scene_order += 1\n            start = round(part_index * len(words) / part_count) if words else 0\n            end = round((part_index + 1) * len(words) / part_count) if words else 0\n            chunk = \" \".join(words[start:end]).strip() if words else narration\n            if not chunk:\n                chunk = narration\n            part = dict(scene)\n            part[\"order\"] = scene_order\n            if part_count > 1:\n                part[\"narrative_block\"] = (\n                    f\"{scene['narrative_block']} — parte {part_index + 1}/{part_count}\"\n                )\n            part[\"narration\"] = chunk\n            part[\"duration_seconds\"] = (\n                duration - part_duration * (part_count - 1)\n                if part_index == part_count - 1\n                else part_duration\n            )\n            expanded_scenes.append(part)\n    scenes = expanded_scenes\n\n    audio_requirements = [\n"""
    replace_once(path, anchor, replacement, "long-form scene expansion")


def add_prepare_script() -> None:
    Path("scripts/run001_ab_editorial_prepare.py").write_text(
        '''from __future__ import annotations

import json

from app.database.render_queue_repository import get_render_job
from app.integrations.deepseek_harness.server import br_editorial_process_next
from app.main import initialize_application

FROZEN_JOB_ID = 18
FROZEN_EXECUTION_ID = "run-001-canary-render-18"
CANARY_JOB_ID = 19
TARGET_DURATION_SECONDS = 1500.0
GOALS = (
    ("A", "93f99ddc-09c7-474b-8849-6981aa78d60c"),
    ("B", "10ea70fb-8255-4f89-a6ce-6d2ffced3982"),
)


def main() -> int:
    initialize_application()
    frozen = get_render_job(FROZEN_JOB_ID)
    if not frozen or frozen.get("status") != "running":
        raise RuntimeError("Job18 frozen checkpoint changed")
    if frozen.get("execution_id") != FROZEN_EXECUTION_ID:
        raise RuntimeError("Job18 execution_id changed")
    canary = get_render_job(CANARY_JOB_ID)
    if not canary or canary.get("status") != "completed":
        raise RuntimeError("Job19 must be completed before A/B editorial preparation")

    outputs = []
    for label, goal_id in GOALS:
        envelope = json.loads(
            br_editorial_process_next(
                goal_id=goal_id,
                target_duration_seconds=TARGET_DURATION_SECONDS,
            )
        )
        result = envelope.get("result") or {}
        plan = result.get("production_plan") or {}
        duration = float(plan.get("estimated_duration_seconds") or 0)
        if abs(duration - TARGET_DURATION_SECONDS) > 0.001:
            raise RuntimeError(f"VIDEO {label} duration contract mismatch: {duration}")
        scenes = plan.get("scenes") or []
        if not scenes:
            raise RuntimeError(f"VIDEO {label} has no production scenes")
        maximum = max(float(scene.get("duration_seconds") or 0) for scene in scenes)
        if maximum > 30.001:
            raise RuntimeError(f"VIDEO {label} scene duration boundary failed: {maximum}")
        outputs.append({
            "label": label,
            "goal_id": goal_id,
            "script_id": (result.get("script") or {}).get("id"),
            "content_item_id": (result.get("content_item") or {}).get("id"),
            "production_plan_id": result.get("production_plan_id"),
            "duration_seconds": duration,
            "scene_count": len(scenes),
            "max_scene_seconds": maximum,
            "status": result.get("status"),
        })

    if get_render_job(FROZEN_JOB_ID) != frozen:
        raise RuntimeError("JOB18_UNCHANGED assertion failed")

    print(json.dumps({
        "RUN001_AB_EDITORIAL": "PASS",
        "JOB18_UNCHANGED": "YES",
        "JOB19_STATUS": "completed",
        "VIDEOS": outputs,
    }, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"RUN001_AB_EDITORIAL": "BLOCKED", "ERROR": str(exc)}, ensure_ascii=False, separators=(",", ":")))
        raise
''',
        encoding="utf-8",
    )


def main() -> None:
    patch_script_generator()
    patch_editorial_consumer()
    patch_server()
    patch_production_plan()
    add_prepare_script()


if __name__ == "__main__":
    main()
