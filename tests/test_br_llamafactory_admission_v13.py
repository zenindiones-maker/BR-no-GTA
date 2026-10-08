from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.br_llamafactory_admission_v13 import (
    SOURCE_SHA, admission_policy, verify_admitted_source,
)


def _policy():
    return json.loads(Path("config/llamafactory_admission_v13.json").read_text())


def _source(root:Path):
    source=root/"pinned-source"
    (source/".git").mkdir(parents=True)
    (source/"src"/"llamafactory"/"extras").mkdir(parents=True)
    (source/"pyproject.toml").write_text('[project]\nname="llamafactory"\n')
    (source/"src"/"llamafactory"/"extras"/"env.py").write_text('VERSION = "0.9.5"\n')
    return source


def test_admission_forbids_training_voice_and_cost_promotion():
    config=_policy()
    admission_policy(config)
    for forbidden in (
        "training_enabled","inference_enabled","api_server_enabled",
        "model_download_authorized","owner_voice_access","unknown_cost_allowed",
    ):
        modified=dict(config)
        modified[forbidden]=True
        with pytest.raises(PermissionError,match="POLICY_DENIED"):
            admission_policy(modified)
    bad=dict(config)
    bad["br_owner_v1_trainer"]="llamafactory"
    with pytest.raises(PermissionError,match="POLICY_DENIED"):
        admission_policy(bad)


def test_exact_commit_distribution_and_source_are_required(tmp_path,monkeypatch):
    original=_source(tmp_path)
    commands=[]
    def invoke(command,**kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0,stdout=SOURCE_SHA+"\n" if "rev-parse" in command else "")
    monkeypatch.setattr("scripts.br_llamafactory_admission_v13.subprocess.run",invoke)
    item=verify_admitted_source(source=original,policy=_policy(),distribution_version="0.9.5")
    assert item["status"]=="PINNED_SOURCE_AND_DISTRIBUTION_METADATA_VERIFIED"
    assert item["training_executed"] is False
    assert item["gpu_ready"] is False
    assert item["tts_training_eligible"] is False
    assert item["voice_assets_read"] is False
    assert item["publication"]=="FORBIDDEN"
    assert item["harness_routing_changed"] is False
    with pytest.raises(PermissionError,match="INSTALLED_VERSION_MISMATCH"):
        verify_admitted_source(source=original,policy=_policy(),distribution_version="0.9.4")
    assert len(commands)>=2


def test_tampered_checkout_or_disallowed_model_claim_fails(tmp_path,monkeypatch):
    original=_source(tmp_path)
    def fake(command,**kwargs):
        if "rev-parse" in command:
            return SimpleNamespace(returncode=0,stdout="bad"*13)
        return SimpleNamespace(returncode=0,stdout="")
    monkeypatch.setattr("scripts.br_llamafactory_admission_v13.subprocess.run",fake)
    with pytest.raises(PermissionError,match="SHA_MISMATCH"):
        verify_admitted_source(source=original,policy=_policy(),distribution_version="0.9.5")


def test_version_tag_not_a_substitute_for_hardware_readiness():
    item=_policy()
    assert item["release"]=="v0.9.5"
    assert item["allowed_stage"]=="PINNED_SOURCE_AND_METADATA_ONLY"
    assert item["training_enabled"] is False
    assert item["approval_required_for_activation"] is True
