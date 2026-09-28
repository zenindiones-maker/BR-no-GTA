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
