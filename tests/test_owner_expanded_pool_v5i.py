"""v5i: ASR/PT-BR verification covers the deduplicated >=0.90 pool, bounded."""
from __future__ import annotations

from pathlib import Path

from app.services.owner_voice_reference_window_service import (
    COMPOSITE_POOL_ASR_BUDGET,
    plan_composite_asr_pool,
)

SRC=Path("scripts/owner_voice_single_human_clone.py").read_text()


def test_pool_plan_dedupes_by_sha_keeps_rank_and_floor_and_is_bounded():
    rows=[{"reference_id":str(i),"sha256":"dup" if i<3 else f"s{i}"} for i in range(40)]
    sims={str(i):0.97-0.002*i for i in range(40)}
    sims["5"]=0.80
    plan=plan_composite_asr_pool(rows,sims,min_similarity=0.90)
    ids=[r["reference_id"] for r in plan]
    assert ids[0]=="0" and "1" not in ids and "2" not in ids
    assert "5" not in ids
    assert len({r["sha256"] for r in plan})==len(plan)
    assert len(plan)<=COMPOSITE_POOL_ASR_BUDGET and COMPOSITE_POOL_ASR_BUDGET>=10


def test_script_asr_loop_uses_deduped_pool_and_counts_distinct_verified():
    assert "plan_composite_asr_pool(" in SRC
    assert "OWNER_COMPOSITE_POOL_ASR_PLANNED=" in SRC
    assert "OWNER_COMPOSITE_POOL_PTBR_VERIFIED_DISTINCT=" in SRC
    assert SRC.index("plan_composite_asr_pool(")<SRC.index("stt=_load_stt(cache_root)")
