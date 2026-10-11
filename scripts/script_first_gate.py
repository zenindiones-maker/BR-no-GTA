"""Script-first gate (diretriz do proprietário Luiz, 11/10/2026).

Nenhum vídeo é renderizado sem um roteiro em content/roteiros/<script_id>/ que:
- foi escrito pelo agente editorial (GTA6 Master Agent / br_editorial_process_next);
- foi aprovado pelo Luiz sobre exatamente o mesmo sha256;
- cita fontes oficiais (Rockstar / Take-Two);
- é original frente a todos os roteiros anteriores (editorial_novelty_service);
- e enquanto nenhum outro roteiro estiver em_producao (um vídeo por vez).
Fail-closed: qualquer dúvida levanta ScriptGateError.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.services import editorial_novelty_service as novelty

DEFAULT_ROOT = Path(__file__).resolve().parents[1] / "content" / "roteiros"
STATUSES = ("rascunho", "editorial_ok", "aprovado_humano", "em_producao", "entregue", "rejeitado")
TRANSITIONS = {
    "rascunho": {"editorial_ok", "rejeitado"},
    "editorial_ok": {"aprovado_humano", "rascunho", "rejeitado"},
    "aprovado_humano": {"em_producao", "rejeitado"},
    "em_producao": {"entregue", "aprovado_humano"},
    "entregue": set(),
    "rejeitado": {"rascunho"},
}
EDITORIAL_AGENTS = {"GTA6 Master Agent", "br_editorial_process_next"}
HUMAN_APPROVERS = {"Luiz"}
PRIOR_STATUSES = {"aprovado_humano", "em_producao", "entregue"}
OFFICIAL_DOMAINS = ("rockstargames.com", "take2games.com", "take2.com")
MAX_REUSE_PERCENT = novelty.MAX_SCRIPT_NGRAM_REUSE_PERCENT


class ScriptGateError(RuntimeError):
    pass


def script_sha256(text: str) -> str:
    return hashlib.sha256(novelty.normalize(text).encode("utf-8")).hexdigest()


def _load(root: Path, script_id: str) -> tuple[dict[str, Any], str]:
    d = root / script_id
    rec_path, txt_path = d / "roteiro.json", d / "roteiro.md"
    if not rec_path.is_file() or not txt_path.is_file():
        raise ScriptGateError(f"SCRIPT_NOT_FOUND: {script_id}")
    return json.loads(rec_path.read_text(encoding="utf-8")), txt_path.read_text(encoding="utf-8")


def _all_ids(root: Path) -> list[str]:
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if (p / "roteiro.json").is_file() and not p.name.startswith("_"))


def _is_official(url: str) -> bool:
    host = (urlparse(str(url)).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in OFFICIAL_DOMAINS)


def transition(record: dict[str, Any], new_status: str, *, actor: str = "", approved_at: str = "") -> dict[str, Any]:
    cur = record.get("status")
    if new_status not in STATUSES or new_status not in TRANSITIONS.get(cur, set()):
        raise ScriptGateError(f"INVALID_TRANSITION: {cur} -> {new_status}")
    if new_status == "editorial_ok" and actor not in EDITORIAL_AGENTS:
        raise ScriptGateError("EDITORIAL_AGENT_REQUIRED")
    out = dict(record)
    if new_status == "aprovado_humano":
        if actor not in HUMAN_APPROVERS or not approved_at:
            raise ScriptGateError("HUMAN_APPROVAL_REQUIRED")
        out["approval"] = {"approved_by": actor, "approved_at": approved_at,
                           "approved_sha256": record.get("sha256")}
    out["status"] = new_status
    return out


def originality(root: Path, script_id: str, text: str, digest: str) -> dict[str, Any]:
    max_reuse, matched = 0.0, None
    for other in _all_ids(root):
        if other == script_id:
            continue
        rec, other_text = _load(root, other)
        if rec.get("status") not in PRIOR_STATUSES:
            continue
        if script_sha256(other_text) == digest or rec.get("sha256") == digest:
            raise ScriptGateError(f"DUPLICATE_SCRIPT: {script_id} == {other}")
        reuse = novelty.script_reuse_percent(text, other_text)
        if reuse > max_reuse:
            max_reuse, matched = reuse, other
    if max_reuse > MAX_REUSE_PERCENT:
        raise ScriptGateError(f"SCRIPT_REUSE: {max_reuse:.1f}% vs {matched} (max {MAX_REUSE_PERCENT}%)")
    return {"max_reuse_percent": round(max_reuse, 3), "matched": matched, "threshold": MAX_REUSE_PERCENT}


def check(*, script_id: str, script_sha256: str, root: Path | str | None = None) -> dict[str, Any]:
    root = _root(root)
    if not script_id or not script_sha256:
        raise ScriptGateError("SCRIPT_SHA256_REQUIRED")
    rec, text = _load(root, str(script_id))
    digest = globals()["script_sha256"](text)
    if digest != script_sha256 or rec.get("sha256") != digest:
        raise ScriptGateError("SCRIPT_SHA_MISMATCH")
    if rec.get("status") not in {"aprovado_humano", "em_producao"}:
        raise ScriptGateError(f"SCRIPT_NOT_APPROVED: status={rec.get('status')}")
    approval = rec.get("approval") or {}
    if approval.get("approved_by") not in HUMAN_APPROVERS or not approval.get("approved_at"):
        raise ScriptGateError("SCRIPT_NOT_APPROVED: missing Luiz approval record")
    if approval.get("approved_sha256") != digest:
        raise ScriptGateError("APPROVAL_SHA_MISMATCH")
    if rec.get("author_agent") not in EDITORIAL_AGENTS:
        raise ScriptGateError("EDITORIAL_AGENT_REQUIRED")
    if not any(_is_official(s.get("url", "")) for s in rec.get("sources") or []):
        raise ScriptGateError("OFFICIAL_SOURCES_REQUIRED")
    scenes = validate_scenes(rec, text)
    for other in _all_ids(root):
        if other != script_id and _load(root, other)[0].get("status") == "em_producao":
            raise ScriptGateError(f"ANOTHER_VIDEO_IN_PRODUCTION: {other}")
    orig = originality(root, str(script_id), text, digest)
    return {"SCRIPT_FIRST_GATE": "PASS", "script_id": script_id, "script_sha256": digest,
            "originality": orig, "scenes": scenes, "episode_slug": rec.get("episode_slug") or script_id}


SCENE_FIELDS = ("order", "narrative_block", "visual_type", "visual_description", "narration", "duration_seconds")
COMPARED_SCENE_FIELDS = ("order", "narration", "visual_description")


def _root(root: Path | str | None = None) -> Path:
    return Path(root or os.environ.get("BR_ROTEIROS_ROOT") or DEFAULT_ROOT)


def validate_scenes(rec: dict[str, Any], text: str) -> list[dict[str, Any]]:
    scenes = rec.get("scenes") or []
    if not scenes:
        raise ScriptGateError("SCRIPT_SCENES_REQUIRED")
    orders = [s.get("order") for s in scenes]
    if orders != list(range(1, len(scenes) + 1)):
        raise ScriptGateError(f"SCRIPT_SCENES_ORDER_INVALID: {orders}")
    for sc in scenes:
        if not str(sc.get("narration") or "").strip():
            raise ScriptGateError(f"SCRIPT_SCENE_EMPTY_NARRATION: {sc.get('order')}")
    joined = " ".join(str(sc["narration"]) for sc in scenes)
    if novelty.normalize(joined) != novelty.normalize(text):
        raise ScriptGateError("SCRIPT_SCENES_TEXT_MISMATCH")
    return [dict(sc) for sc in scenes]


def assert_render_scenes_match(render_scenes: list[dict[str, Any]], script_scenes: list[dict[str, Any]]) -> None:
    """O render segue o roteiro aprovado cena por cena (ordem, narração, visual)."""
    if len(render_scenes) != len(script_scenes):
        raise ScriptGateError(
            f"RENDER_SCENES_DIVERGE_FROM_SCRIPT: {len(render_scenes)} cenas no render vs {len(script_scenes)} no roteiro")
    for got, want in zip(render_scenes, script_scenes):
        for f in COMPARED_SCENE_FIELDS:
            a, b = got.get(f), want.get(f)
            if f == "narration":
                a, b = novelty.normalize(str(a)), novelty.normalize(str(b))
            if a != b:
                raise ScriptGateError(f"RENDER_SCENES_DIVERGE_FROM_SCRIPT: cena {want.get('order')} campo {f}")


def scene_decision_list(script_id: str, script_sha: str, scenes: list[dict[str, Any]], *, fps: int = 30) -> dict[str, Any]:
    """Lista de decisões por cena (inspirada em EDL CMX3600/OpenTimelineIO): cada evento
    tem record in/out em frames e o sha256 da narração. Endereçada por conteúdo."""
    events, cursor = [], 0
    for sc in scenes:
        frames = int(round(float(sc.get("duration_seconds") or 0) * fps))
        events.append({"order": sc["order"], "record_in_frame": cursor, "record_out_frame": cursor + frames,
                       "narration_sha256": globals()["script_sha256"](str(sc.get("narration") or "")),
                       "visual_type": sc.get("visual_type"), "visual_description": sc.get("visual_description")})
        cursor += frames
    body = {"schema": "br-scene-decision-list/v1", "script_id": script_id, "script_sha256": script_sha,
            "fps": fps, "events": events}
    body["edl_sha256"] = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return body


def render_dispatch_inputs() -> dict[str, str]:
    """Inputs obrigatórios do render-worker, lidos do ambiente do orquestrador e já validados."""
    if os.environ.get("BR_SCRIPT_FIRST_GATE_ENFORCE", "1") == "0":
        return {}
    sid = os.environ.get("SCRIPT_ID", "").strip()
    sha = os.environ.get("SCRIPT_SHA256", "").strip()
    check(script_id=sid, script_sha256=sha)
    return {"script_id": sid, "script_sha256": sha}


def _save(root: Path, script_id: str, rec: dict[str, Any]) -> None:
    (root / script_id / "roteiro.json").write_text(
        json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def start_production(*, script_id: str, script_sha256: str, root: Path | str | None = None) -> dict[str, Any]:
    r = _root(root)
    check(script_id=script_id, script_sha256=script_sha256, root=r)
    rec, _ = _load(r, script_id)
    if rec.get("status") == "em_producao":
        return rec
    rec = transition(rec, "em_producao")
    _save(r, script_id, rec)
    return rec


def deliver(*, script_id: str, script_sha256: str, videos_root: Path | str | None = None,
            delivery: dict[str, Any] | None = None, root: Path | str | None = None) -> dict[str, Any]:
    r = _root(root)
    rec, text = _load(r, script_id)
    if script_sha256 != globals()["script_sha256"](text) or rec.get("sha256") != script_sha256:
        raise ScriptGateError("SCRIPT_SHA_MISMATCH")
    rec = transition(rec, "entregue")
    slug = rec.get("episode_slug") or script_id
    vroot = Path(videos_root or (Path(__file__).resolve().parents[1] / "content" / "videos"))
    pkg = vroot / slug / "PUBLICAR.md"
    pkg.parent.mkdir(parents=True, exist_ok=True)
    d = delivery or {}
    lines = [f"# PUBLICAR — {rec.get('title') or slug}", "",
             f"- Roteiro: content/roteiros/{script_id}/ (sha256 {script_sha256})",
             f"- Aprovado por: {(rec.get('approval') or {}).get('approved_by')} em {(rec.get('approval') or {}).get('approved_at')}",
             "- Status: entregue para revisão; o clique de publicar é do Luiz.", "", "## Entrega", ""]
    lines += [f"- {k}: {v}" for k, v in sorted(d.items())]
    lines += ["", "Checklist completo: content/videos/_modelo_pacote/PUBLICAR.md", ""]
    pkg.write_text("\n".join(lines), encoding="utf-8")
    rec["package"] = f"content/videos/{slug}/PUBLICAR.md"
    rec["delivery"] = d
    _save(r, script_id, rec)
    return rec


def write_editorial_script(result: dict[str, Any], *, goal_id: str | None = None,
                           root: Path | str | None = None) -> dict[str, Any]:
    """Grava o roteiro do agente editorial em content/roteiros (rascunho -> editorial_ok)
    e preenche scripts.content_sha256. Nunca aprova: aprovação é só do Luiz."""
    plan = result.get("production_plan") or {}
    raw = plan.get("scenes") or []
    if not raw:
        raise ScriptGateError("SCRIPT_SCENES_REQUIRED")
    scenes = []
    for i, sc in enumerate(raw, 1):
        item = {f: sc.get(f) for f in SCENE_FIELDS if f in sc}
        item["order"] = i
        if sc.get("source_url"):
            item["source_url"] = sc["source_url"]
        scenes.append(item)
    text = "\n\n".join(str(sc.get("narration") or "").strip() for sc in scenes) + "\n"
    digest = globals()["script_sha256"](text)
    script = result.get("script") or {}
    db_id = script.get("id")
    script_id = f"ep-{db_id:04d}" if isinstance(db_id, int) else f"ep-{digest[:12]}"
    r = _root(root)
    d = r / script_id
    if (d / "roteiro.json").is_file():
        existing, _ = _load(r, script_id)
        if existing.get("sha256") != digest:
            raise ScriptGateError(f"SCRIPT_ID_COLLISION: {script_id}")
        return existing
    urls = [s.get("url") for s in (result.get("sources") or []) if s.get("url")]
    try:
        urls += [u for u in json.loads(os.environ.get("BR_EDITORIAL_VERIFIED_SOURCES") or "[]") if u]
    except ValueError:
        raise ScriptGateError("BR_EDITORIAL_VERIFIED_SOURCES must be a JSON list")
    urls += [sc["source_url"] for sc in scenes if sc.get("source_url")]
    sources = [{"url": u, "kind": "official" if _is_official(u) else "other"} for u in dict.fromkeys(urls)]
    rec = {"schema": "br-roteiro/v1", "script_id": script_id, "episode_slug": script_id,
           "title": script.get("title") or "", "goal_id": goal_id, "db_script_id": db_id,
           "status": "rascunho", "author_agent": "br_editorial_process_next", "sha256": digest,
           "target_duration_seconds": plan.get("estimated_duration_seconds"),
           "scenes": scenes, "sources": sources, "approval": None, "package": None}
    rec = transition(rec, "editorial_ok", actor="br_editorial_process_next")
    d.mkdir(parents=True, exist_ok=True)
    (d / "roteiro.md").write_text(text, encoding="utf-8")
    _save(r, script_id, rec)
    if isinstance(db_id, int):
        from app.database.connection import get_connection
        conn = get_connection()
        try:
            conn.execute("UPDATE scripts SET content_sha256=? WHERE id=?", (digest, db_id))
            conn.commit()
        finally:
            conn.close()
    return rec


def checkpoint_matches(checkpoint: dict[str, Any], script_id: str, script_sha256: str) -> None:
    if (checkpoint or {}).get("script_id") != script_id or (checkpoint or {}).get("script_sha256") != script_sha256:
        raise ScriptGateError("CHECKPOINT_SCRIPT_MISMATCH")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check"); c.add_argument("--script-id", required=True); c.add_argument("--script-sha256", required=True)
    c.add_argument("--root"); c.add_argument("--edl-out", default="")
    k = sub.add_parser("checkpoint"); k.add_argument("--checkpoint", required=True)
    k.add_argument("--script-id", required=True); k.add_argument("--script-sha256", required=True)
    st = sub.add_parser("start"); st.add_argument("--script-id", required=True); st.add_argument("--script-sha256", required=True)
    dv = sub.add_parser("deliver"); dv.add_argument("--script-id", required=True); dv.add_argument("--script-sha256", required=True)
    dv.add_argument("--delivery-json", default="")
    a = p.parse_args(argv)
    try:
        if a.cmd == "check":
            res = check(script_id=a.script_id, script_sha256=a.script_sha256, root=a.root)
            edl = scene_decision_list(a.script_id, a.script_sha256, res["scenes"])
            if a.edl_out:
                Path(a.edl_out).parent.mkdir(parents=True, exist_ok=True)
                Path(a.edl_out).write_text(json.dumps(edl, ensure_ascii=False, indent=2), encoding="utf-8")
            res["edl_sha256"] = edl["edl_sha256"]
            print(json.dumps(res, ensure_ascii=False))
        elif a.cmd == "start":
            rec = start_production(script_id=a.script_id, script_sha256=a.script_sha256)
            print(json.dumps({"SCRIPT_STATE": rec["status"], "script_id": a.script_id}))
        elif a.cmd == "deliver":
            d = json.loads(Path(a.delivery_json).read_text(encoding="utf-8")) if a.delivery_json and Path(a.delivery_json).is_file() else {}
            rec = deliver(script_id=a.script_id, script_sha256=a.script_sha256, delivery=d)
            print(json.dumps({"SCRIPT_STATE": rec["status"], "package": rec["package"]}))
        else:
            checkpoint_matches(json.loads(Path(a.checkpoint).read_text(encoding="utf-8")), a.script_id, a.script_sha256)
            print(json.dumps({"CHECKPOINT_SCRIPT_MATCH": "PASS"}))
    except ScriptGateError as exc:
        print(json.dumps({"SCRIPT_FIRST_GATE": "BLOCKED", "ERROR": str(exc)}, ensure_ascii=False))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
