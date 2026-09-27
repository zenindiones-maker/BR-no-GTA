from __future__ import annotations

import importlib.util
from pathlib import Path


def _gate_module():
    path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "local_deterministic_integration_gate.py"
    )
    spec = importlib.util.spec_from_file_location(
        "local_deterministic_integration_gate_test",
        path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_script_shape_contract_is_independent_from_longform_word_budget():
    module = _gate_module()
    module._script_contract()


def test_longform_under_delivery_remains_fail_closed():
    module = _gate_module()
    module._longform_under_delivery_contract()
