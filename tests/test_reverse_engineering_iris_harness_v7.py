from __future__ import annotations

from pathlib import Path

import pytest

from app.services import reverse_engineering_harness_service as harness
from app.services import reverse_engineering_iris_v7_service as iris
from app.services.harness_authorization_service import (
    issue_harness_authorization, revoke_harness_authorization,
)
from app.services.harness_capability_adapter import CapabilityAdapter
from app.services.harness_collaboration_service import TaskEnvelope
from app.services.harness_routing_policy_service import HarnessRoutingRequest, route_harness_request
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY


def _auth(root, output):
    return issue_harness_authorization(
        authorized_action="RESEARCH",
        subject=f"capability:{harness.IRIS_CAPABILITY_ID}",
        lineage={"allowed_media_roots":[str(root)],
                 "allowed_vision_output_roots":[str(output)]},
    )


def _route():
    return route_harness_request(HarnessRoutingRequest(
        intent="Capture trusted owned static HTML with scoped Iris",
        authorized_action="RESEARCH", required_capability_id=harness.IRIS_CAPABILITY_ID,
        domain="web-visual-observation", fallback_allowed=False,
        provider_required=False, learning_required=False,
    ))


def _fixture(tmp_path):
    root=tmp_path/"site"
    root.mkdir()
    output=tmp_path/"private-shots"
    output.mkdir()
    page=root/"owned.html"
    page.write_text("<!doctype html><html><body><h1>Owner page</h1></body></html>")
    return root,output,page


def _payload(src,out):
    return {"source_path":str(src),"output_path":str(out),
            "rights":"owned","viewport":"960x600","selector":"h1"}


def test_iris_registered_without_direct_mcp_or_authority():
    record=GLOBAL_CAPABILITY_REGISTRY.get(harness.IRIS_CAPABILITY_ID)
    assert record is not None and record.execution_enabled
    assert record.allowed_actions==("RESEARCH",)
    assert record.authority==record.publication_authority==record.memory_write=="NONE"
    assert record.routing_authority=="NONE"
    assert "mcp" not in record.allowed_tools


def test_actual_persisted_harness_routes_scoped_iris(tmp_path,monkeypatch):
    root,output,src=_fixture(tmp_path)
    auth=_auth(root,output)
    monkeypatch.setenv("BR_IRIS_PINNED_BIN","/opt/pinned/bin/iris")
    def fake_iris(**kwargs):
        assert kwargs["source_path"]==src.resolve()
        assert kwargs["output_path"]==output/"screen.png"
        assert kwargs["iris_binary"]=="/opt/pinned/bin/iris"
        return {"schema_version":"BRIrisVisionObservation/v1",
                "status":"MEASURED","image_sha256":"a"*64,
                "publication":"FORBIDDEN"}
    monkeypatch.setattr(iris,"capture_owned_static_page",fake_iris)
    result=CapabilityAdapter().execute(
        authorization=auth,
        task_envelope=TaskEnvelope(
            task_id="iris-v7-scoped-static",capability_id=harness.IRIS_CAPABILITY_ID,
            action="RESEARCH",objective="Capture owned page safely",
        ),
        routing_decision=_route(),
        payload=_payload(src,output/"screen.png"),
    ).result
    assert result["status"]=="PRIVATE_VISUAL_CAPTURED"
    assert result["production_mutation"] is False
    assert result["memory_write"]=="NOT_ATTEMPTED"
    assert result["owner_voice_access"]=="FORBIDDEN"


def test_iris_blocks_caller_override_private_paths_and_network_urls(tmp_path,monkeypatch):
    root,out,src=_fixture(tmp_path)
    auth=_auth(root,out)
    payload=_payload(src,out/"shot.png")
    payload["url"]="https://example.com"
    with pytest.raises(PermissionError,match="IRIS_HARNESS_PAYLOAD_SCHEMA_INVALID"):
        harness.execute_authorized_iris_capture(
            authorization=auth,routing_decision=_route(),payload=payload)
    payload=_payload(src,out/"shot.png")
    payload["rights"]="observation_only"
    with pytest.raises(PermissionError,match="IRIS_HARNESS_ONLY_OWNED_STATIC_PAGES"):
        harness.execute_authorized_iris_capture(
            authorization=auth,routing_decision=_route(),payload=payload)
    payload=_payload(src,tmp_path/"outside.png")
    with pytest.raises(PermissionError,match="IRIS_HARNESS_OUTPUT_OUTSIDE_PRIVATE_SCOPE"):
        harness.execute_authorized_iris_capture(
            authorization=auth,routing_decision=_route(),payload=payload)


def test_iris_rejects_symlinked_source_and_revoked_authorization(tmp_path):
    root,out,src=_fixture(tmp_path)
    auth=_auth(root,out)
    link=root/"linked.html"
    link.symlink_to(src)
    with pytest.raises(PermissionError,match="SYMLINK"):
        harness.execute_authorized_iris_capture(
            authorization=auth,routing_decision=_route(),
            payload=_payload(link,out/"shot.png"))
    revoke_harness_authorization(auth)
    with pytest.raises(PermissionError):
        harness.execute_authorized_iris_capture(
            authorization=auth,routing_decision=_route(),
            payload=_payload(src,out/"shot.png"))


def test_iris_requires_pinned_binary_after_path_scope(tmp_path,monkeypatch):
    root,out,src=_fixture(tmp_path)
    auth=_auth(root,out)
    monkeypatch.delenv("BR_IRIS_PINNED_BIN",raising=False)
    with pytest.raises(PermissionError,match="IRIS_HARNESS_PINNED_BINARY_REQUIRED"):
        harness.execute_authorized_iris_capture(
            authorization=auth,routing_decision=_route(),
            payload=_payload(src,out/"shot.png"))
