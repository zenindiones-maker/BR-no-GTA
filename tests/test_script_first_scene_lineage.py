"""Luiz (11/10/2026): o vídeo segue o roteiro aprovado cena por cena."""
import json
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

SCENES = [
    {"order": 1, "narrative_block": "abertura", "visual_type": "official_trailer",
     "visual_description": "Logo oficial de GTA VI",
     "narration": "A Rockstar Games confirmou oficialmente a data de lançamento de GTA VI para novembro.",
     "duration_seconds": 8.0},
    {"order": 2, "narrative_block": "contexto", "visual_type": "official_screenshot",
     "visual_description": "Vice City em captura oficial",
     "narration": "Leonida e Vice City aparecem em todos os materiais publicados pela própria Rockstar.",
     "duration_seconds": 9.0},
]
RENDER = {"resolution": "1920x1080", "fps": 30, "aspect_ratio": "16:9",
          "container": "mp4", "video_codec": "h264", "audio_codec": "aac"}


def _g():
    from scripts import script_first_gate
    return script_first_gate


def _write(root, sid="ep-001", scenes=SCENES, md=None, status="aprovado_humano", slug=None):
    g = _g()
    d = root / sid
    d.mkdir(parents=True)
    text = md if md is not None else "\n\n".join(s["narration"] for s in scenes)
    (d / "roteiro.md").write_text(text, encoding="utf-8")
    sha = g.script_sha256(text)
    rec = {"schema": "br-roteiro/v1", "script_id": sid, "episode_slug": slug or sid,
           "status": status, "author_agent": "br_editorial_process_next", "sha256": sha,
           "scenes": scenes,
           "sources": [{"url": "https://www.rockstargames.com/VI", "kind": "official"}],
           "approval": {"approved_by": "Luiz", "approved_at": "2026-10-11T14:00:00-03:00",
                        "approved_sha256": sha}}
    (d / "roteiro.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    return sha


@pytest.fixture
def enforced(tmp_path, monkeypatch):
    root = tmp_path / "roteiros"
    root.mkdir()
    monkeypatch.setenv("BR_SCRIPT_FIRST_GATE_ENFORCE", "1")
    monkeypatch.setenv("BR_ROTEIROS_ROOT", str(root))
    return root


def _spec(sid, sha, scenes):
    return {"content_item_id": 1, "script_id": sid, "script_sha256": sha, "idea_id": 1,
            "objective": "x", "format": "longform", "estimated_duration_seconds": 17,
            "scenes": [dict(s, execution_requirements=[]) for s in scenes], "audio_requirements": [],
            "visual_requirements": [], "render": RENDER}


def test_gate_requires_scenes_matching_roteiro_text(enforced):
    g = _g()
    sha = _write(enforced, md="Texto diferente das cenas aprovadas pela equipe editorial do canal.")
    with pytest.raises(g.ScriptGateError, match="SCRIPT_SCENES_TEXT_MISMATCH"):
        g.check(script_id="ep-001", script_sha256=sha)


def test_gate_requires_scenes(enforced):
    g = _g()
    sha = _write(enforced, scenes=[], md="Algum texto oficial qualquer sobre o jogo.")
    with pytest.raises(g.ScriptGateError, match="SCRIPT_SCENES_REQUIRED"):
        g.check(script_id="ep-001", script_sha256=sha)


def test_render_job_scenes_equal_script_scenes(enforced):
    from app.services.render_job_service import create_render_job
    sha = _write(enforced)
    job = create_render_job(_spec("ep-001", sha, SCENES))
    assert [s["order"] for s in job["scenes"]] == [s["order"] for s in SCENES]
    assert [s["narration"] for s in job["scenes"]] == [s["narration"] for s in SCENES]
    assert [s["visual_description"] for s in job["scenes"]] == [s["visual_description"] for s in SCENES]


def test_render_job_refuses_altered_narration(enforced):
    from app.services.render_job_service import create_render_job
    sha = _write(enforced)
    bad = [dict(s) for s in SCENES]
    bad[1]["narration"] = "Narração inventada que não está no roteiro aprovado."
    with pytest.raises(Exception, match="RENDER_SCENES_DIVERGE_FROM_SCRIPT"):
        create_render_job(_spec("ep-001", sha, bad))


def test_render_job_refuses_extra_or_missing_scene(enforced):
    from app.services.render_job_service import create_render_job
    sha = _write(enforced)
    with pytest.raises(Exception, match="RENDER_SCENES_DIVERGE_FROM_SCRIPT"):
        create_render_job(_spec("ep-001", sha, SCENES[:1]))
    with pytest.raises(Exception, match="RENDER_SCENES_DIVERGE_FROM_SCRIPT"):
        create_render_job(_spec("ep-001", sha, SCENES + [dict(SCENES[0], order=3)]))


def test_dispatch_inputs_from_env(enforced, monkeypatch):
    g = _g()
    sha = _write(enforced)
    monkeypatch.setenv("SCRIPT_ID", "ep-001")
    monkeypatch.setenv("SCRIPT_SHA256", sha)
    assert g.render_dispatch_inputs() == {"script_id": "ep-001", "script_sha256": sha}
    monkeypatch.setenv("SCRIPT_SHA256", "0" * 64)
    with pytest.raises(g.ScriptGateError):
        g.render_dispatch_inputs()


def test_dispatcher_refuses_render_worker_without_script(enforced):
    from app.services.github_actions_dispatcher import GitHubActionsDispatcher
    d = GitHubActionsDispatcher(command_runner=lambda *a, **k: (_ for _ in ()).throw(AssertionError("ran")))
    with pytest.raises(Exception, match="SCRIPT_SHA256_REQUIRED"):
        d.dispatch(repository="o/r", workflow="render-worker.yml", ref="main", inputs={"render_job": ""})


@pytest.mark.parametrize("path", [
    "scripts/new_video_current_render_resume.py",
    "scripts/video_a_current_contract_recovery.py",
    "scripts/video_a_current_job2_resume.py",
])
def test_dispatch_scripts_pass_script_identity(path):
    src = (ROOT / path).read_text(encoding="utf-8")
    n_dispatch = src.count('workflow="render-worker.yml"')
    assert n_dispatch >= 1
    assert src.count("render_dispatch_inputs()") >= n_dispatch


def test_transitions_start_and_deliver_with_publicar_link(enforced, tmp_path):
    g = _g()
    sha = _write(enforced, slug="ep-001-data-oficial")
    videos = tmp_path / "videos"
    rec = g.start_production(script_id="ep-001", script_sha256=sha)
    assert rec["status"] == "em_producao"
    rec = g.deliver(script_id="ep-001", script_sha256=sha, videos_root=videos,
                    delivery={"youtube_video_id": "abc", "privacy": "private"})
    assert rec["status"] == "entregue"
    assert rec["package"] == "content/videos/ep-001-data-oficial/PUBLICAR.md"
    publicar = videos / "ep-001-data-oficial" / "PUBLICAR.md"
    assert publicar.is_file() and sha in publicar.read_text(encoding="utf-8")
    on_disk = json.loads((enforced / "ep-001/roteiro.json").read_text(encoding="utf-8"))
    assert on_disk["status"] == "entregue"


def test_deliver_requires_em_producao(enforced, tmp_path):
    g = _g()
    sha = _write(enforced)
    with pytest.raises(g.ScriptGateError, match="INVALID_TRANSITION"):
        g.deliver(script_id="ep-001", script_sha256=sha, videos_root=tmp_path, delivery={})


@pytest.mark.parametrize("name", ["video-a-current-product-e2e.yml", "new-video-current-render-resume.yml"])
def test_orchestrators_transition_states(name):
    text = (ROOT / ".github/workflows" / name).read_text(encoding="utf-8")
    assert "script_first_gate.py start" in text
    assert "script_first_gate.py deliver" in text
    assert 'SCRIPT_ID=' in text and "GITHUB_ENV" in text


def test_editorial_writes_roteiro_and_db_sha(enforced, monkeypatch):
    g = _g()
    result = {"status": "processed", "script": {"id": None, "title": "GTA VI: data oficial"},
              "production_plan": {"scenes": SCENES, "estimated_duration_seconds": 17},
              "sources": [{"url": "https://www.rockstargames.com/VI"}]}
    rec = g.write_editorial_script(result, goal_id="93f99ddc-09c7-474b-8849-6981aa78d60c")
    assert rec["status"] == "editorial_ok"
    assert rec["author_agent"] == "br_editorial_process_next"
    d = enforced / rec["script_id"]
    assert g.script_sha256((d / "roteiro.md").read_text(encoding="utf-8")) == rec["sha256"]
    assert [s["narration"] for s in rec["scenes"]] == [s["narration"] for s in SCENES]
    assert rec.get("approval") is None


def test_editorial_fills_db_content_sha(enforced):
    g = _g()
    from app.database.connection import get_connection
    conn = get_connection()
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute("INSERT INTO scripts(idea_id,title,content) VALUES (1,'t','c')")
    sid = conn.execute("SELECT max(id) FROM scripts").fetchone()[0]
    conn.commit(); conn.close()
    result = {"status": "processed", "script": {"id": sid, "title": "GTA VI"},
              "production_plan": {"scenes": SCENES}}
    rec = g.write_editorial_script(result)
    conn = get_connection()
    row = conn.execute("SELECT content_sha256 FROM scripts WHERE id=?", (sid,)).fetchone()
    assert row[0] == rec["sha256"]


def test_harness_editorial_calls_writer():
    src = (ROOT / "app/integrations/deepseek_harness/server.py").read_text(encoding="utf-8")
    body = src.split("def br_editorial_process_next(")[1].split("\ndef ")[0]
    assert "write_editorial_script(" in body


# --- Boas práticas pesquisadas (docs GitHub Actions concurrency/queue; OTIO/EDL) ---

@pytest.mark.parametrize("name", [
    "render-worker.yml", "video-a-current-product-e2e.yml", "new-video-current-render-resume.yml",
    "new-video-e2e-benchmark.yml", "run001-e2e-canary.yml"])
def test_video_concurrency_queues_fifo_instead_of_cancelling_pending(name):
    # Docs: com queue=single (padrão) um run pendente é CANCELADO quando outro entra.
    import yaml
    c = yaml.safe_load((ROOT / ".github/workflows" / name).read_text(encoding="utf-8"))["concurrency"]
    assert c.get("queue") == "max", name
    assert c.get("cancel-in-progress") is False


def test_scene_decision_list_is_content_addressed_timeline():
    g = _g()
    edl = g.scene_decision_list("ep-001", "a" * 64, SCENES, fps=30)
    assert edl["schema"] == "br-scene-decision-list/v1" and edl["fps"] == 30
    ev = edl["events"]
    assert [e["order"] for e in ev] == [1, 2]
    assert ev[0]["record_in_frame"] == 0 and ev[0]["record_out_frame"] == 240
    assert ev[1]["record_in_frame"] == 240 and ev[1]["record_out_frame"] == 510
    assert ev[0]["narration_sha256"] == g.script_sha256(SCENES[0]["narration"])
    again = g.scene_decision_list("ep-001", "a" * 64, SCENES, fps=30)
    assert again["edl_sha256"] == edl["edl_sha256"]


def test_render_job_carries_edl_hash(enforced):
    from app.services.render_job_service import create_render_job
    sha = _write(enforced)
    job = create_render_job(_spec("ep-001", sha, SCENES))
    assert len(job["scene_decision_list_sha256"]) == 64
    assert [s["narration_sha256"] for s in job["scenes"]] == [
        _g().script_sha256(s["narration"]) for s in SCENES]


def test_render_worker_gate_exposes_job_outputs_and_edl_artifact():
    import yaml
    wf = yaml.safe_load((ROOT / ".github/workflows/render-worker.yml").read_text(encoding="utf-8"))
    gate = wf["jobs"]["script-first-gate"]
    assert set(gate["outputs"]) >= {"script_id", "script_sha256", "edl_sha256"}
    assert any("upload-artifact" in str(s.get("uses", "")) for s in gate["steps"])
