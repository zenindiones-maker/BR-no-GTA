from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import br_harness_visual_timeline_v16 as timeline
from app.services import br_harness_sensory_pixel_v12 as pixels
from app.services import br_harness_sensory_authorization_v12 as gate
from app.services.harness_authorization_service import issue_harness_authorization
from app.services.harness_routing_policy_service import HarnessRoutingRequest,route_harness_request


def _scoped(tmp_path):
    root=tmp_path/"original-visuals"
    root.mkdir(mode=0o700)
    shots=root/"samples"
    shots.mkdir(mode=0o700)
    return root,shots


def _render(path:Path,*,change:bool):
    inputs=[
        "-f","lavfi","-i","color=c=red:s=320x180:r=30:d=3",
    ]
    if change:
        inputs+=["-f","lavfi","-i","color=c=blue:s=320x180:r=30:d=3"]
        video_filter="[0:v][1:v]concat=n=2:v=1:a=0[v]"
        inputs+=["-filter_complex",video_filter,"-map","[v]"]
    else:
        inputs=["-f","lavfi","-i","color=c=red:s=320x180:r=30:d=6"]
    subprocess.run(["ffmpeg","-nostdin","-hide_banner","-v","error",
                    *inputs,"-c:v","libx264","-threads","2",
                    "-pix_fmt","yuv420p","-preset","ultrafast",str(path)],
                   check=True,capture_output=True,text=True,timeout=50)


def _receipt(source):
    return {
        "schema_version":"BRHarnessSensoryPixelObservation/v1",
        "status":"PIXELS_DECODED_AND_MEASURED",
        "media_kind":"owner_video_mp4",
        "source_sha256":pixels._sha(source),
        "receipt_sha256":"f"*64,
        "media_metadata":{"duration_seconds":6.0},
    }


def _routing():
    return route_harness_request(HarnessRoutingRequest(
        intent="Observe original bounded scene changes without decoding owner voice",
        authorized_action="RESEARCH",
        domain="production-multimodal-observation",
        required_capability_id=gate.CAPABILITY_ID,
        provider_required=False,fallback_allowed=False,learning_required=False,
    ))


def test_window_plan_stays_bounded_and_covers_time_sections():
    assert timeline._windows(6)==(0.0,)
    assert timeline._windows(24)==(0.,8.,16.)
    assert timeline._windows(1200)==(0.,596.,1192.)
    for invalid in (None,-1,0,float("nan"),float("inf"),1900,True):
        with pytest.raises(ValueError,match="DURATION"):
            timeline._windows(invalid)


def test_report_rejects_source_hash_mismatch_before_any_ffmpeg(tmp_path,monkeypatch):
    root,_=_scoped(tmp_path)
    source=root/"owner.mp4"
    source.write_bytes(b"x"*2050)
    report=_receipt(source)
    report["source_sha256"]="0"*64
    monkeypatch.setattr(timeline,"_measure_window",lambda *_args,**_kwargs:
                        pytest.fail("should fail before launching FFmpeg"))
    with pytest.raises(PermissionError,match="SAME_SOURCE_PIXELS"):
        timeline.observe_timeline(source=source,authoritative_pixel_evidence=report)


def test_no_semantic_or_voice_claim_from_even_a_successful_observation(tmp_path,monkeypatch):
    root,_=_scoped(tmp_path)
    source=root/"owned.mp4"
    source.write_bytes(b"x"*2050)
    monkeypatch.setattr(timeline,"_measure_window",lambda source,start,seconds,**kwargs:{
        "start_seconds":start,"analyzed_seconds":seconds,
        "candidate_transition_seconds":[1.5],"candidate_transitions_count":1,
        "decode_exit_zero":True,
    })
    receipt=timeline.observe_timeline(source=source,authoritative_pixel_evidence=_receipt(source))
    assert receipt["status"]=="SCOPED_VIDEO_TRANSITIONS_MEASURED"
    assert receipt["candidate_transition_times_seconds"]==[1.5]
    for field in ("whole_video_scenes_certified","semantically_interpreted",
                  "artist_recognition_certified","subtitle_absence_certified",
                  "audio_transcript_certified","owner_identity_certified",
                  "automated_editorial_pass","publisher_authorized",
                  "mcp_authority_granted","raw_frame_payload_included"):
        assert receipt[field] is False
    assert receipt["sha256"]==hashlib.sha256(json.dumps({
        k:v for k,v in receipt.items() if k!="sha256"
    },sort_keys=True,ensure_ascii=False,allow_nan=False,
       separators=(",",":")).encode()).hexdigest()


@pytest.mark.skipif(__import__("shutil").which("ffmpeg") is None,
                    reason="FFmpeg unavailable")
def test_original_two_shot_video_has_real_cut_static_video_does_not(tmp_path):
    root,scratch=_scoped(tmp_path)
    joined=root/"original-two-shots.mp4"
    still=root/"original-static.mp4"
    _render(joined,change=True)
    _render(still,change=False)
    actual=pixels.inspect_pixel_evidence(joined,kind="owner_video_mp4",
                                          private_workspace=scratch)
    measured=timeline.observe_timeline(source=joined,authoritative_pixel_evidence=actual)
    assert measured["candidate_transition_count"]>=1
    assert any(2.7<=x<=3.3 for x in measured["candidate_transition_times_seconds"])
    assert measured["whole_video_scenes_certified"] is False
    # Need a fresh scratch path to avoid V12 no-overwrite frame collision.
    other=root/"other-frames"
    other.mkdir(mode=0o700)
    control=pixels.inspect_pixel_evidence(still,kind="owner_video_mp4",
                                          private_workspace=other)
    silent=timeline.observe_timeline(source=still,authoritative_pixel_evidence=control)
    assert silent["candidate_transition_count"]==0
    print("BR_V16_REAL_TWO_SHOT_VIDEO_CUT=PASS")
    print("BR_V16_STATIC_NEGATIVE_CONTROL=PASS")


def test_harness_rejects_unapproved_scan_for_png_and_payload_escalation(tmp_path):
    root,scratch=_scoped(tmp_path)
    import PIL.Image
    image=root/"owner.png"
    PIL.Image.new("RGB",(32,32),(40,40,40)).save(image)
    auth=issue_harness_authorization(
        authorized_action="RESEARCH",
        subject=f"capability:{gate.CAPABILITY_ID}",
        lineage={"allowed_media_roots":[str(root)]},
    )
    payload={"source_path":str(image),"private_workspace":str(scratch),
             "kind":"owner_screenshot_png","rights":"owned","scene_scan":True}
    with pytest.raises(PermissionError,match="PAYLOAD_DENIED"):
        gate.execute_authorized_pixel_observation(
            authorization=auth,routing_decision=_routing(),payload=payload,
        )
    payload["kind"]="owner_video_mp4"
    payload["run_tts"]=True
    with pytest.raises(PermissionError,match="PAYLOAD_DENIED"):
        gate.execute_authorized_pixel_observation(
            authorization=auth,routing_decision=_routing(),payload=payload,
        )
