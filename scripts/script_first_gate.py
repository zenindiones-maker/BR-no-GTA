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
    root = Path(root or os.environ.get("BR_ROTEIROS_ROOT") or DEFAULT_ROOT)
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
    for other in _all_ids(root):
        if other != script_id and _load(root, other)[0].get("status") == "em_producao":
            raise ScriptGateError(f"ANOTHER_VIDEO_IN_PRODUCTION: {other}")
    orig = originality(root, str(script_id), text, digest)
    return {"SCRIPT_FIRST_GATE": "PASS", "script_id": script_id, "script_sha256": digest, "originality": orig}


def checkpoint_matches(checkpoint: dict[str, Any], script_id: str, script_sha256: str) -> None:
    if (checkpoint or {}).get("script_id") != script_id or (checkpoint or {}).get("script_sha256") != script_sha256:
        raise ScriptGateError("CHECKPOINT_SCRIPT_MISMATCH")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check"); c.add_argument("--script-id", required=True); c.add_argument("--script-sha256", required=True)
    c.add_argument("--root")
    k = sub.add_parser("checkpoint"); k.add_argument("--checkpoint", required=True)
    k.add_argument("--script-id", required=True); k.add_argument("--script-sha256", required=True)
    a = p.parse_args(argv)
    try:
        if a.cmd == "check":
            print(json.dumps(check(script_id=a.script_id, script_sha256=a.script_sha256, root=a.root), ensure_ascii=False))
        else:
            checkpoint_matches(json.loads(Path(a.checkpoint).read_text(encoding="utf-8")), a.script_id, a.script_sha256)
            print(json.dumps({"CHECKPOINT_SCRIPT_MATCH": "PASS"}))
    except ScriptGateError as exc:
        print(json.dumps({"SCRIPT_FIRST_GATE": "BLOCKED", "ERROR": str(exc)}, ensure_ascii=False))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
