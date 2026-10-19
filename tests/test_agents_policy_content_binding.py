"""AGENTS.md volta a ser um mapa curto (<=80 linhas) e as autorizações do dono
ficam verbatim em docs/policy/, presas por sha256 no AGENTS.md: editar a
autorização sem atualizar o hash faz a validação falhar (content binding)."""
from __future__ import annotations

import hashlib
from pathlib import Path

from app.services.agents_policy_validation_service import validate_agents_policy

ROOT = Path(__file__).resolve().parents[1]
OWNER = "docs/policy/owner_authorizations.md"
DIRECTIVES = "docs/policy/agents_operational_directives.md"


def test_owner_authorizations_live_verbatim_in_bound_policy_doc():
    text = (ROOT / OWNER).read_text(encoding="utf-8")
    for marker in (
        "OWNER_AUTHORIZED_20261011_SEGMENT_GATE_P10_BINDING: on 11/10/2026 the owner",
        "OWNER_AUTHORIZED_20261011_SEGMENT_REFERENCE_P10_BINDING: on 11/10/2026 the",
        "and the whole-audio centroid gate 0.868594, which is also binding. Any other",
        "Keep BR_OWNER_V1 single-human voice thresholds untouched; canonical script",
    ):
        assert marker in text
    directives = (ROOT / DIRECTIVES).read_text(encoding="utf-8")
    assert "Protocolo obrigatório de Engenharia Reversa Real" in directives


def test_agents_md_binds_policy_docs_by_sha256():
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    for ref in (OWNER, DIRECTIVES):
        digest = hashlib.sha256((ROOT / ref).read_bytes()).hexdigest()
        assert f"Policy: `{ref}` (sha256 {digest})" in agents
    result = validate_agents_policy(ROOT)
    assert result.status == "PASS", result
    assert result.content_binding_mismatches == ()
    assert result.line_count <= 80


def test_tampered_policy_doc_fails_closed(tmp_path):
    (tmp_path / "docs/policy").mkdir(parents=True)
    doc = tmp_path / "docs/policy/owner_authorizations.md"
    doc.write_text("original\n", encoding="utf-8")
    digest = hashlib.sha256(doc.read_bytes()).hexdigest()
    (tmp_path / "AGENTS.md").write_text(
        f"# map\nPolicy: `docs/policy/owner_authorizations.md` (sha256 {digest})\n", encoding="utf-8"
    )
    assert validate_agents_policy(tmp_path).status == "PASS"
    doc.write_text("edited without owner\n", encoding="utf-8")
    result = validate_agents_policy(tmp_path)
    assert result.status == "FAIL"
    assert result.content_binding_mismatches == ("docs/policy/owner_authorizations.md",)
