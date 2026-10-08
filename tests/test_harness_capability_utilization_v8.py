from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.harness_capability_utilization_v8 import (
    _hash, _collect_names, probe_rea_discovery, capability_utilization_report
)


@dataclass
class Stub:
    capability_id: str
    domain: str = "test"
    execution_enabled: bool = True
    available: bool = True
    allowed_actions: tuple[str,...] = ("RESEARCH",)
    cost_class: str = "FREE_NO_BILLING"


class Registry:
    def all(self):
        return [Stub("reverse-engineering.test-a"), Stub("reverse-engineering.test-b", execution_enabled=False)]


def test_inventory_distinguishes_registry_availability_from_execution_proof():
    report=capability_utilization_report(registry=Registry())
    assert report["registry_total"]==2
    assert report["declared_executor_count"]==1
    assert report["runtime_verified_count"]==0
    assert report["canonical_learning_changed"] is False
    assert report["capability_autorouting_changed"] is False
    assert report["focus_surfaces"]["iris"][0]["state"]=="LOCAL_MEASURED"
    assert report["evidence_sha256"] == _hash({k:v for k,v in report.items() if k!="evidence_sha256"})


def test_upstream_tool_names_are_sanitized_but_no_untrusted_text_is_emitted():
    obj={"tools":[{"name":"native_pseudocode","description":"TOKEN=SECRET/DO_NOT_LOG"},
                  {"name":"https://secret.local/?key=123"}],
         "nested":{"entries":[{"capability_id":"source_map"}]}}
    assert _collect_names(obj)==["native_pseudocode","source_map"]


def test_rea_discovery_probes_real_executable_commands_without_claiming_provider_ready(tmp_path,monkeypatch):
    binary=tmp_path/"rea"
    binary.write_text("#!/bin/sh\nexit 0\n")
    binary.chmod(0o700)
    calls=[]
    def fake_run(argv,**kwargs):
        calls.append(argv[1:])
        if argv[1:]==["--version"]:
            return SimpleNamespace(returncode=0,stdout="6.0.0\n")
        if argv[1:]==["doctor","--json"]:
            return SimpleNamespace(returncode=1,stdout='{"status":"blocked","provider":"ghidra"}')
        return SimpleNamespace(returncode=0,stdout='{"tools":[{"name":"native_overview"}]}')
    import app.services.harness_capability_utilization_v8 as mod
    monkeypatch.setattr(mod.subprocess,"run",fake_run)
    probe=probe_rea_discovery(binary)
    assert calls==[["--version"],["capabilities","--json"],["providers","--json"],["doctor","--json"]]
    assert probe["native_provider_ready"] is False
    assert probe["catalog"]["capabilities"]["readiness"]=="DISCOVERY_SUCCEEDED"
    assert probe["catalog"]["doctor"]["readiness"]=="DIAGNOSTIC_INCOMPLETE_OR_UNAVAILABLE"
    report=capability_utilization_report(registry=Registry(),rea_probe=probe)
    focus={x["operation"]:x["state"] for x in report["focus_surfaces"]["rea"]}
    assert focus["capability_inventory"]=="DISCOVERY_PROBED_NOT_EXECUTION_PROOF"
    assert focus["provider_doctor"]=="DIAGNOSTIC_INCOMPLETE_OR_UNAVAILABLE"


def test_rea_pin_mismatch_fails_closed(tmp_path,monkeypatch):
    binary=tmp_path/"rea"
    binary.write_text("fake")
    binary.chmod(0o700)
    import app.services.harness_capability_utilization_v8 as mod
    monkeypatch.setattr(mod.subprocess,"run",lambda *_args,**_kwargs:SimpleNamespace(returncode=0,stdout="7.0.0\n"))
    with pytest.raises(ValueError,match="REA_DISCOVERY_VERSION_PIN_MISMATCH"):
        probe_rea_discovery(binary)


def test_malformed_or_extra_large_discovery_never_generates_capability_claims(tmp_path,monkeypatch):
    binary=tmp_path/"rea"
    binary.write_text("fake")
    binary.chmod(0o700)
    def run(args,**kwargs):
        if args[1:]==["--version"]:
            return SimpleNamespace(returncode=0,stdout="6.0.0\n")
        return SimpleNamespace(returncode=0,stdout="not json")
    import app.services.harness_capability_utilization_v8 as mod
    monkeypatch.setattr(mod.subprocess,"run",run)
    probe=probe_rea_discovery(binary)
    assert all(x["readiness"]=="DIAGNOSTIC_INCOMPLETE_OR_UNAVAILABLE" for x in probe["catalog"].values())
    with pytest.raises(ValueError,match="REA_DISCOVERY_RECEIPT_SCHEMA_INVALID"):
        capability_utilization_report(registry=Registry(),rea_probe={"schema_version":"fake"})



def test_planner_never_authorizes_risky_rea_native_or_iris_network():
    from app.services.harness_capability_utilization_v8 import propose_next_utilization_probe
    report=capability_utilization_report(registry=Registry())
    for tool,operation,action in [
        ("rea","native_ghidra","ATTEST_PROVIDER_DOCTOR"),
        ("iris","live_public_pages","AUDIT_NETWORK_ISOLATION"),
        ("iris","persistent_mcp_server","REQUIRE_NEW_OWNER_POLICY_APPROVAL"),
        ("iris","full_page_capture","RUN_LOCAL_SCOPED_FIXTURE"),
    ]:
        proposed=propose_next_utilization_probe(report=report,tool=tool,operation=operation)
        assert proposed["next_action"]==action
        assert proposed["execution_authorized"] is False
        assert proposed["routing_changed"] is False
        assert proposed["memory_written"] is False
        assert proposed["harness_authorization_required"] is True


def test_proposal_refuses_modified_report_and_unknown_operation():
    from app.services.harness_capability_utilization_v8 import propose_next_utilization_probe
    report=capability_utilization_report(registry=Registry())
    altered=json.loads(json.dumps(report))
    altered["runtime_verified_count"]=170
    with pytest.raises(ValueError,match="TAMPERED"):
        propose_next_utilization_probe(report=altered,tool="rea",operation="native_ghidra")
    assert propose_next_utilization_probe(report=report,tool="rea",operation="rootkit_launch")["status"]=="BLOCKED_UNKNOWN_OPERATION"
