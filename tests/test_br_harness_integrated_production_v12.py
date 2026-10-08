from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.services import br_harness_sensory_authorization_v12 as gate
from app.services.harness_authorization_service import issue_harness_authorization,revoke_harness_authorization
from app.services.harness_capability_adapter import CapabilityAdapter
from app.services.harness_collaboration_service import TaskEnvelope
from app.services.harness_routing_policy_service import HarnessRoutingRequest,route_harness_request
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY


def _render(root:Path,filename:str,*,audio:bool=True)->Path:
    p=root/filename
    cmd=["ffmpeg","-nostdin","-hide_banner","-v","error",
        "-f","lavfi","-i","testsrc2=size=320x180:rate=30:duration=3"]
    if audio:
        cmd.extend(["-f","lavfi","-i","sine=frequency=420:sample_rate=48000:duration=3"])
    cmd.extend(["-t","3","-c:v","libx264","-preset","ultrafast","-threads","2",
                "-pix_fmt","yuv420p","-r","30"])
    if audio:
        cmd.extend(["-c:a","aac","-ar","48000","-ac","2"])
    else:
        cmd.append("-an")
    cmd.append(str(p))
    subprocess.run(cmd,capture_output=True,check=True,timeout=60)
    return p


def _route():
    return route_harness_request(HarnessRoutingRequest(
        intent="Prove locally owned movie can be technically decoded",
        authorized_action="RESEARCH",domain="production-media-quality",
        required_capability_id=gate.PRODUCTION_QA_CAPABILITY_ID,
        provider_required=False,fallback_allowed=False,learning_required=False,
    ))


@pytest.mark.skipif(__import__("shutil").which("ffmpeg") is None,reason="ffmpeg not installed")
def test_integrated_harness_can_decode_real_audio_video_and_keep_human_approval_blocked(tmp_path):
    root=tmp_path/"render-samples"
    root.mkdir(mode=0o700)
    movie=_render(root,"real-original.mp4")
    token=issue_harness_authorization(
        authorized_action="RESEARCH",
        subject=f"capability:{gate.PRODUCTION_QA_CAPABILITY_ID}",
        lineage={"allowed_media_roots":[str(root)]},
    )
    record=GLOBAL_CAPABILITY_REGISTRY.get(gate.PRODUCTION_QA_CAPABILITY_ID)
    assert record is not None and record.execution_enabled
    assert record.authority==record.publication_authority==record.memory_write=="NONE"
    payload={"source_path":str(movie),"rights":"owned",
             "profile":"synthetic_ci_canary","full_decode":True}
    e=CapabilityAdapter().execute(
        authorization=token,task_envelope=TaskEnvelope(
            task_id="v12-qa-real-original-mp4",
            capability_id=gate.PRODUCTION_QA_CAPABILITY_ID,
            action="RESEARCH",objective="Analyze original audiovisual QA",
        ),
        routing_decision=_route(),payload=payload,
    ).result
    assert e["status"]=="TECHNICAL_RESEARCH_EVIDENCE_ONLY"
    assert e["evidence"]["status"]=="TECHNICAL_SAMPLED_QA_PASS"
    assert e["full_decode_evidence"]["status"]=="FULL_SYNTHETIC_CANARY_DECODE_PASS"
    assert e["full_decode_evidence"]["entire_video_decoder_completed"] is True
    assert e["full_decode_evidence"]["entire_audio_decoder_completed"] is True
    assert e["production_readiness_board"]["can_start_publication"] is False
    assert e["br_owner_v1_approval"]=="NOT_VERIFIED"
    assert e["production_ready"] is False
    assert e["publication"]=="FORBIDDEN"
    print("BR_V12_COMMON_BRANCH_AUDIO_VIDEO_FULL_DECODE=PASS")
    revoke_harness_authorization(token)
    with pytest.raises(PermissionError):
        gate.execute_authorized_production_media_qa(
            authorization=token,routing_decision=_route(),payload=payload,
        )


@pytest.mark.skipif(__import__("shutil").which("ffmpeg") is None,reason="ffmpeg not installed")
def test_integrated_harness_cannot_approve_video_without_audio_or_short_master(tmp_path):
    root=tmp_path/"original-video"
    root.mkdir(mode=0o700)
    good=_render(root,"short.mp4")
    muted=_render(root,"no-audio.mp4",audio=False)
    token=issue_harness_authorization(
        authorized_action="RESEARCH",subject=f"capability:{gate.PRODUCTION_QA_CAPABILITY_ID}",
        lineage={"allowed_media_roots":[str(root)]},
    )
    short=gate.execute_authorized_production_media_qa(
        authorization=token,routing_decision=_route(),
        payload={"source_path":str(good),"rights":"owned",
                 "profile":"br_no_gta_1080p_master","full_decode":True},
    )
    assert "VIDEO_DURATION_NOT_20_TO_25_MINUTES" in short["evidence"]["failure_codes"]
    assert short["full_decode_evidence"] is None
    empty=gate.execute_authorized_production_media_qa(
        authorization=token,routing_decision=_route(),
        payload={"source_path":str(muted),"rights":"owned",
                 "profile":"synthetic_ci_canary","full_decode":True},
    )
    assert "EXPECTED_ONE_AUDIO_STREAM" in empty["evidence"]["failure_codes"]
    assert empty["full_decode_evidence"] is None
    assert empty["publication"]=="FORBIDDEN"
    print("BR_V12_COMMON_BRANCH_FALSE_PRODUCTION_READY=BLOCKED")


def test_integrated_harness_rejects_untrusted_payload(tmp_path):
    root=tmp_path/"original-mp4"
    root.mkdir(mode=0o700)
    p=root/"sample.mp4"
    p.write_bytes(b"x"*2048)
    auth=issue_harness_authorization(
        authorized_action="RESEARCH",subject=f"capability:{gate.PRODUCTION_QA_CAPABILITY_ID}",
        lineage={"allowed_media_roots":[str(root)]},
    )
    with pytest.raises(PermissionError,match="PAYLOAD_DENIED"):
        gate.execute_authorized_production_media_qa(
            authorization=auth,routing_decision=_route(),
            payload={"source_path":str(p),"rights":"observation_only",
                     "profile":"synthetic_ci_canary","full_decode":False},
        )
