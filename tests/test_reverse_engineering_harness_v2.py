from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.harness_authorization_service import (
    issue_harness_authorization, revoke_harness_authorization,
)
from app.services.harness_capability_adapter import CapabilityAdapter
from app.services.harness_collaboration_service import TaskEnvelope
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest, route_harness_request,
)
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services import reverse_engineering_harness_service as harness
from app.services import reverse_engineering_forensics_service as forensic
from app.services.reverse_engineering_media_service import ObservationError


def _route(capability_id, domain):
    return route_harness_request(HarnessRoutingRequest(
        intent="Professional evidence-only reverse engineering",
        authorized_action="RESEARCH", required_capability_id=capability_id,
        domain=domain, fallback_allowed=False, provider_required=False,
        learning_required=False,
    ))


def _auth(capability_id, root: Path):
    return issue_harness_authorization(
        authorized_action="RESEARCH",
        subject=f"capability:{capability_id}",
        lineage={"allowed_media_roots": [str(root)]},
    )


def _media(tmp_path: Path):
    video = tmp_path / "owned.mp4"
    video.write_bytes(b"local-forensic-target")
    return video


def test_registry_routes_both_readonly_capabilities():
    for cid, domain in [
        (harness.MEDIA_CAPABILITY_ID, "audiovisual-analysis"),
        (harness.REA_CAPABILITY_ID, "software-investigation"),
    ]:
        record = GLOBAL_CAPABILITY_REGISTRY.get(cid)
        assert record.availability == "AVAILABLE"
        assert record.execution_enabled
        assert record.allowed_actions == ("RESEARCH",)
        assert record.publication_authority == "NONE"
        assert record.memory_write == "NONE"
        assert record.authority == "NONE"
        assert record.side_effect_class == "READ_ONLY"
        assert record.default_write_scope == ()
        assert _route(cid, domain).selected_capability_id == cid


def test_harness_adapter_invokes_scoped_media_executor_with_real_persisted_auth(tmp_path, monkeypatch):
    source = _media(tmp_path)
    auth = _auth(harness.MEDIA_CAPABILITY_ID, tmp_path)
    decision = _route(harness.MEDIA_CAPABILITY_ID, "audiovisual-analysis")
    observed = {}
    def fake_forensics(path, **kwargs):
        observed.update(path=str(path), **kwargs)
        return {"schema_version": "BRAudiovisualForensics/v2", "evidence_sha256": "0" * 64}
    monkeypatch.setattr(harness, "analyze_forensics", fake_forensics)
    result = CapabilityAdapter().execute(
        authorization=auth,
        task_envelope=TaskEnvelope(
            task_id="reverse-observe-001", capability_id=harness.MEDIA_CAPABILITY_ID,
            action="RESEARCH", objective="Read local authorized video evidence",
        ),
        routing_decision=decision,
        payload={"source_path": str(source), "rights": "owned"},
    )
    assert result.authorization_id == auth.authorization_id
    assert result.result["status"] == "MEASURED"
    assert result.result["production_mutation"] is False
    assert observed["path"] == str(source.resolve())
    assert observed["rights"] == "owned"


@pytest.mark.parametrize("case", ["missing_auth", "wrong_action", "replayed", "outside_root", "forged_root", "forbidden_field", "relative_path"])
def test_media_rejects_unauthorized_access(tmp_path, monkeypatch, case):
    safe = tmp_path / "safe"
    safe.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    source = _media(outside)
    allowed_source = _media(safe)
    auth = _auth(harness.MEDIA_CAPABILITY_ID, safe)
    decision = _route(harness.MEDIA_CAPABILITY_ID, "audiovisual-analysis")
    monkeypatch.setattr(harness, "analyze_forensics", lambda *_args, **_kwargs: pytest.fail("unauthorized media decoded"))
    arguments = {"source_path": str(source), "rights": "owned"}
    active_auth = auth
    if case == "missing_auth":
        active_auth = "unregistered-authorization-id"
        arguments["source_path"] = str(allowed_source)
    elif case == "wrong_action":
        active_auth = issue_harness_authorization(
            authorized_action="PUBLICATION", subject=f"capability:{harness.MEDIA_CAPABILITY_ID}",
            lineage={"allowed_media_roots": [str(safe)]},
        )
        arguments["source_path"] = str(allowed_source)
    elif case == "replayed":
        revoke_harness_authorization(auth)
        arguments["source_path"] = str(allowed_source)
    elif case == "forged_root":
        arguments["allowed_media_roots"] = [str(outside)]
    elif case == "forbidden_field":
        arguments["runtime_activation"] = True
        arguments["source_path"] = str(allowed_source)
    elif case == "relative_path":
        arguments["source_path"] = "owned.mp4"
    with pytest.raises(PermissionError):
        harness.execute_authorized_media_observation(
            authorization=active_auth, routing_decision=decision, payload=arguments
        )


def test_private_media_path_is_rejected_even_if_root_allows_it(tmp_path, monkeypatch):
    root = tmp_path / "evidence"
    private = root / "owner_voice"
    private.mkdir(parents=True)
    reference = private / "reference.wav"
    reference.write_bytes(b"private-biometric-ref")
    auth = _auth(harness.MEDIA_CAPABILITY_ID, root)
    decision = _route(harness.MEDIA_CAPABILITY_ID, "audiovisual-analysis")
    monkeypatch.setattr(harness, "analyze_forensics", lambda *_a, **_k: pytest.fail("read private reference"))
    with pytest.raises(PermissionError, match="PRIVATE_PATH"):
        harness.execute_authorized_media_observation(
            authorization=auth, routing_decision=decision,
            payload={"source_path": str(reference), "rights": "owned"},
        )


def test_loudnorm_parse_uses_input_not_normalized_output(tmp_path, monkeypatch):
    target = _media(tmp_path)
    def fake_cmd(args, *, timeout):
        assert "loudnorm=I=-23:TP=-2:LRA=7:print_format=json" in args
        return subprocess.CompletedProcess(
            args, 0, stdout="", stderr='[Parsed_loudnorm]\n{"input_i":"-18.27","input_tp":"-1.72","input_lra":"2.10","input_thresh":"-29.70","output_i":"-23.00"}',
        )
    monkeypatch.setattr(forensic, "_command", fake_cmd)
    result = forensic._loudness(target, timeout=10)
    assert result["metrics"]["input_i"]["value"] == -18.27
    assert result["metrics"]["input_tp"]["value"] == -1.72
    assert "output_i" not in result["metrics"]


def test_silence_black_and_freeze_are_technical_events(tmp_path, monkeypatch):
    target = _media(tmp_path)
    logs = {
        "silencedetect": "[silencedetect] silence_start: 1.2\n[silencedetect] silence_end: 2.4 | silence_duration: 1.2",
        "blackdetect": "[blackdetect] black_start:0.1 black_end:0.6 black_duration:0.5",
        "freezedetect": "[freezedetect] lavfi.freezedetect.freeze_start: 1.0\n[freezedetect] lavfi.freezedetect.freeze_end: 3.0",
    }
    def fake_cmd(args, *, timeout):
        value = next((x for x in logs if x in " ".join(args)), "none")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr=logs.get(value, ""))
    monkeypatch.setattr(forensic, "_command", fake_cmd)
    assert forensic._silences(target, timeout=5)["detected_duration_seconds"] == 1.2
    rows = forensic._video_events(target, timeout=5)
    assert rows["black_segments"][0]["duration"] == 0.5
    assert rows["freeze_start_seconds"] == [1.0]
    assert rows["freeze_end_seconds"] == [3.0]


def test_metrics_missing_does_not_fake_loudness(tmp_path, monkeypatch):
    target = _media(tmp_path)
    monkeypatch.setattr(forensic, "_command", lambda args, **kw: subprocess.CompletedProcess(args, 0, stderr=""))
    with pytest.raises(ObservationError, match="LOUDNESS_UNAVAILABLE"):
        forensic._loudness(target, timeout=10)


def test_forensics_makes_no_claim_of_speaker_identity(tmp_path, monkeypatch):
    target = _media(tmp_path)
    monkeypatch.setattr(forensic, "analyze_reference", lambda *_args, **_kwargs: {
        "evidence_sha256": "b" * 64,
        "source": {"sha256": "a" * 64, "rights": "owned"},
        "evidence": {
            "container_and_streams": {"duration_seconds": 3.0, "streams": [{"codec_type": "audio"}]},
            "script_timing": {"status": "NOT_PROVIDED"},
        },
    })
    monkeypatch.setattr(forensic, "_loudness", lambda *_args, **_kw: {"status": "MEASURED", "metrics": {}})
    monkeypatch.setattr(forensic, "_silences", lambda *_args, **_kw: {"status": "MEASURED"})
    r = forensic.analyze_forensics(target, rights="owned")
    assert r["video"]["status"] == "NOT_APPLICABLE"
    assert r["interpretation"]["speaker_identity_verified"] is False
    assert r["interpretation"]["pronunciation_verified"] is False
    assert r["interpretation"]["human_approval_required"] is True


def test_differential_is_descriptive_and_never_approves_quality():
    original = {
        "schema_version": forensic.SCHEMA,
        "source": {"rights": "observation_only", "sha256": "a" * 64},
        "duration_seconds": 10,
        "audio": {"loudness": {"metrics": {"input_i": {"value": -20.0}}}},
    }
    candidate = {
        "schema_version": forensic.SCHEMA,
        "source": {"rights": "owned", "sha256": "b" * 64},
        "duration_seconds": 11,
        "audio": {"loudness": {"metrics": {"input_i": {"value": -19.0}}}},
    }
    comparison = forensic.differential_observation(original, candidate)
    assert comparison["metric_deltas_candidate_minus_reference"]["input_i"] == 1.0
    assert comparison["metric_deltas_candidate_minus_reference"]["duration_seconds"] == 1.0
    assert comparison["quality_pass"] is None
    assert comparison["human_review_required"] is True


def test_software_static_can_only_run_pinned_rea_inside_scope(tmp_path, monkeypatch):
    root = tmp_path / "authorized"
    source = root / "sample-javascript-app"
    source.mkdir(parents=True)
    (source / "index.js").write_text("export const sum = (a,b) => a+b;", encoding="utf-8")
    prefix = tmp_path / "rea-6.0.0"
    target = prefix / "node_modules" / "rea-agents" / "scripts"
    target.mkdir(parents=True)
    (target / "rea.mjs").write_text("cli stub", encoding="utf-8")
    bin_dir = prefix / "node_modules" / ".bin"
    bin_dir.mkdir()
    (bin_dir / "rea").symlink_to("../rea-agents/scripts/rea.mjs")
    monkeypatch.setenv("BR_REA_INSTALL_PREFIX", str(prefix))
    calls = []
    def fake_run(args, **kwargs):
        calls.append(args)
        if "--version" in args:
            return subprocess.CompletedProcess(args, 0, stdout="6.0.0\n")
        return subprocess.CompletedProcess(args, 0, stdout='{"evidence":[],"status":"ok"}')
    monkeypatch.setattr(harness.subprocess, "run", fake_run)
    auth = _auth(harness.REA_CAPABILITY_ID, root)
    decision = _route(harness.REA_CAPABILITY_ID, "software-investigation")
    result = harness.execute_authorized_software_observation(
        authorization=auth, routing_decision=decision,
        payload={"source_path": str(source), "rights": "owned"},
    )
    assert len(calls) == 2
    assert "analyze-javascript-application" in calls[1]
    assert result["evidence"]["rea_version"] == "6.0.0"
    assert "cli stub" not in json.dumps(result)
    assert result["production_mutation"] is False
