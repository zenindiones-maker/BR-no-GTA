from __future__ import annotations

from pathlib import Path

import pytest

from app.services import development_checkpoint_capability_service as cap


class _Svc:
    def __init__(self, repo_root):
        self.repo_root = repo_root
    def persist(self, **kwargs):
        return {"development_state":"DURABLE","recovery_ref":kwargs["recovery_ref"],"authorization_id":kwargs["authorization_id"]}


def test_checkpoint_capability_requires_exact_harness_authorization(monkeypatch, tmp_path: Path):
    seen={}
    def validate(value, *, expected_action, expected_subject, expected_execution_id=None, allowed_statuses=("active",)):
        seen.update(action=expected_action,subject=expected_subject,value=value)
        return type("A",(),{"authorization_id":"auth-1"})()
    monkeypatch.setattr(cap,"validate_harness_authorization",validate)
    monkeypatch.setattr(cap,"DevelopmentRecoveryCheckpointService",_Svc)
    result=cap.execute_development_checkpoint_persist_capability(
        authorization="auth-1",
        repo_root=tmp_path,
        ledger={"mission_id":"m1"},
        checkpoint_request={
            "mission_id":"m1","task_id":"t1","checkpoint_kind":"RECOVERY",
            "canonical_branch":"work/gate6f-analytics-learning","canonical_base_sha":"a"*40,
            "recovery_ref":"recovery/dev/m1","workspace_id":"w1","sprite_id":"s1",
            "runtime_namespace":"rt","agent_execution_identity":"agent",
            "included_paths":["app"],"excluded_paths":[],
            "expected_previous_remote_oid":None,
        },
    )
    assert seen == {"action":"DEVELOPMENT","subject":"development.checkpoint.persist","value":"auth-1"}
    assert result["development_state"]=="DURABLE"
    assert result["authorization_id"]=="auth-1"


def test_checkpoint_capability_rejects_canonical_recovery_target(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        cap,"validate_harness_authorization",
        lambda *a,**k: type("A",(),{"authorization_id":"auth-1"})()
    )
    monkeypatch.setattr(cap,"DevelopmentRecoveryCheckpointService",_Svc)
    with pytest.raises(ValueError):
        cap.execute_development_checkpoint_persist_capability(
            authorization="auth-1", repo_root=tmp_path, ledger={"mission_id":"m1"},
            checkpoint_request={
                "mission_id":"m1","task_id":"t1","checkpoint_kind":"RECOVERY",
                "canonical_branch":"work/gate6f-analytics-learning","canonical_base_sha":"a"*40,
                "recovery_ref":"work/gate6f-analytics-learning","workspace_id":"w1","sprite_id":"s1",
                "runtime_namespace":"rt","agent_execution_identity":"agent",
                "included_paths":["app"],"excluded_paths":[],
            },
        )
