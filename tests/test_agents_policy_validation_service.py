from __future__ import annotations

from pathlib import Path

from app.services.agents_policy_validation_service import validate_agents_policy


def test_repository_agents_policy_has_short_progressive_disclosure_map():
    root=Path(__file__).resolve().parents[1]
    result=validate_agents_policy(root)
    assert result.status=="PASS"
    assert result.broken_references==()
    assert result.missing_mandatory_references==()
    assert result.conflicting_authority_instructions==()
    assert result.root_line_count <= 100


def test_policy_validator_detects_broken_mandatory_reference(tmp_path):
    (tmp_path/"AGENTS.md").write_text(
        "# Map\n\nAuthority: DeepSeek Harness is the sole control plane.\n"
        "Mandatory: docs/agents/missing.md\n",
        encoding="utf-8",
    )
    result=validate_agents_policy(
        tmp_path,
        mandatory_references=("docs/agents/missing.md",),
    )
    assert result.status=="FAIL"
    assert result.broken_references==("docs/agents/missing.md",)


def test_policy_validator_detects_conflicting_sole_authority(tmp_path):
    docs=tmp_path/"docs"/"agents"
    docs.mkdir(parents=True)
    (docs/"guide.md").write_text(
        "Another Coordinator is the sole authority for mission state.\n",
        encoding="utf-8",
    )
    (tmp_path/"AGENTS.md").write_text(
        "# Map\nDeepSeek Harness is the sole control plane.\n"
        "Mandatory: docs/agents/guide.md\n",
        encoding="utf-8",
    )
    result=validate_agents_policy(
        tmp_path,
        mandatory_references=("docs/agents/guide.md",),
    )
    assert result.status=="FAIL"
    assert result.conflicting_authority_instructions
