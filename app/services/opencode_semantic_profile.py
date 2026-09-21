from __future__ import annotations

import json
from typing import Any


OPENCODE_SEMANTIC_AGENT_ID = "build"
OPENCODE_SEMANTIC_PROFILE_VERSION = "opencode-semantic-text-v3"
OPENCODE_SEMANTIC_MAX_STEPS = None
OPENCODE_SEMANTIC_CONTRACT = "SEMANTIC_TEXT_ONLY"

_SEMANTIC_TEXT_ONLY_HEADER = """EXECUTION MODE: SEMANTIC_TEXT_ONLY
This task is text-only semantic reasoning. Do not call, request, or attempt any tool, filesystem access, shell command, network request, browser/search action, code execution, file read/write, subagent, skill, or external lookup.
All evidence and context required for the task are already present in this prompt. Produce the requested final answer directly from that context and obey the requested output format.
""".strip()


def semantic_text_only_prompt(prompt: str) -> str:
    value = str(prompt or "").strip()
    if not value:
        raise ValueError("semantic prompt must be non-empty")
    return f"{_SEMANTIC_TEXT_ONLY_HEADER}\n\nTASK\n{value}"


def semantic_text_only_config() -> dict[str, Any]:
    """Native OpenCode V2 config for text-only semantic reasoning.

    Keep the official built-in build agent intact. Global deny-all permissions
    are resolved before the model request and remove every disabled tool from
    the request; the semantic instruction itself stays in the bounded user prompt.
    """
    deny_all = [
        {"action": "*", "resource": "*", "effect": "deny"},
    ]
    return {
        "$schema": "https://opencode.ai/config.json",
        "default_agent": OPENCODE_SEMANTIC_AGENT_ID,
        "permissions": deny_all,
    }


def semantic_text_only_config_json() -> str:
    return json.dumps(
        semantic_text_only_config(),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )


def semantic_profile_evidence() -> dict[str, Any]:
    return {
        "profile_version": OPENCODE_SEMANTIC_PROFILE_VERSION,
        "semantic_agent": OPENCODE_SEMANTIC_AGENT_ID,
        "semantic_contract": OPENCODE_SEMANTIC_CONTRACT,
        "semantic_steps": OPENCODE_SEMANTIC_MAX_STEPS,
        "permissions": "deny-all",
        "tool_exposure_contract": "permission-filter-removes-disabled-tools-before-model-request",
    }
