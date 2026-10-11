"""Diretriz do proprietário (Luiz, 11/10/2026): um vídeo por vez, roteiros
distintos, vídeo somente a partir de roteiro aprovado pelo agente editorial e
pelo humano. Estes testes travam o render fail-closed."""
import json
import re
import sqlite3
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WF = ROOT / ".github" / "workflows"
VIDEO_WORKFLOWS = [
    "video-a-current-product-e2e.yml",
    "new-video-current-render-resume.yml",
    "new-video-e2e-benchmark.yml",
    "run001-e2e-canary.yml",
]

TEXT_A = (
    "A Rockstar Games confirmou oficialmente que GTA VI chega em 19 de novembro. "
    "Neste episódio analisamos cada informação publicada no site oficial, os dois trailers "
    "lançados pela Rockstar e o que a Take-Two declarou aos investidores sobre o lançamento. "
    "Leonida, Vice City e os protagonistas Jason e Lucia aparecem nos materiais oficiais."
)
TEXT_B = (
    "Este episódio é sobre a música e as rádios nos jogos da série. Falamos de como a "
    "trilha sonora sempre definiu a identidade de cada cidade, dos locutores memoráveis, "
    "das propagandas satíricas e do que a Rockstar já mostrou oficialmente sobre o som "
    "do novo jogo nos trailers, sem qualquer especulação ou vazamento."
)


def _gate():
    from scripts import script_first_gate
    return script_first_gate


def _write(root, script_id, text, status="aprovado_humano", approve=True, sources=None, sha=None):
    g = _gate()
    d = root / script_id
    d.mkdir(parents=True)
    (d / "roteiro.md").write_text(text, encoding="utf-8")
    digest = g.script_sha256(text)
    rec = {
        "schema": "br-roteiro/v1",
        "script_id": script_id,
        "episode_slug": script_id,
        "status": status,
        "author_agent": "GTA6 Master Agent",
        "sha256": sha or digest,
        "scenes": [{"order": 1, "narrative_block": "unico", "visual_type": "official",
                    "visual_description": "material oficial", "narration": text,
                    "duration_seconds": 10.0}],
        "sources": sources if sources is not None else [
            {"url": "https://www.rockstargames.com/VI", "kind": "official"}],
        "approval": {"approved_by": "Luiz", "approved_at": "2026-10-11T14:00:00-03:00",
                     "approved_sha256": digest} if approve else None,
    }
    (d / "roteiro.json").write_text(json.dumps(rec), encoding="utf-8")
    return digest


@pytest.fixture
def roteiros(tmp_path):
    return tmp_path / "roteiros"


def test_gate_refuses_missing_script(roteiros):
    g = _gate()
    roteiros.mkdir()
    with pytest.raises(g.ScriptGateError, match="SCRIPT_NOT_FOUND"):
        g.check(script_id="ep-001", script_sha256="0" * 64, root=roteiros)


def test_gate_refuses_unapproved_script(roteiros):
    g = _gate()
    sha = _write(roteiros, "ep-001", TEXT_A, status="editorial_ok", approve=False)
    with pytest.raises(g.ScriptGateError, match="SCRIPT_NOT_APPROVED"):
        g.check(script_id="ep-001", script_sha256=sha, root=roteiros)


def test_gate_refuses_hash_mismatch(roteiros):
    g = _gate()
    _write(roteiros, "ep-001", TEXT_A)
    with pytest.raises(g.ScriptGateError, match="SCRIPT_SHA_MISMATCH"):
        g.check(script_id="ep-001", script_sha256="f" * 64, root=roteiros)


def test_gate_refuses_approval_for_other_hash(roteiros):
    g = _gate()
    sha = _write(roteiros, "ep-001", TEXT_A)
    rec = json.loads((roteiros / "ep-001/roteiro.json").read_text())
    rec["approval"]["approved_sha256"] = "a" * 64
    (roteiros / "ep-001/roteiro.json").write_text(json.dumps(rec))
    with pytest.raises(g.ScriptGateError, match="APPROVAL_SHA_MISMATCH"):
        g.check(script_id="ep-001", script_sha256=sha, root=roteiros)


def test_gate_requires_official_sources(roteiros):
    g = _gate()
    sha = _write(roteiros, "ep-001", TEXT_A, sources=[{"url": "https://reddit.com/r/x", "kind": "rumor"}])
    with pytest.raises(g.ScriptGateError, match="OFFICIAL_SOURCES_REQUIRED"):
        g.check(script_id="ep-001", script_sha256=sha, root=roteiros)


def test_gate_accepts_approved_unique_script(roteiros):
    g = _gate()
    sha = _write(roteiros, "ep-001", TEXT_A)
    result = g.check(script_id="ep-001", script_sha256=sha, root=roteiros)
    assert result["SCRIPT_FIRST_GATE"] == "PASS"
    assert result["originality"]["max_reuse_percent"] == 0.0


def test_gate_refuses_duplicate_script_sha(roteiros):
    g = _gate()
    _write(roteiros, "ep-001", TEXT_A, status="entregue")
    sha = _write(roteiros, "ep-002", TEXT_A)
    with pytest.raises(g.ScriptGateError, match="DUPLICATE_SCRIPT"):
        g.check(script_id="ep-002", script_sha256=sha, root=roteiros)


def test_gate_refuses_high_shingle_reuse(roteiros):
    g = _gate()
    _write(roteiros, "ep-001", TEXT_A, status="entregue")
    disguised = TEXT_A + " Inscreva-se no canal para acompanhar as próximas novidades oficiais."
    sha = _write(roteiros, "ep-002", disguised)
    with pytest.raises(g.ScriptGateError, match="SCRIPT_REUSE"):
        g.check(script_id="ep-002", script_sha256=sha, root=roteiros)


def test_gate_accepts_distinct_second_script(roteiros):
    g = _gate()
    _write(roteiros, "ep-001", TEXT_A, status="entregue")
    sha = _write(roteiros, "ep-002", TEXT_B)
    assert g.check(script_id="ep-002", script_sha256=sha, root=roteiros)["SCRIPT_FIRST_GATE"] == "PASS"


def test_gate_refuses_when_another_script_in_production(roteiros):
    g = _gate()
    _write(roteiros, "ep-001", TEXT_A, status="em_producao")
    sha = _write(roteiros, "ep-002", TEXT_B)
    with pytest.raises(g.ScriptGateError, match="ANOTHER_VIDEO_IN_PRODUCTION"):
        g.check(script_id="ep-002", script_sha256=sha, root=roteiros)


def test_status_transitions_require_luiz_record():
    g = _gate()
    rec = {"status": "rascunho", "sha256": "a" * 64}
    with pytest.raises(g.ScriptGateError, match="INVALID_TRANSITION"):
        g.transition(rec, "aprovado_humano")
    rec = g.transition(rec, "editorial_ok", actor="GTA6 Master Agent")
    with pytest.raises(g.ScriptGateError, match="HUMAN_APPROVAL_REQUIRED"):
        g.transition(rec, "aprovado_humano", actor="GTA6 Master Agent")
    rec = g.transition(rec, "aprovado_humano", actor="Luiz", approved_at="2026-10-11T14:00:00-03:00")
    assert rec["approval"]["approved_sha256"] == "a" * 64
    with pytest.raises(g.ScriptGateError, match="EDITORIAL_AGENT_REQUIRED"):
        g.transition({"status": "rascunho", "sha256": "b" * 64}, "editorial_ok", actor="Grok")


def test_resume_checkpoint_must_match_script_sha():
    g = _gate()
    with pytest.raises(g.ScriptGateError, match="CHECKPOINT_SCRIPT_MISMATCH"):
        g.checkpoint_matches({"script_id": "ep-001", "script_sha256": "a" * 64}, "ep-001", "b" * 64)
    with pytest.raises(g.ScriptGateError, match="CHECKPOINT_SCRIPT_MISMATCH"):
        g.checkpoint_matches({}, "ep-001", "a" * 64)
    g.checkpoint_matches({"script_id": "ep-001", "script_sha256": "a" * 64}, "ep-001", "a" * 64)


def test_render_job_service_enforces_gate(monkeypatch, roteiros):
    from app.services import render_job_service
    monkeypatch.setenv("BR_SCRIPT_FIRST_GATE_ENFORCE", "1")
    monkeypatch.setenv("BR_ROTEIROS_ROOT", str(roteiros))
    roteiros.mkdir()
    spec = {"content_item_id": 1, "script_id": "ep-001", "idea_id": 1, "objective": "x",
            "format": "longform", "estimated_duration_seconds": 1500, "scenes": [],
            "audio_requirements": [], "visual_requirements": [],
            "render": {"resolution": "1920x1080", "fps": 30, "aspect_ratio": "16:9",
                       "container": "mp4", "video_codec": "h264", "audio_codec": "aac"}}
    with pytest.raises(Exception, match="SCRIPT_SHA256_REQUIRED|SCRIPT_NOT_FOUND"):
        render_job_service.create_render_job(spec)


def _wf(name):
    return yaml.safe_load((WF / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", VIDEO_WORKFLOWS)
def test_video_workflows_share_global_concurrency(name):
    c = _wf(name).get("concurrency") or {}
    assert c.get("group") == "br-video-production", name
    assert c.get("cancel-in-progress") is False, name


def test_render_worker_single_global_render_group():
    # Grupo irmão: o render é disparado pelo orquestrador (br-video-production);
    # mesmo grupo causaria deadlock.
    c = _wf("render-worker.yml").get("concurrency") or {}
    assert c.get("group") == "br-video-production-render"
    assert c.get("cancel-in-progress") is False


@pytest.mark.parametrize("name", ["video-a-current-product-e2e.yml", "new-video-current-render-resume.yml"])
def test_orchestrators_gate_and_checkpoint_match(name):
    text = (WF / name).read_text(encoding="utf-8")
    assert "script_first_gate.py check" in text
    assert "script_first_gate.py checkpoint" in text


def test_render_worker_runs_script_first_gate_first():
    wf = _wf("render-worker.yml")
    on = wf.get("on") or wf.get(True)
    inputs = on["workflow_dispatch"]["inputs"]
    assert inputs["script_id"]["required"] is True
    assert inputs["script_sha256"]["required"] is True
    jobs = wf["jobs"]
    first = next(iter(jobs))
    assert first == "script-first-gate"
    runs = [s.get("run", "") for s in jobs[first]["steps"]]
    assert any("script_first_gate.py check" in r for r in runs)
    for name, job in jobs.items():
        if name != first:
            assert job.get("needs") == first, name


@pytest.mark.parametrize("name", ["video-a-current-product-e2e.yml", "new-video-current-render-resume.yml"])
def test_no_hardcoded_render_ref_or_artifact_ids(name):
    text = (WF / name).read_text(encoding="utf-8")
    assert "GITHUB_ACTIONS_RENDER_REF: work/gate6f-analytics-learning" not in text
    active = [l for l in text.splitlines() if not l.strip().startswith("#")]
    assert not any(re.search(r'artifact-ids:\s*"\d+"', l) for l in active), name


def test_ab_prepare_processes_single_script():
    src = (ROOT / "scripts/run001_ab_editorial_prepare.py").read_text(encoding="utf-8")
    assert "for label, goal_id in GOALS" not in src
    assert "--goal-id" in src


def test_schema_scripts_has_hash_and_approval_columns(tmp_path, monkeypatch):
    from app.database.schema import initialize_schema
    db = tmp_path / "s.db"
    monkeypatch.setenv("BR_TEST_DATABASE", str(db))
    initialize_schema()
    cols = {r[1] for r in sqlite3.connect(db).execute("PRAGMA table_info(scripts)")}
    assert {"content_sha256", "approved_by", "approved_at"} <= cols


def test_agents_md_records_owner_directive():
    text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "11/10/2026" in text and "um vídeo por vez" in text.lower()
    assert "content/roteiros" in text


def test_roteiros_readme_exists():
    assert (ROOT / "content/roteiros/README.md").is_file()
