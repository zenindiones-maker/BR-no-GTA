from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services import br_production_forensic_qa_v10 as qa
from app.services import reverse_engineering_harness_service as harness
from app.services.harness_authorization_service import issue_harness_authorization,revoke_harness_authorization
from app.services.harness_capability_adapter import CapabilityAdapter
from app.services.harness_collaboration_service import TaskEnvelope
from app.services.harness_routing_policy_service import HarnessRoutingRequest,route_harness_request
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY


def _owned(root:Path):
    p=root/"owned.mp4"
    p.write_bytes(b"synthetic-only"*160)
    return p


def _meta(seconds=3.0,*,with_audio=True,video_fps="30/1",codec="h264"):
    streams=[{
        "index":0,"codec_type":"video","codec_name":codec,
        "width":320,"height":180,"pix_fmt":"yuv420p",
        "avg_frame_rate":video_fps,"r_frame_rate":"30/1",
    }]
    if with_audio:
        streams.append({"index":1,"codec_type":"audio","codec_name":"aac",
                        "sample_rate":"48000","channels":2})
    return {"streams":streams,"format":{"duration":str(seconds)}}


def _measured(**kw):
    return {"v_decode_ok":True,"a_decode_ok":True,"audio_mean_dbfs":-19.0,
            "audio_measured":True,"video_heuristic_filter_ok":True,
            "black_event_count":0,"freeze_event_count":0,**kw}


def _auth(root):
    return issue_harness_authorization(
        authorized_action="RESEARCH",
        subject=f"capability:{harness.PRODUCTION_QA_CAPABILITY_ID}",
        lineage={"allowed_media_roots":[str(root)]},
    )


def _route():
    return route_harness_request(HarnessRoutingRequest(
        intent="Inspect owned media before release",
        authorized_action="RESEARCH",
        required_capability_id=harness.PRODUCTION_QA_CAPABILITY_ID,
        domain="production-media-quality",
        fallback_allowed=False,provider_required=False,learning_required=False,
    ))


def test_positive_canary_is_technical_only_and_zero_publication(tmp_path,monkeypatch):
    p=_owned(tmp_path)
    monkeypatch.setattr(qa,"_probe",lambda _: _meta())
    monkeypatch.setattr(qa,"_sample_window",lambda *args: _measured())
    r=qa.analyze_render(p,profile=qa.PROFILE_CANARY)
    assert r["status"]=="TECHNICAL_SAMPLED_QA_PASS"
    assert r["sampled_windows"][0]["audio_mean_dbfs"]==-19
    assert r["source_sha256"]==qa._sha256(p)
    assert r["voice_identity_verified"] is False
    assert r["human_review_approved"] is False
    assert r["publish_authorized"] is False
    assert r["full_video_decode_verified"] is False
    assert r["full_audio_decode_verified"] is False
    assert r["receipt_sha256"]==__import__("hashlib").sha256(json.dumps(
        {k:v for k,v in r.items() if k!="receipt_sha256"},
        sort_keys=True,ensure_ascii=False,separators=(",",":"),allow_nan=False
    ).encode()).hexdigest()


def test_canary_missing_audio_and_wrong_fps_fail_without_decoding(tmp_path,monkeypatch):
    p=_owned(tmp_path)
    monkeypatch.setattr(qa,"_sample_window",lambda *a: (_ for _ in ()).throw(
        AssertionError("Should stop before decoding")))
    monkeypatch.setattr(qa,"_probe",lambda _: _meta(with_audio=False))
    r=qa.analyze_render(p,profile=qa.PROFILE_CANARY)
    assert "EXPECTED_ONE_AUDIO_STREAM" in r["failure_codes"]
    monkeypatch.setattr(qa,"_probe",lambda _: _meta(video_fps="25/1"))
    r=qa.analyze_render(p,profile=qa.PROFILE_CANARY)
    assert "VIDEO_AVERAGE_FPS_NOT_30" in r["failure_codes"]


def test_short_render_cannot_be_relabelled_as_20_minute_production(tmp_path,monkeypatch):
    p=_owned(tmp_path)
    monkeypatch.setattr(qa,"_probe",lambda _: _meta(3))
    r=qa.analyze_render(p,profile=qa.PROFILE_MASTER)
    assert r["status"]=="TECHNICAL_QA_FAIL"
    assert "VIDEO_DURATION_NOT_20_TO_25_MINUTES" in r["failure_codes"]
    assert "VIDEO_DIMENSIONS_INCORRECT" in r["failure_codes"]


def test_muted_audio_is_blocked_and_static_warning_is_not_false_artistic_fail(tmp_path,monkeypatch):
    p=_owned(tmp_path)
    monkeypatch.setattr(qa,"_probe",lambda _: _meta())
    monkeypatch.setattr(qa,"_sample_window",lambda *args: {
        **_measured(), "audio_mean_dbfs":None,"black_event_count":1,"freeze_event_count":1,
    })
    r=qa.analyze_render(p,profile=qa.PROFILE_CANARY)
    assert "SAMPLED_AUDIO_SILENT_OR_TOO_LOW" in r["failure_codes"]
    assert "REVIEW_INTENTIONAL_BLACK_OR_STATIC_SHOTS" in r["review_warnings"]
    assert r["artistic_approval"] is False


def test_missing_file_and_symlinked_media_denied(tmp_path):
    with pytest.raises(ValueError,match="REGULAR_MP4"):
        qa.analyze_render(tmp_path/"missing.mp4")
    actual=_owned(tmp_path)
    link=tmp_path/"link.mp4"
    link.symlink_to(actual)
    with pytest.raises(ValueError,match="REGULAR_MP4"):
        qa.analyze_render(link)


def test_harness_authorization_scopes_readonly_research(tmp_path,monkeypatch):
    p=_owned(tmp_path)
    record=GLOBAL_CAPABILITY_REGISTRY.get(harness.PRODUCTION_QA_CAPABILITY_ID)
    assert record is not None and record.execution_enabled
    assert record.allowed_actions==("RESEARCH",)
    assert record.authority==record.memory_write==record.publication_authority=="NONE"
    auth=_auth(tmp_path)
    monkeypatch.setattr(qa,"analyze_render",lambda *_args,**_kwargs:{
        "status":"TECHNICAL_SAMPLED_QA_PASS","schema_version":qa.SCHEMA,
    })
    r=CapabilityAdapter().execute(
        authorization=auth,
        task_envelope=TaskEnvelope(
            task_id="production-v10-original-audio-video",
            capability_id=harness.PRODUCTION_QA_CAPABILITY_ID,action="RESEARCH",
            objective="Measure technical release risks",
        ),
        routing_decision=_route(),
        payload={"source_path":str(p),"rights":"owned","profile":qa.PROFILE_CANARY},
    ).result
    assert r["status"]=="TECHNICAL_EVIDENCE_ONLY"
    assert r["technical_status"]=="TECHNICAL_SAMPLED_QA_PASS"
    assert r["production_ready"] is False
    assert r["publication"]=="FORBIDDEN"
    revoke_harness_authorization(auth)
    with pytest.raises(PermissionError):
        harness.execute_authorized_production_forensics(
            authorization=auth,routing_decision=_route(),
            payload={"source_path":str(p),"rights":"owned","profile":qa.PROFILE_CANARY},
        )


def test_harness_cannot_process_public_or_private_source(tmp_path):
    root=tmp_path/"owned"
    root.mkdir()
    p=_owned(root)
    auth=_auth(root)
    with pytest.raises(PermissionError,match="MEDIA_QA_OWNED_ORIGINAL_REQUIRED"):
        harness.execute_authorized_production_forensics(
            authorization=auth,routing_decision=_route(),
            payload={"source_path":str(p),"rights":"observation_only","profile":qa.PROFILE_CANARY},
        )
    with pytest.raises(PermissionError,match="MEDIA_QA_HARNESS_PAYLOAD_INVALID"):
        harness.execute_authorized_production_forensics(
            authorization=auth,routing_decision=_route(),
            payload={"source_path":str(p),"rights":"owned","profile":qa.PROFILE_CANARY,"publish":True},
        )
