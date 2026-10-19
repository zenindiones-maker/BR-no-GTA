"""Com 40+ claims oficiais o contexto semântico do content-strategy estourava o
limite de 24000 caracteres (run 39191086825). O contexto passa a usar uma visão
compacta e limitada dos claims, preservando statement + URL oficial por claim."""
from __future__ import annotations

import json
from pathlib import Path

from scripts import prove_real_multi_agent_synergy as synergy


def _claims(n: int) -> list[dict]:
    return [{
        "claim_id": f"source-claim-{i:024d}",
        "statement": ("Grand Theft Auto VI será lançado em 19 de novembro de 2026 no PS5. " * 20)[:1200],
        "verification_status": "VERIFIED",
        "source_hierarchy": "OFFICIAL_PRIMARY",
        "fact_check_result": "SUPPORTED",
        "fact_check_confidence": 1.0,
        "evidence_refs": [f"fact-check-execution:{'x' * 60}"] * 12,
        "source_urls": ["https://www.playstation.com/pt-br/games/grand-theft-auto-vi/"],
    } for i in range(n)]


def test_semantic_claims_fit_budget_and_keep_source_urls():
    rows = synergy._semantic_claims(_claims(44), budget=14000)
    assert rows, "must keep claims"
    assert len(json.dumps(rows, ensure_ascii=False, sort_keys=True)) <= 14000
    assert all(r["source_urls"] for r in rows)
    assert all(r["verification_status"] == "VERIFIED" for r in rows)


def test_verified_claims_come_first():
    claims = _claims(3)
    claims[0]["verification_status"] = "INSUFFICIENT_EVIDENCE"
    rows = synergy._semantic_claims(claims, budget=14000)
    assert rows[0]["verification_status"] == "VERIFIED"


def test_prove_uses_bounded_semantic_claims():
    body = Path(synergy.__file__).read_text(encoding="utf-8")
    assert '"verified_claims": _semantic_claims(claims)' in body
