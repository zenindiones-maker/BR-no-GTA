from __future__ import annotations

import json
from typing import Any


OPENCODE_SEMANTIC_AGENT_ID = "build"
OPENCODE_SEMANTIC_PROFILE_VERSION = "opencode-semantic-text-v3"
OPENCODE_SEMANTIC_MAX_STEPS = 1
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

    steps=1 is intentional: on the final step OpenCode removes tools from the
    model request. Deny-all permissions remain as a second fail-closed boundary.
    """
    deny_all = [
        {"action": "*", "resource": "*", "effect": "deny"},
    ]
    return {
        "$schema": "https://opencode.ai/config.json",
        "default_agent": OPENCODE_SEMANTIC_AGENT_ID,
        "permissions": deny_all,
        "agents": {
            OPENCODE_SEMANTIC_AGENT_ID: {
                # Preserve the official built-in build system identity. The free
                # OpenCode Console tier currently rejects some customized/internal
                # agent request paths before generation. Text-only behavior is
                # enforced without replacing the build system prompt: final-step
                # tool removal + deny-all permissions + the bounded user prompt.
                "mode": "primary",
                "steps": OPENCODE_SEMANTIC_MAX_STEPS,
                "permissions": deny_all,
            }
        },
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
        "tool_exposure_contract": "final-step-tools-removed-by-opencode",
    }
