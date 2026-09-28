from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import re

import pytest


ROOT = Path(__file__).resolve().parents[1]
LOADER_PATH = ROOT / "scripts" / "agent-tooling" / "agent_skill_pack.py"
MANIFEST_PATH = ROOT / "config" / "agent_skill_pack_v1.json"
EXPECTED_SKILLS = {"superpowers", "tdd", "teach", "caveman", "handoff", "video-edit"}
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")


def _load_module():
    assert LOADER_PATH.is_file(), "agent skill pack loader not implemented"
    spec = importlib.util.spec_from_file_location("br_agent_skill_pack", LOADER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_raw_manifest() -> dict:
    assert MANIFEST_PATH.is_file(), "agent skill pack manifest not implemented"
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _entries_by_id(pack):
    return {entry.skill_id: entry for entry in pack.skills}


def test_skill_pack_manifest_has_exact_requested_skills():
    module = _load_module()
    pack = module.load_agent_skill_pack(ROOT)
    assert {entry.skill_id for entry in pack.skills} == EXPECTED_SKILLS


def test_skill_pack_sources_are_full_commit_pins():
    module = _load_module()
    pack = module.load_agent_skill_pack(ROOT)
    for entry in pack.skills:
        assert FULL_SHA.fullmatch(entry.source.commit)
        assert "latest" not in entry.source.commit.lower()
        assert entry.source.commit not in {"main", "master"}


def test_skill_pack_authority_is_none_and_bootstrap_is_off():
    module = _load_module()
    pack = module.load_agent_skill_pack(ROOT)
    assert pack.superpowers_bootstrap_global is False
    for entry in pack.skills:
        assert entry.authority == "NONE"
        assert entry.routing_authority == "NONE"
        assert entry.policy_authority == "NONE"
        assert entry.publication_authority == "NONE"
        assert entry.direct_external_side_effects is False


def test_skill_pack_rejects_duplicate_exposed_ids(tmp_path: Path):
    module = _load_module()
    raw = _load_raw_manifest()
    duplicate = copy.deepcopy(raw["skills"][0])
    raw["skills"].append(duplicate)

    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    (root / "config" / "agent_skill_pack_v1.json").write_text(
        json.dumps(raw),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate"):
        module.load_agent_skill_pack(root)


def test_vendored_skill_files_exist_and_are_non_empty():
    module = _load_module()
    pack = module.load_agent_skill_pack(ROOT)
    for entry in pack.skills:
        if not entry.local_path:
            continue
        skill_file = ROOT / entry.local_path / "SKILL.md"
        assert skill_file.is_file(), f"missing vendored skill: {entry.skill_id}"
        assert skill_file.read_text(encoding="utf-8").strip()


def test_vendored_skill_digests_match_manifest():
    module = _load_module()
    pack = module.load_agent_skill_pack(ROOT)
    for entry in pack.skills:
        if not entry.local_path:
            continue
        assert entry.content_digest, f"missing digest for {entry.skill_id}"
        assert (
            module.skill_tree_digest(ROOT / entry.local_path)
            == entry.content_digest
        )


def test_existing_project_skills_are_not_overwritten():
    existing = {
        "gta6-editorial",
        "gta6-fact-check",
        "gta6-production",
        "gta6-research",
        "gta6-youtube",
        "human-presentation-action-first",
    }
    skill_root = ROOT / ".dsh" / "skills"
    assert existing <= {p.name for p in skill_root.iterdir() if p.is_dir()}
    assert existing.isdisjoint(EXPECTED_SKILLS)


def test_teach_and_handoff_remain_explicit():
    module = _load_module()
    pack = module.load_agent_skill_pack(ROOT)
    entries = _entries_by_id(pack)
    for skill_id in ("teach", "handoff"):
        entry = entries[skill_id]
        assert entry.invocation_policy.startswith("EXPLICIT")
        text = (ROOT / entry.local_path / "SKILL.md").read_text(encoding="utf-8")
        assert "disable-model-invocation: true" in text


def test_superpowers_bootstrap_reads_pinned_manifest():
    bootstrap = ROOT / "scripts" / "agent-tooling" / "bootstrap_dsh_skill_pack.sh"
    assert bootstrap.is_file(), "superpowers DSH bootstrap not implemented"
    text = bootstrap.read_text(encoding="utf-8")
    assert "agent_skill_pack_v1.json" in text
    assert "superpowers-dsh@latest" not in text
    assert "github:LayneChai/superpowers-dsh" not in text


def test_superpowers_bootstrap_never_installs_caveman_runtime():
    bootstrap = ROOT / "scripts" / "agent-tooling" / "bootstrap_dsh_skill_pack.sh"
    assert bootstrap.is_file(), "superpowers DSH bootstrap not implemented"
    text = bootstrap.read_text(encoding="utf-8").lower()
    assert "@caveman-ai/cli" not in text
    assert "@caveman-ai/middleware" not in text
    assert "caveman setup" not in text


def test_superpowers_provider_proof_requires_bootstrap_off():
    proof = ROOT / "scripts" / "agent-tooling" / "prove_superpowers_provider.mjs"
    assert proof.is_file(), "superpowers provider proof not implemented"
    text = proof.read_text(encoding="utf-8")
    assert "bootstrap_global: false" in text
    assert 'authority: "NONE"' in text or "authority: 'NONE'" in text


def test_deepseek_workflow_bootstraps_provider_before_resolved_config():
    workflow = (ROOT / ".github" / "workflows" / "deepseek-harness.yml").read_text(
        encoding="utf-8"
    )
    bootstrap_index = workflow.find("bootstrap_dsh_skill_pack.sh")
    config_index = workflow.find("Resolve canonical BR Harness configuration")
    assert bootstrap_index >= 0, "native DSH workflow does not install skill pack"
    assert config_index >= 0
    assert bootstrap_index < config_index
