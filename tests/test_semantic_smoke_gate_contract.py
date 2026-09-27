from __future__ import annotations

from pathlib import Path


def test_semantic_smoke_uses_harness_selected_provider_without_fixed_route():
    source = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "semantic_smoke_gate.py"
    ).read_text(encoding="utf-8")
    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "workflows"
        / "real-multi-agent-synergy.yml"
    ).read_text(encoding="utf-8")

    assert 'preferred_providers=()' in source
    assert 'allowed_providers=()' in source
    assert 'subject=f"provider:{decision.selected_provider}"' in source
    assert 'preferred_providers=("opencode",)' not in source
    assert 'preferred_providers=("nvidia_nim",)' not in source
    assert 'allowed_providers=("nvidia_nim",)' not in source
    assert 'subject="provider:nvidia_nim"' not in source
    assert "SEMANTIC_SMOKE_SECRET_BLOCKER" not in source
    assert "NVIDIA_API_KEY: ${{ secrets.NVIDIA_API_KEY }}" in workflow


def test_nvidia_secret_scope_covers_smoke_and_real_mission():
    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "workflows"
        / "real-multi-agent-synergy.yml"
    ).read_text(encoding="utf-8")

    job_start = workflow.index("  prove:")
    steps_start = workflow.index("    steps:", job_start)
    job_env = workflow[job_start:steps_start]
    assert "NVIDIA_API_KEY: ${{ secrets.NVIDIA_API_KEY }}" in job_env

    smoke = workflow.index("      - name: SEMANTIC_SMOKE gate")
    mission = workflow.index(
        "      - name: Execute real governed multi-agent mission"
    )
    assert smoke > steps_start
    assert mission > smoke
    assert "NVIDIA_API_KEY:" not in workflow[smoke:mission]


def test_semantic_smoke_preserves_zero_cost_harness_policy():
    source = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "semantic_smoke_gate.py"
    ).read_text(encoding="utf-8")

    assert 'required_capability_id="ai.reasoning.text"' in source
    assert "provider_required=True" in source
    assert "zero_cost_operation=True" in source
    assert "fallback_allowed=False" in source
    assert "route_harness_request(" in source
