"""Luiz aprova (ou rejeita) o roteiro pelo celular: Actions > "Aprovar roteiro".

Sem esse caminho nenhum roteiro do agente editorial chega a aprovado_humano e o
render (que exige aprovação) nunca começa.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from scripts import script_first_gate as g

ROOT = Path(__file__).resolve().parents[1]
WF = ROOT / ".github/workflows/script-approval.yml"


def _draft(root: Path) -> dict:
    result = {"production_plan": {"scenes": [
        {"narration": "Fato oficial um da Rockstar.", "duration_seconds": 6},
        {"narration": "Fato oficial dois da Rockstar.", "duration_seconds": 6}]},
        "script": {"id": 7, "title": "Guia"},
        "sources": [{"url": "https://www.rockstargames.com/VI"}]}
    import os
    os.environ.pop("BR_EDITORIAL_VERIFIED_SOURCES", None)
    return g.write_editorial_script(result, root=root)


def _fake_db(monkeypatch):
    class C:
        def execute(self, *a):
            return self
        def commit(self):
            pass
        def close(self):
            pass
    import app.database.connection as c
    monkeypatch.setattr(c, "get_connection", lambda: C())


def test_cli_approve_sets_luiz_approval_bound_to_sha(tmp_path, monkeypatch, capsys):
    _fake_db(monkeypatch)
    rec = _draft(tmp_path)
    assert rec["status"] == "editorial_ok" and rec["approval"] is None
    rc = g.main(["approve", "--root", str(tmp_path), "--script-id", rec["script_id"],
                 "--script-sha256", rec["sha256"], "--approver", "Luiz",
                 "--github-actor", "zenindiones-maker"])
    assert rc == 0
    saved = json.loads((tmp_path / rec["script_id"] / "roteiro.json").read_text())
    assert saved["status"] == "aprovado_humano"
    assert saved["approval"]["approved_by"] == "Luiz"
    assert saved["approval"]["approved_sha256"] == rec["sha256"]
    assert saved["approval"]["approved_at"]
    assert saved["approval"]["github_actor"] == "zenindiones-maker"
    # Depois de aprovado, o gate do render passa.
    assert g.check(script_id=rec["script_id"], script_sha256=rec["sha256"], root=tmp_path)["SCRIPT_FIRST_GATE"] == "PASS"


def test_cli_approve_refuses_wrong_sha_or_non_owner(tmp_path, monkeypatch):
    _fake_db(monkeypatch)
    rec = _draft(tmp_path)
    assert g.main(["approve", "--root", str(tmp_path), "--script-id", rec["script_id"],
                   "--script-sha256", "0" * 64, "--approver", "Luiz"]) == 2
    assert g.main(["approve", "--root", str(tmp_path), "--script-id", rec["script_id"],
                   "--script-sha256", rec["sha256"], "--approver", "agente"]) == 2
    saved = json.loads((tmp_path / rec["script_id"] / "roteiro.json").read_text())
    assert saved["status"] == "editorial_ok"


def test_cli_reject_records_reason(tmp_path, monkeypatch):
    _fake_db(monkeypatch)
    rec = _draft(tmp_path)
    assert g.main(["reject", "--root", str(tmp_path), "--script-id", rec["script_id"],
                   "--script-sha256", rec["sha256"], "--approver", "Luiz", "--reason", "falta fonte"]) == 0
    saved = json.loads((tmp_path / rec["script_id"] / "roteiro.json").read_text())
    assert saved["status"] == "rejeitado"
    assert saved["rejection"]["reason"] == "falta fonte"


def test_approval_workflow_is_owner_only_least_privilege_and_injection_safe():
    wf = yaml.safe_load(WF.read_text(encoding="utf-8"))
    on = wf.get("on") or wf.get(True)
    inputs = on["workflow_dispatch"]["inputs"]
    assert {"editorial_run_id", "script_id", "script_sha256", "decisao"} <= set(inputs)
    assert set(on) == {"workflow_dispatch"}
    assert wf["permissions"] == {}
    (job,) = wf["jobs"].values()
    assert "github.actor == github.repository_owner" in job["if"]
    assert job["permissions"] == {"contents": "write", "actions": "read"}
    for step in job["steps"]:
        assert "${{ inputs." not in str(step.get("run", "")), step.get("name")
    text = WF.read_text(encoding="utf-8")
    assert "script_first_gate.py" in text and "^ep-[0-9a-z-]+$" in text and "^[0-9a-f]{64}$" in text
    assert "real-multi-agent-synergy-" in text


def test_private_upload_requires_script_first_lineage_before_oauth():
    up = ROOT / ".github/workflows/youtube-private-upload-worker.yml"
    wf = yaml.safe_load(up.read_text(encoding="utf-8"))
    steps = wf["jobs"]["upload-private"]["steps"]
    names = [s.get("name", "") for s in steps]
    dl = next(i for i, s in enumerate(steps)
              if "scene-decision-list-" in str((s.get("with") or {}).get("name", "")))
    gate = next(i for i, n in enumerate(names) if "roteiro aprovado" in n.lower())
    oauth = next(i for i, n in enumerate(names) if "OAuth" in n)
    assert dl < gate < oauth
    run = steps[gate]["run"]
    assert "script_first_gate.py check" in run
    assert "edl_sha256" in run
    assert "${{ inputs." not in run
