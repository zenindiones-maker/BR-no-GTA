"""v5h: composite pool must be deduped by content hash and near-duplicate embedding."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.services.owner_voice_reference_window_service import dedupe_reference_pool

SRC=Path("scripts/owner_voice_single_human_clone.py").read_text()


def test_two_ids_same_sha_collapse_to_one_clip():
    rows=[{"reference_id":"46","sha256":"aa"},{"reference_id":"51","sha256":"aa"},
          {"reference_id":"60","sha256":"bb"}]
    emb={"46":[1.0,0.0],"51":[1.0,0.0],"60":[0.6,0.8]}
    sims={"46":0.97429,"51":0.97429,"60":0.93}
    kept,stats=dedupe_reference_pool(rows,emb,sims,min_similarity=0.90)
    assert [r["reference_id"] for r in kept]==["46","60"]
    assert stats=={"candidates":3,"exact_duplicates":1,"near_duplicates":0,"distinct_qualifying":2}


def test_near_duplicate_embedding_dropped_and_below_floor_excluded():
    rows=[{"reference_id":"a","sha256":"1"},{"reference_id":"b","sha256":"2"},
          {"reference_id":"c","sha256":"3"}]
    emb={"a":[1.0,0.0],"b":[0.9999,0.0141],"c":[0.0,1.0]}
    sims={"a":0.95,"b":0.94,"c":0.85}
    kept,stats=dedupe_reference_pool(rows,emb,sims,min_similarity=0.90)
    assert [r["reference_id"] for r in kept]==["a"]
    assert stats["near_duplicates"]==1 and stats["distinct_qualifying"]==1


def test_missing_hash_fails_closed():
    with pytest.raises(RuntimeError,match="OWNER_REFERENCE_SHA256_REQUIRED"):
        dedupe_reference_pool([{"reference_id":"a"}],{"a":[1.0]},{"a":0.95},min_similarity=0.9)


def test_script_dedupes_before_composite_and_logs_without_hashes():
    assert "dedupe_reference_pool(" in SRC
    assert "OWNER_QWEN_COMPOSITE_DISTINCT_QUALIFYING_CLIPS=" in SRC
    assert "OWNER_QWEN_COMPOSITE_PARTS_DISTINCT_CONTENT=" in SRC
    assert SRC.index("dedupe_reference_pool(")<SRC.index("choose_composite_windows(\n")
