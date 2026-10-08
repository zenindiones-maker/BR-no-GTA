from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest
from PIL import Image,ImageDraw

from app.services import br_harness_sensory_pixel_v12 as pixels
from app.services import br_harness_sensory_authorization_v12 as gate
from app.services.harness_authorization_service import issue_harness_authorization,revoke_harness_authorization
from app.services.harness_capability_adapter import CapabilityAdapter
from app.services.harness_collaboration_service import TaskEnvelope
from app.services.harness_routing_policy_service import HarnessRoutingRequest,route_harness_request
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY


def _paths(root):
    owned=root/"owned-pixel-observations"
    owned.mkdir(mode=0o700)
    scratch=owned/"frames"
    scratch.mkdir(mode=0o700)
    return owned,scratch


def _screenshot(path:Path):
    image=Image.new("RGB",(320,180),(18,44,90))
    ImageDraw.Draw(image).rectangle((20,30,90,80),fill=(240,50,20))
    image.save(path,format="PNG")


def _auth(root):
    return issue_harness_authorization(
        authorized_action="RESEARCH",
        subject=f"capability:{gate.CAPABILITY_ID}",
        lineage={"allowed_media_roots":[str(root)]},
    )


def _route():
    return route_harness_request(HarnessRoutingRequest(
        intent="Observe original bounded visual pixels",
        authorized_action="RESEARCH",
        domain="production-multimodal-observation",
        required_capability_id=gate.CAPABILITY_ID,
        provider_required=False,
        fallback_allowed=False,
        learning_required=False,
    ))


def _payload(media,scratch,kind="owner_screenshot_png"):
    return {"source_path":str(media),"rights":"owned",
            "kind":kind,"private_workspace":str(scratch)}


def test_owned_png_is_actually_decoded_with_measured_rgb(tmp_path):
    owned,scratch=_paths(tmp_path)
    png=owned/"screenshot.png"
    _screenshot(png)
    receipt=pixels.inspect_pixel_evidence(png,kind="owner_screenshot_png",
                                         private_workspace=scratch)
    assert receipt["status"]=="PIXELS_DECODED_AND_MEASURED"
    assert receipt["sample_count"]==1
    assert receipt["frames"][0]["dimensions"]==[320,180]
    assert receipt["frames"][0]["pixels_decoded"] is True
    assert receipt["frames"][0]["png_sha256"]==pixels._sha(png)
    assert receipt["frames"][0]["rgb_mean"][0]>18
    assert receipt["semantic_scene_understood"] is False
    assert receipt["raw_media_exported"] is False
    assert receipt["publish_authorized"] is False
    assert not list(scratch.iterdir())


def test_authorized_harness_receives_only_measured_evidence(tmp_path):
    owned,scratch=_paths(tmp_path)
    path=owned/"owner.png"
    _screenshot(path)
    auth=_auth(owned)
    capability=GLOBAL_CAPABILITY_REGISTRY.get(gate.CAPABILITY_ID)
    assert capability is not None and capability.execution_enabled
    assert capability.authority==capability.memory_write==capability.publication_authority=="NONE"
    result=CapabilityAdapter().execute(
        authorization=auth,
        task_envelope=TaskEnvelope(
            task_id="sensory-v12-real-pixel-smoke",
            capability_id=gate.CAPABILITY_ID,
            action="RESEARCH",
            objective="Measure owned PNG pixels without inventing visual content",
        ),
        routing_decision=_route(),
        payload=_payload(path,scratch),
    ).result
    assert result["status"]=="OBSERVED_PIXEL_EVIDENCE_ONLY"
    assert result["evidence"]["sample_count"]==1
    assert result["agents_can_consume_private_frames"] is False
    assert result["scene_semantics_certified"] is False
    assert result["publication"]=="FORBIDDEN"
    revoke_harness_authorization(auth)
    with pytest.raises(PermissionError):
        gate.execute_authorized_pixel_observation(
            authorization=auth,routing_decision=_route(),
            payload=_payload(path,scratch),
        )


def test_scope_private_voice_and_unowned_sources_are_rejected(tmp_path):
    owned,scratch=_paths(tmp_path)
    png=owned/"screen.png"
    _screenshot(png)
    auth=_auth(owned)
    with pytest.raises(PermissionError,match="PAYLOAD_DENIED"):
        gate.execute_authorized_pixel_observation(
            authorization=auth,routing_decision=_route(),
            payload={**_payload(png,scratch),"rights":"observation_only"},
        )
    with pytest.raises(PermissionError,match="PAYLOAD_DENIED"):
        gate.execute_authorized_pixel_observation(
            authorization=auth,routing_decision=_route(),
            payload={**_payload(png,scratch),"publish":True},
        )
    dangerous=owned/"owner_voice"
    dangerous.mkdir(mode=0o700)
    bad=dangerous/"secret.png"
    _screenshot(bad)
    with pytest.raises(PermissionError,match="PRIVATE_MEDIA_FORBIDDEN"):
        gate.execute_authorized_pixel_observation(
            authorization=auth,routing_decision=_route(),
            payload=_payload(bad,scratch),
        )
    link=owned/"linked.png"
    link.symlink_to(png)
    with pytest.raises(PermissionError,match="NONLINK_REQUIRED"):
        gate.execute_authorized_pixel_observation(
            authorization=auth,routing_decision=_route(),
            payload=_payload(link,scratch),
        )


def test_private_workspace_must_reject_insecure_permissions(tmp_path):
    owned,scratch=_paths(tmp_path)
    png=owned/"source.png"
    _screenshot(png)
    scratch.chmod(0o755)
    with pytest.raises(PermissionError,match="WORKSPACE_PERMISSIONS_INVALID"):
        pixels.inspect_pixel_evidence(png,kind="owner_screenshot_png",
                                      private_workspace=scratch)


@pytest.mark.skipif(not __import__("shutil").which("ffmpeg"),reason="ffmpeg unavailable")
def test_real_video_extracts_distinct_pixels_and_audio_metadata(tmp_path):
    owned,scratch=_paths(tmp_path)
    mp4=owned/"owned.mp4"
    cmd=[
        "ffmpeg","-nostdin","-hide_banner","-loglevel","error",
        "-f","lavfi","-i","testsrc2=size=320x180:rate=30:duration=3",
        "-f","lavfi","-i","sine=frequency=350:sample_rate=48000:duration=3",
        "-shortest","-c:v","libx264","-preset","ultrafast","-threads","2",
        "-pix_fmt","yuv420p","-c:a","aac","-ar","48000","-ac","2",
        str(mp4),
    ]
    subprocess.run(cmd,check=True,capture_output=True,timeout=60)
    receipt=pixels.inspect_pixel_evidence(mp4,kind="owner_video_mp4",
                                         private_workspace=scratch)
    assert receipt["status"]=="PIXELS_DECODED_AND_MEASURED"
    assert receipt["sample_count"]==4
    assert receipt["media_metadata"]["audio_track_count"]==1
    assert receipt["media_metadata"]["video_codec"]=="h264"
    assert all(x["pixels_decoded"] for x in receipt["frames"])
    assert len(list(scratch.glob("owner-visual-frame-*.png")))==4
    assert all(x["png_sha256"] for x in receipt["frames"])
    assert any((x["delta_from_previous_64x64"] or 0)>0 for x in receipt["frames"])
    assert receipt["full_duration_reviewed"] is False
    assert receipt["semantic_scene_understood"] is False
    print("BR_V12_REAL_FFMPEG_VIDEO_PIXELS_OBSERVED=PASS")
    print("BR_V12_UNPROVEN_SEMANTIC_VISION=DECLARED")
