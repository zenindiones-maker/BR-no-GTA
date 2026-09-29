from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = ROOT / "requirements.txt"

CRITICAL_WORKFLOWS = (
    ROOT / ".github/workflows/ci.yml",
    ROOT / ".github/workflows/harness-continuous-learning-validation.yml",
    ROOT / ".github/workflows/real-agent-self-improvement.yml",
    ROOT / ".github/workflows/real-multi-agent-synergy.yml",
)


def test_psutil_is_a_canonical_declared_dependency_for_profile_collection():
    requirements = REQUIREMENTS.read_text(encoding="utf-8")
    assert "psutil==7.2.2" in requirements


def test_critical_python_workflows_consume_the_same_root_dependency_manifest():
    for workflow in CRITICAL_WORKFLOWS:
        text = workflow.read_text(encoding="utf-8")
        assert "requirements.txt" in text, workflow
        assert "-r requirements.txt" in text, workflow
        assert "pip install psutil" not in text, workflow


def test_dependency_cache_keys_are_bound_to_root_manifest_when_cache_is_used():
    ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    synergy = (
        ROOT / ".github/workflows/real-multi-agent-synergy.yml"
    ).read_text(encoding="utf-8")
    assert "hashFiles('requirements.txt'" in ci
    assert "hashFiles('requirements.txt'" in synergy
