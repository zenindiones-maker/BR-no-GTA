from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services import br_llamafactory_training_admission_v13 as factory
from app.services import br_llamafactory_harness_gate_v13 as gate
from app.services.harness_authorization_service import (
    issue_harness_authorization,revoke_harness_authorization,
)
from app.services.harness_capability_adapter import CapabilityAdapter
from app.services.harness_collaboration_service import TaskEnvelope
from app.services.harness_routing_policy_service import HarnessRoutingRequest,route_harness_request
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY


def _make_dataset(root:Path,*,bad:dict|None=None)->Path:
    root.mkdir(exist_ok=True)
    p=root/"synthetic-owned.jsonl"
    rows=[
        {"instruction":f"Classifique uma observação sintética {i}.",
         "input":f"evento-{i}",
         "output":f"Classe original {i%2}."} for i in range(6)
    ]
    if bad is not None:
        rows[0]=bad
    p.write_text("".join(json.dumps(r,ensure_ascii=False)+"\n" for r in rows),encoding="utf-8")
    return p


def _authorization(root:Path):
    return issue_harness_authorization(
        authorized_action="RESEARCH",
        subject=f"capability:{gate.CAPABILITY_ID}",
        lineage={"allowed_media_roots":[str(root)]},
    )


def _route():
    return route_harness_request(HarnessRoutingRequest(
        intent="Check synthetic original textual dataset for bounded Qwen3 SFT research",
        authorized_action="RESEARCH",domain="model-training-readiness",
        required_capability_id=gate.CAPABILITY_ID,
        provider_required=False,fallback_allowed=False,learning_required=False,
    ))


def test_real_synthetic_alpaca_jsonl_receives_hash_without_any_training(tmp_path):
    directory=tmp_path/"original-synthetic"
    source=_make_dataset(directory)
    a=factory.prepare_readonly_plan(dataset_path=source,allowed_roots=(directory,))
    assert a["status"]=="DATASET_ADMITTED_TRAINING_BLOCKED"
    assert a["model_id"]=="Qwen/Qwen3-0.6B"
    assert a["pinned_upstream_commit"]==factory.PINNED_COMMIT
    assert a["dataset_evidence"]["example_count"]==6
    assert a["dataset_evidence"]["runtime_installed"] is False
    assert a["dataset_evidence"]["gpu_attested"] is False
    assert a["run_executed"] is False
    assert a["publication_authorized"] is False
    assert a["owner_voice_dataset_access"] is False
    assert a["receipt_sha256"]


def test_harness_research_route_and_revocation_enforced(tmp_path):
    directory=tmp_path/"source-synthetic"
    data=_make_dataset(directory)
    auth=_authorization(directory)
    record=GLOBAL_CAPABILITY_REGISTRY.get(gate.CAPABILITY_ID)
    assert record is not None and record.execution_enabled
    assert record.allowed_actions==("RESEARCH",)
    assert record.authority==record.memory_write==record.publication_authority=="NONE"
    res=CapabilityAdapter().execute(
        authorization=auth,
        task_envelope=TaskEnvelope(
            task_id="factory-v13-alpaca-synthetic",
            capability_id=gate.CAPABILITY_ID,action="RESEARCH",
            objective="Inspect original synthetic SFT data in scoped research",
        ),
        routing_decision=_route(),
        payload={"dataset_path":str(data),"rights":"owned","model_id":"Qwen/Qwen3-0.6B"},
    ).result
    assert res["status"]=="RESEARCH_DATASET_ADMITTED_NO_TRAINING"
    assert res["publication"]=="FORBIDDEN"
    assert res["model_training_executed"] is False
    assert res["owner_voice_training_access"]=="FORBIDDEN"
    revoke_harness_authorization(auth)
    with pytest.raises(PermissionError):
        gate.execute_authorized_llamafactory_admission(
            authorization=auth,routing_decision=_route(),
            payload={"dataset_path":str(data),"rights":"owned","model_id":"Qwen/Qwen3-0.6B"},
        )


@pytest.mark.parametrize("forbidden",[
    {"instruction":"exemplo","input":"","output":"owner_voice reference"},
    {"instruction":"exemplo","input":"","output":"api_key=sample"},
    {"instruction":"exemplo","input":"","output":"ref_audio"},
])
def test_voice_and_credential_training_content_blocked(tmp_path,forbidden):
    directory=tmp_path/"own-original"
    data=_make_dataset(directory,bad=forbidden)
    with pytest.raises(ValueError,match="VOICE_OR_SECRETS"):
        factory.prepare_readonly_plan(dataset_path=data,allowed_roots=(directory,))


def test_no_tts_or_unreviewed_model_can_be_selected(tmp_path):
    directory=tmp_path/"own-original"
    data=_make_dataset(directory)
    for name in ["Qwen/Qwen3-TTS-12Hz-1.7B-Base","any/restricted-model","Qwen/Qwen3-4B-Instruct-2507"]:
        with pytest.raises(PermissionError,match="MODEL_NOT_APPROVED"):
            factory.prepare_readonly_plan(
                dataset_path=data,allowed_roots=(directory,),model_id=name,
            )


def test_traversal_and_symlink_not_in_scope(tmp_path):
    allowed=tmp_path/"owned"
    real=tmp_path/"elsewhere"
    allowed.mkdir()
    data=_make_dataset(real)
    with pytest.raises(PermissionError,match="OUTSIDE_OWNER_SCOPE"):
        factory.prepare_readonly_plan(dataset_path=data,allowed_roots=(allowed,))
    link=allowed/"link.jsonl"
    link.symlink_to(data)
    with pytest.raises(PermissionError,match="NOT_ADMITTED"):
        factory.prepare_readonly_plan(dataset_path=link,allowed_roots=(allowed,))


def test_policy_cannot_be_overridden_through_payload(tmp_path):
    directory=tmp_path/"own-original"
    data=_make_dataset(directory)
    auth=_authorization(directory)
    with pytest.raises(PermissionError,match="PAYLOAD_FORBIDDEN"):
        gate.execute_authorized_llamafactory_admission(
            authorization=auth,routing_decision=_route(),
            payload={"dataset_path":str(data),"rights":"owned",
                     "model_id":"Qwen/Qwen3-0.6B","enable_gpu_training":True},
        )
