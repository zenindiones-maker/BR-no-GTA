from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "semantic_smoke_gate.py"
    spec = importlib.util.spec_from_file_location("semantic_smoke_gate_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_semantic_smoke_requires_nvidia_secret_before_routing(monkeypatch, tmp_path):
    module = _module()
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.setattr(
        "sys.argv",
        [
            "semantic_smoke_gate.py",
            "--output",
            str(tmp_path / "semantic-smoke.json"),
        ],
    )
    with pytest.raises(
        RuntimeError,
        match="SEMANTIC_SMOKE_SECRET_BLOCKER:NVIDIA_API_KEY",
    ):
        module.main()


def test_semantic_smoke_contract_targets_healthy_nvidia_not_blocked_opencode():
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

    assert 'preferred_providers=("nvidia_nim",)' in source
    assert 'allowed_providers=("nvidia_nim",)' in source
    assert 'subject="provider:nvidia_nim"' in source
    assert 'preferred_providers=("opencode",)' not in source
    assert "SEMANTIC_PROVIDER_READY=PASS" not in workflow
    assert "OPENCODE_EXECUTOR_PROFILE_READY=PASS" in workflow
    assert "NVIDIA_API_KEY: ${{ secrets.NVIDIA_API_KEY }}" in workflow
