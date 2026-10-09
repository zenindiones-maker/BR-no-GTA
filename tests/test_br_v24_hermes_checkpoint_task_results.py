"""Focused regression: Hermes checkpoint includes cryptographically verified dependency envelopes."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import json
import tempfile

import pytest

from app.services.hermes_multiagent.runtime import (
    export_hermes_mission_checkpoint, restore_hermes_mission_checkpoint,
)


def _scenario(root: Path):
    state = root / "a-home"
    state.mkdir()
    (state / "board.json").write_text('{"schema":"fixture"}')
    artifacts = root / "a-artifacts"
    task_dir = artifacts / "task-results"
    task_dir.mkdir(parents=True)
    (task_dir / "retrieve-primary-1.json").write_text('{"schema":"task-result-envelope/v1","task_id":"retrieve-primary"}')
    results = artifacts / "capability-results"
    results.mkdir()
    (results / "retrieve-primary-1.json").write_text('{"schema":"capability-result","task_id":"retrieve-primary"}')
    spec = SimpleNamespace(
        mission_id="br-v24-checkpoint-test",
        goal_id="verify-task-result-copy",
        base_sha="a" * 40,
        allowed_task_ids=("retrieve-primary","retrieve-dependent"),
        allowed_capability_ids=("capability-1",),
    )
    checkpoint=root/"checkpoint"
    manifest=export_hermes_mission_checkpoint(
        spec=spec, hermes_home=state, artifact_dir=artifacts, checkpoint_dir=checkpoint)
    return spec, checkpoint, manifest


def test_cross_runner_checkpoint_restores_dependency_task_result_without_repeat():
    with tempfile.TemporaryDirectory() as t:
        root=Path(t)
        spec, checkpoint, manifest=_scenario(root)
        assert manifest["task_result_files"] and len(manifest["task_result_files"]) == 1
        assert manifest["task_result_files"][0]["name"]=="retrieve-primary-1.json"
        b_home=root/"b-home"
        b_artifacts=root/"b-artifacts"
        receipt=restore_hermes_mission_checkpoint(
            spec=spec, checkpoint_dir=checkpoint, hermes_home=b_home, artifact_dir=b_artifacts)
        assert receipt["CANONICAL_CHECKPOINT_RESTORED"]=="PASS"
        assert (b_artifacts/"task-results/retrieve-primary-1.json").read_bytes() == (
            checkpoint/"task-results/retrieve-primary-1.json").read_bytes()
        )
        assert (b_artifacts/"capability-results/retrieve-primary-1.json").is_file()


@pytest.mark.parametrize("mutation",["missing","corrupt","extra"])
def test_checkpoint_dependency_artifact_loss_or_tamper_is_rejected(mutation):
    with tempfile.TemporaryDirectory() as t:
        root=Path(t)
        spec, checkpoint, _=_scenario(root)
        path=checkpoint/"task-results/retrieve-primary-1.json"
        if mutation=="missing":
            path.unlink()
        elif mutation=="corrupt":
            path.write_text('{"schema":"bad"}')
        else:
            (checkpoint/"task-results/injected.json").write_text("{}")
        with pytest.raises((PermissionError,ValueError)):
            restore_hermes_mission_checkpoint(
                spec=spec,checkpoint_dir=checkpoint,hermes_home=root/"b-home",
                artifact_dir=root/"b-artifacts")
