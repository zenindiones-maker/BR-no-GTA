from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.harness_authorization_service import issue_harness_authorization,revoke_harness_authorization
from app.services.harness_capability_adapter import CapabilityAdapter
from app.services.harness_collaboration_service import TaskEnvelope
from app.services.harness_routing_policy_service import HarnessRoutingRequest,route_harness_request
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services import reverse_engineering_harness_service as harness
from app.services import reverse_engineering_studio_v6_service as studio


def _route():
    return route_harness_request(HarnessRoutingRequest(
        intent="Measure licensed studio technique without changing live media",
        authorized_action="RESEARCH",required_capability_id=harness.STUDIO_CAPABILITY_ID,
        domain="studio-forensics",fallback_allowed=False,
        provider_required=False,learning_required=False,
    ))


def _auth(root):
    return issue_harness_authorization(
        authorized_action="RESEARCH",
        subject=f"capability:{harness.STUDIO_CAPABILITY_ID}",
        lineage={"allowed_media_roots":[str(root)]},
    )


def _file(folder,name="original.json"):
    target=folder/name
    target.write_text('{"test":"yes"}')
    return target


def test_studio_registered_readonly_and_real_harness_adapter(tmp_path,monkeypatch):
    target=_file(tmp_path)
    auth=_auth(tmp_path)
    record=GLOBAL_CAPABILITY_REGISTRY.get(harness.STUDIO_CAPABILITY_ID)
    assert record is not None and record.execution_enabled
    assert record.memory_write==record.authority==record.publication_authority=="NONE"
    assert record.side_effect_class=="READ_ONLY"
    monkeypatch.setattr(studio,"compile_original_timeline",lambda p: {
        "schema_version":"BROriginalTimelineEvidence/v1","media_resolved":False,
        "rendered":False,"evidence_sha256":"a"*64,
    })
    result=CapabilityAdapter().execute(
        authorization=auth,
        task_envelope=TaskEnvelope(
            task_id="studio-v6-timeline-proof",
            capability_id=harness.STUDIO_CAPABILITY_ID,action="RESEARCH",
            objective="Inspect original frame-exact storyboard",
        ),
        routing_decision=_route(),
        payload={"mode":"timeline","rights":"owned","inputs":[str(target)],"options":{}},
    ).result
    assert result["status"]=="EVIDENCE_ONLY"
    assert result["memory_write"]=="NOT_ATTEMPTED"
    assert result["production_mutation"] is False
    assert result["publication"]=="FORBIDDEN"


@pytest.mark.parametrize("bad",[
    {"mode":"alignment","rights":"observation_only","inputs":["a"],"options":{}},
    {"mode":"motion","rights":"owned","inputs":["a"],"options":{"window_seconds":3}},
    {"mode":"timeline","rights":"owned","inputs":["a","b"],"options":{}},
    {"mode":"unknown","rights":"owned","inputs":["a"],"options":{}},
    {"mode":"timeline","rights":"owned","inputs":["a"],"options":{},"publish":True},
])
def test_bad_modes_unknown_actions_and_unapproved_rights_fail_before_access(tmp_path,bad):
    auth=_auth(tmp_path)
    with pytest.raises(PermissionError):
        harness.execute_authorized_studio_observation(
            authorization=auth,routing_decision=_route(),payload=bad)


def test_owner_voice_symlink_and_revoked_auth_rejected(tmp_path):
    root=tmp_path/"public"
    root.mkdir()
    private=root/"owner_voice"
    private.mkdir()
    reference=_file(private,"biometric.json")
    normal=_file(root,"ok.json")
    auth=_auth(root)
    with pytest.raises(PermissionError,match="PRIVATE_PATH"):
        harness.execute_authorized_studio_observation(
            authorization=auth,routing_decision=_route(),
            payload={"mode":"timeline","rights":"owned","inputs":[str(reference)],"options":{}},
        )
    link=root/"pointer.json"
    link.symlink_to(normal)
    with pytest.raises(PermissionError,match="SYMLINK"):
        harness.execute_authorized_studio_observation(
            authorization=auth,routing_decision=_route(),
            payload={"mode":"timeline","rights":"owned","inputs":[str(link)],"options":{}},
        )
    revoke_harness_authorization(auth)
    with pytest.raises(PermissionError):
        harness.execute_authorized_studio_observation(
            authorization=auth,routing_decision=_route(),
            payload={"mode":"timeline","rights":"owned","inputs":[str(normal)],"options":{}},
        )
