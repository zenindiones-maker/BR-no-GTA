from dataclasses import replace
from pathlib import Path
import pytest
import app.services.generative_media_service as service
from app.services.generative_media_service import *
from app.services.global_capability_registry import AVAILABLE,FUNCTIONAL,GLOBAL_CAPABILITY_REGISTRY,UNKNOWN,GlobalCapabilityRegistry
from app.services.harness_authorization_service import issue_harness_authorization
from app.services.harness_routing_policy_service import HarnessRoutingRequest,RoutingPolicyError,route_harness_request

def _registry_for(capability_id,provider_id,model_revision):
    records=[]
    for record in GLOBAL_CAPABILITY_REGISTRY.all():
        if record.capability_id==capability_id: record=replace(record,availability=AVAILABLE,maturity=FUNCTIONAL)
        elif record.provider_id==provider_id: record=replace(record,availability=AVAILABLE,maturity=FUNCTIONAL,model_id=model_revision)
        records.append(record)
    return GlobalCapabilityRegistry(records)

def _install_test_registry(monkeypatch,spec,model):
    registry=_registry_for(spec.capability_id,spec.provider_id,model)
    monkeypatch.setattr(service,"GLOBAL_CAPABILITY_REGISTRY",registry)
    return registry

def _route(spec,model):
    domain='video' if spec.media_kind=='video' else 'audio'
    return route_harness_request(HarnessRoutingRequest(intent=spec.capability_id.replace('.',' '),authorized_action='EXECUTION',domain=domain,required_capability_id=spec.capability_id,provider_required=True,provider_domain=domain,preferred_providers=(spec.provider_id,),preferred_models=(model,),fallback_allowed=False),registry=_registry_for(spec.capability_id,spec.provider_id,model))

def _auth(spec): return issue_harness_authorization(authorized_action='EXECUTION',subject=f'capability:{spec.capability_id}',harness_decision_id='decision-g5b',execution_id='execution-g5b',lineage={'capability_id':spec.capability_id,'provider_id':spec.provider_id})
class FakeRuntime:
    def __init__(self,path): self.path=str(path); self.calls=[]
    def generate(self,payload): self.calls.append(dict(payload)); return GeneratedMediaRuntimeResult(path=self.path,backend='fake-runtime',seed=123,generation_config={'fixture':True},elapsed_seconds=.25)
def _video_probe(): return {'format':{'duration':'1.5','format_name':'mp4'},'streams':[{'codec_type':'video','width':320,'height':180,'r_frame_rate':'24/1','nb_frames':'36'}]}
def _audio_probe(): return {'format':{'duration':'2.0','format_name':'wav'},'streams':[{'codec_type':'audio','sample_rate':'48000','channels':2}]}

def test_registry_gate5b_is_metadata_only_and_unavailable():
    ids=(HUNYUAN_CAPABILITY_ID,'provider.hunyuanvideo-i2v',ACE_STEP_CAPABILITY_ID,'provider.ace-step')
    records=[GLOBAL_CAPABILITY_REGISTRY.get(x) for x in ids]
    assert all(r is not None for r in records)
    assert all(r.availability==UNKNOWN for r in records)
    assert all(r.execution_enabled is False for r in records)
    assert all(r.fallback_eligibility is False for r in records)
    assert GLOBAL_CAPABILITY_REGISTRY.get('provider.hunyuanvideo-i2v').model_id is None
    assert GLOBAL_CAPABILITY_REGISTRY.get('provider.ace-step').model_id is None
    assert GLOBAL_CAPABILITY_REGISTRY.get(HUNYUAN_CAPABILITY_ID).version==HUNYUAN_CODE_REVISION
    assert GLOBAL_CAPABILITY_REGISTRY.get(ACE_STEP_CAPABILITY_ID).version==ACE_STEP_CODE_REVISION

@pytest.mark.parametrize('spec',[HUNYUAN_SPEC,ACE_STEP_SPEC])
def test_real_registry_rejects_unproven_execution(spec):
    domain='video' if spec.media_kind=='video' else 'audio'
    with pytest.raises(RoutingPolicyError,match='No executable capability'):
        route_harness_request(HarnessRoutingRequest(intent=spec.capability_id.replace('.',' '),authorized_action='EXECUTION',domain=domain,required_capability_id=spec.capability_id,provider_required=True,provider_domain=domain,preferred_providers=(spec.provider_id,),fallback_allowed=False))

@pytest.mark.parametrize('spec,model',[ (HUNYUAN_SPEC,'hf:test-hunyuan'),(ACE_STEP_SPEC,'hf:test-ace') ])
def test_test_registry_routes_separate_capability_provider_model_executor(spec,model):
    d=_route(spec,model)
    assert d.selected_capability_id==spec.capability_id
    assert d.selected_provider==spec.provider_id
    assert d.selected_model==model
    assert d.selected_executor_binding==spec.executor_binding
    assert d.selected_provider_executor_binding==spec.executor_binding
    assert d.fallback_occurred is False

def test_public_hunyuan_executor_fail_closed_until_snapshot_pinned():
    d=_route(HUNYUAN_SPEC,'hf:test-hunyuan'); a=_auth(HUNYUAN_SPEC)
    with pytest.raises(GenerativeMediaUnavailable): service.execute_hunyuan_video_i2v(payload={'source_image_ref':'asset:image:1','prompt':'pan'},routing_decision=d,authorization=a,harness_decision_id=a.harness_decision_id,execution_id=a.execution_id,runtime=FakeRuntime('/tmp/never.mp4'))

def test_forged_authorization_rejected(monkeypatch):
    model='hf:test-hunyuan'; d=_route(HUNYUAN_SPEC,model); _install_test_registry(monkeypatch,HUNYUAN_SPEC,model); spec=replace(HUNYUAN_SPEC,model_revision=model,runtime_available=True)
    with pytest.raises(PermissionError,match='not found'): service._execute_governed_generative_media(spec=spec,payload={'source_image_ref':'asset:image:1','prompt':'pan'},routing_decision=d,authorization='forged',harness_decision_id='decision-g5b',execution_id='execution-g5b',runtime=FakeRuntime('/tmp/never.mp4'))

def test_execution_id_mismatch_rejected(monkeypatch):
    model='hf:test-hunyuan'; d=_route(HUNYUAN_SPEC,model); _install_test_registry(monkeypatch,HUNYUAN_SPEC,model); a=_auth(HUNYUAN_SPEC); spec=replace(HUNYUAN_SPEC,model_revision=model,runtime_available=True)
    with pytest.raises(PermissionError,match='execution_id mismatch'): service._execute_governed_generative_media(spec=spec,payload={'source_image_ref':'asset:image:1','prompt':'pan'},routing_decision=d,authorization=a,harness_decision_id=a.harness_decision_id,execution_id='wrong',runtime=FakeRuntime('/tmp/never.mp4'))

@pytest.mark.parametrize('field',['capability','provider','model','executor'])
def test_routing_mismatch_fail_closed(field,monkeypatch):
    model='hf:test-hunyuan'; d=_route(HUNYUAN_SPEC,model); _install_test_registry(monkeypatch,HUNYUAN_SPEC,model); a=_auth(HUNYUAN_SPEC); spec=replace(HUNYUAN_SPEC,model_revision=model,runtime_available=True); changes={}
    if field=='capability':
        changes['selected_capability_id']=ACE_STEP_CAPABILITY_ID
    elif field=='provider':
        changes['selected_provider']=ACE_STEP_PROVIDER_ID

        # Para este teste específico, torne o provider divergente executável
        # no Registry canônico de teste. Assim a validação não morre em
        # availability e alcança exatamente provider mismatch.
        records=[]
        for record in service.GLOBAL_CAPABILITY_REGISTRY.all():
            if record.provider_id==ACE_STEP_PROVIDER_ID:
                record=replace(
                    record,
                    availability=AVAILABLE,
                    maturity=FUNCTIONAL,
                    model_id=model,
                )
            records.append(record)

        monkeypatch.setattr(
            service,
            "GLOBAL_CAPABILITY_REGISTRY",
            GlobalCapabilityRegistry(records),
        )
    elif field=='model':
        changes['selected_model']='hf:unregistered'
    else:
        changes['selected_executor_binding']=ACE_STEP_EXECUTOR_BINDING
    with pytest.raises(PermissionError): service._execute_governed_generative_media(spec=spec,payload={'source_image_ref':'asset:image:1','prompt':'pan'},routing_decision=replace(d,**changes),authorization=a,harness_decision_id=a.harness_decision_id,execution_id=a.execution_id,runtime=FakeRuntime('/tmp/never.mp4'))

def test_video_artifact_and_lineage(monkeypatch,tmp_path):
    p=tmp_path/'out.mp4'; p.write_bytes(b'video'); monkeypatch.setattr(service,'_probe_media',lambda _: _video_probe()); model='hf:test-hunyuan'; d=_route(HUNYUAN_SPEC,model); _install_test_registry(monkeypatch,HUNYUAN_SPEC,model); a=_auth(HUNYUAN_SPEC); spec=replace(HUNYUAN_SPEC,model_revision=model,runtime_available=True)
    e=service._execute_governed_generative_media(spec=spec,payload={'source_image_ref':'asset:image:1','prompt':'dolly','content_item_id':3},routing_decision=d,authorization=a,harness_decision_id=a.harness_decision_id,execution_id=a.execution_id,runtime=FakeRuntime(p))
    assert e.artifact['sha256'] and e.artifact['width']==320 and e.artifact['height']==180 and e.artifact['frame_count']==36
    assert e.input_lineage['source_image_ref']=='asset:image:1' and e.upstream_code_revision==HUNYUAN_CODE_REVISION

def test_audio_artifact_and_lineage(monkeypatch,tmp_path):
    p=tmp_path/'out.wav'; p.write_bytes(b'audio'); monkeypatch.setattr(service,'_probe_media',lambda _: _audio_probe()); model='hf:test-ace'; d=_route(ACE_STEP_SPEC,model); _install_test_registry(monkeypatch,ACE_STEP_SPEC,model); a=_auth(ACE_STEP_SPEC); spec=replace(ACE_STEP_SPEC,model_revision=model,runtime_available=True)
    e=service._execute_governed_generative_media(spec=spec,payload={'prompt':'dark pulse','lyrics':'[Verse]','production_plan_id':7},routing_decision=d,authorization=a,harness_decision_id=a.harness_decision_id,execution_id=a.execution_id,runtime=FakeRuntime(p))
    assert e.artifact['sample_rate']==48000 and e.artifact['channels']==2 and e.artifact['sha256'] and e.upstream_code_revision==ACE_STEP_CODE_REVISION

def test_missing_zero_and_invalid_artifacts_rejected(monkeypatch,tmp_path):
    with pytest.raises(GenerativeMediaArtifactError): service.validate_generated_artifact(tmp_path/'missing.mp4',media_kind='video')
    empty=tmp_path/'empty.wav'; empty.write_bytes(b'')
    with pytest.raises(GenerativeMediaArtifactError): service.validate_generated_artifact(empty,media_kind='audio')
    bad=tmp_path/'bad.mp4'; bad.write_bytes(b'x'); monkeypatch.setattr(service,'_probe_media',lambda _: {'format':{'duration':'1','format_name':'mp4'},'streams':[]})
    with pytest.raises(GenerativeMediaArtifactError): service.validate_generated_artifact(bad,media_kind='video')

def test_no_publication_scheduler_authorization_or_fallback_surface():
    names=set(dir(service)); assert 'publish' not in names and 'schedule' not in names and 'issue_harness_authorization' not in names
    assert not any('fallback' in n.lower() for n in names)

def test_no_heavy_upstream_imports():
    source=Path(service.__file__).read_text(); forbidden=('torch','diffusers','hyvideo','acestep.')
    assert not any(f'import {n}' in source or f'from {n}' in source for n in forbidden)


def test_caller_controlled_model_revision_cannot_become_authority(monkeypatch):
    canonical_model="hf:canonical-hunyuan"
    d=_route(HUNYUAN_SPEC,canonical_model)
    _install_test_registry(monkeypatch,HUNYUAN_SPEC,canonical_model)
    a=_auth(HUNYUAN_SPEC)

    forged_spec=replace(
        HUNYUAN_SPEC,
        model_revision="hf:caller-controlled-model",
        runtime_available=True,
    )

    with pytest.raises(
        PermissionError,
        match="spec model/checkpoint mismatch",
    ):
        service._execute_governed_generative_media(
            spec=forged_spec,
            payload={
                "source_image_ref":"asset:image:1",
                "prompt":"pan",
            },
            routing_decision=d,
            authorization=a,
            harness_decision_id=a.harness_decision_id,
            execution_id=a.execution_id,
            runtime=FakeRuntime("/tmp/never.mp4"),
        )


def test_registry_model_is_canonical_even_when_spec_has_no_model(monkeypatch,tmp_path):
    canonical_model="hf:canonical-hunyuan"
    registry=_install_test_registry(
        monkeypatch,
        HUNYUAN_SPEC,
        canonical_model,
    )
    d=_route(HUNYUAN_SPEC,canonical_model)
    a=_auth(HUNYUAN_SPEC)

    p=tmp_path/"canonical.mp4"
    p.write_bytes(b"video")

    monkeypatch.setattr(
        service,
        "_probe_media",
        lambda _: _video_probe(),
    )

    spec=replace(
        HUNYUAN_SPEC,
        model_revision=None,
        runtime_available=False,
    )

    evidence=service._execute_governed_generative_media(
        spec=spec,
        payload={
            "source_image_ref":"asset:image:1",
            "prompt":"pan",
        },
        routing_decision=d,
        authorization=a,
        harness_decision_id=a.harness_decision_id,
        execution_id=a.execution_id,
        runtime=FakeRuntime(p),
    )

    provider=next(
        record
        for record in registry.all()
        if record.capability_type=="PROVIDER"
        and record.provider_id==HUNYUAN_PROVIDER_ID
    )

    assert provider.model_id==canonical_model
    assert evidence.model_revision==canonical_model


def test_runtime_available_flag_cannot_enable_real_registry():
    model="hf:caller-model"
    d=_route(HUNYUAN_SPEC,model)
    a=_auth(HUNYUAN_SPEC)

    spec=replace(
        HUNYUAN_SPEC,
        model_revision=model,
        runtime_available=True,
    )

    with pytest.raises(GenerativeMediaUnavailable):
        service._execute_governed_generative_media(
            spec=spec,
            payload={
                "source_image_ref":"asset:image:1",
                "prompt":"pan",
            },
            routing_decision=d,
            authorization=a,
            harness_decision_id=a.harness_decision_id,
            execution_id=a.execution_id,
            runtime=FakeRuntime("/tmp/never.mp4"),
        )


def test_registry_provider_without_model_id_fails_closed(monkeypatch):
    canonical_model="hf:test-hunyuan"
    d=_route(HUNYUAN_SPEC,canonical_model)
    a=_auth(HUNYUAN_SPEC)

    records=[]
    for record in _registry_for(
        HUNYUAN_SPEC.capability_id,
        HUNYUAN_SPEC.provider_id,
        canonical_model,
    ).all():
        if (
            record.capability_type=="PROVIDER"
            and record.provider_id==HUNYUAN_PROVIDER_ID
        ):
            record=replace(record,model_id=None)
        records.append(record)

    monkeypatch.setattr(
        service,
        "GLOBAL_CAPABILITY_REGISTRY",
        GlobalCapabilityRegistry(records),
    )

    with pytest.raises(GenerativeMediaUnavailable):
        service._execute_governed_generative_media(
            spec=HUNYUAN_SPEC,
            payload={
                "source_image_ref":"asset:image:1",
                "prompt":"pan",
            },
            routing_decision=d,
            authorization=a,
            harness_decision_id=a.harness_decision_id,
            execution_id=a.execution_id,
            runtime=FakeRuntime("/tmp/never.mp4"),
        )


def test_registry_action_cannot_be_expanded_by_routing(monkeypatch):
    model="hf:test-hunyuan"
    d=_route(HUNYUAN_SPEC,model)
    a=_auth(HUNYUAN_SPEC)

    records=[]
    for record in _registry_for(
        HUNYUAN_SPEC.capability_id,
        HUNYUAN_SPEC.provider_id,
        model,
    ).all():
        if record.capability_id==HUNYUAN_CAPABILITY_ID:
            record=replace(record,allowed_actions=("RESEARCH",))
        records.append(record)

    monkeypatch.setattr(
        service,
        "GLOBAL_CAPABILITY_REGISTRY",
        GlobalCapabilityRegistry(records),
    )

    with pytest.raises(
        PermissionError,
        match="action is not allowed",
    ):
        service._execute_governed_generative_media(
            spec=HUNYUAN_SPEC,
            payload={
                "source_image_ref":"asset:image:1",
                "prompt":"pan",
            },
            routing_decision=d,
            authorization=a,
            harness_decision_id=a.harness_decision_id,
            execution_id=a.execution_id,
            runtime=FakeRuntime("/tmp/never.mp4"),
        )


def test_authorization_action_mismatch_fails_closed(monkeypatch):
    model="hf:test-hunyuan"
    d=_route(HUNYUAN_SPEC,model)
    _install_test_registry(monkeypatch,HUNYUAN_SPEC,model)

    wrong=issue_harness_authorization(
        authorized_action="EDITORIAL",
        subject=f"capability:{HUNYUAN_CAPABILITY_ID}",
        harness_decision_id="decision-g5b-wrong-action",
        execution_id="execution-g5b-wrong-action",
        lineage={
            "capability_id":HUNYUAN_CAPABILITY_ID,
            "provider_id":HUNYUAN_PROVIDER_ID,
        },
    )

    with pytest.raises(PermissionError):
        service._execute_governed_generative_media(
            spec=HUNYUAN_SPEC,
            payload={
                "source_image_ref":"asset:image:1",
                "prompt":"pan",
            },
            routing_decision=d,
            authorization=wrong,
            harness_decision_id=wrong.harness_decision_id,
            execution_id=wrong.execution_id,
            runtime=FakeRuntime("/tmp/never.mp4"),
        )


def test_authorization_subject_mismatch_fails_closed(monkeypatch):
    model="hf:test-hunyuan"
    d=_route(HUNYUAN_SPEC,model)
    _install_test_registry(monkeypatch,HUNYUAN_SPEC,model)

    wrong=issue_harness_authorization(
        authorized_action="EXECUTION",
        subject=f"capability:{ACE_STEP_CAPABILITY_ID}",
        harness_decision_id="decision-g5b-wrong-subject",
        execution_id="execution-g5b-wrong-subject",
        lineage={
            "capability_id":ACE_STEP_CAPABILITY_ID,
            "provider_id":ACE_STEP_PROVIDER_ID,
        },
    )

    with pytest.raises(PermissionError):
        service._execute_governed_generative_media(
            spec=HUNYUAN_SPEC,
            payload={
                "source_image_ref":"asset:image:1",
                "prompt":"pan",
            },
            routing_decision=d,
            authorization=wrong,
            harness_decision_id=wrong.harness_decision_id,
            execution_id=wrong.execution_id,
            runtime=FakeRuntime("/tmp/never.mp4"),
        )


def test_fallback_is_rejected_before_runtime(monkeypatch):
    model="hf:test-hunyuan"
    d=_route(HUNYUAN_SPEC,model)
    _install_test_registry(monkeypatch,HUNYUAN_SPEC,model)
    a=_auth(HUNYUAN_SPEC)

    class RuntimeMustNotRun:
        def generate(self,payload):
            raise AssertionError("runtime must not execute after fallback")

    with pytest.raises(
        PermissionError,
        match="fallback is forbidden",
    ):
        service._execute_governed_generative_media(
            spec=HUNYUAN_SPEC,
            payload={
                "source_image_ref":"asset:image:1",
                "prompt":"pan",
            },
            routing_decision=replace(
                d,
                fallback_occurred=True,
            ),
            authorization=a,
            harness_decision_id=a.harness_decision_id,
            execution_id=a.execution_id,
            runtime=RuntimeMustNotRun(),
        )
