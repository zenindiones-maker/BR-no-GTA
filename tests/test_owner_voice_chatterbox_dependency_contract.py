from __future__ import annotations

from pathlib import Path

from packaging.specifiers import SpecifierSet
from packaging.version import Version


ROOT = Path(__file__).resolve().parents[1]
CONSTRAINTS = ROOT / "integrations/chatterbox-ptbr/constraints.txt"
WORKFLOW = ROOT / ".github/workflows/owner-voice-human-audition-pack.yml"


def _constraints() -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in CONSTRAINTS.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "==" not in line:
            raise AssertionError(f"critical runtime constraint is not exact: {line}")
        name, version = line.split("==", 1)
        result[name.strip().lower()] = version.strip()
    return result


def test_transformers_and_hub_constraints_have_nonempty_intersection():
    constraints = _constraints()
    assert constraints["transformers"] == "5.2.0"
    hub = Version(constraints["huggingface-hub"])
    assert hub in SpecifierSet(">=1.3.0,<2.0")
    assert hub in SpecifierSet(">=0.23.2")


def test_chatterbox_runtime_is_reproducible_and_self_checked():
    constraints = _constraints()
    assert constraints["huggingface-hub"] == "1.3.5"
    assert constraints["diffusers"] == "0.29.0"
    assert constraints["torch"] == "2.6.0"
    assert constraints["torchaudio"] == "2.6.0"

    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "--constraint \"$CONSTRAINTS\"" in workflow
    assert "-m pip check" in workflow
    assert "CHATTERBOX_DEPENDENCY_CHECK=PASS" in workflow
    assert "resemble-ai/Perth.git@ff1c8ac55a976971245cdd53c18d6131ca00d993" in workflow
    assert "resemble-ai/chatterbox.git@5de7a54aa4e5e2baadb0182dde554908b48b85c2" in workflow
    assert "huggingface_hub>=0.34,<1" not in workflow
