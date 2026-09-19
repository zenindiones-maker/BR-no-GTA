from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APPROVAL = ROOT / ".run001" / "video-a-final-audio-approval.json"


def test_g_brand_mixed_is_locked_as_human_approved_final_end_signature():
    data = json.loads(APPROVAL.read_text(encoding="utf-8"))
    assert data["status"] == "HUMAN_APPROVED"
    assert data["role"] == "FINAL_END_SIGNATURE"
    assert data["sample_id"] == "G-brand-mixed"
    assert data["source_run_id"] == 35444013735
    assert data["source_artifact_id"] == 10585440542
    assert data["artifact_relative_path"] == "samples/G-brand-mixed.mp3"
    assert data["approved_asset_path"] == "assets/branding/audio/g-brand-mixed-approved-20260919.mp3"
    assert data["approved_asset_sha256"] == "9e2e7a2d9717f460dd45cf0d07e96a4596e4f61372c6d87028b8809a052c59ca"
    assert data["approval_manifest_path"] == "assets/branding/audio/human-approval-manifest.json"
    assert data["artifact_source_preserved_for_provenance"] is True
    assert data["runtime_dependency_on_historical_artifact"] is False
    assert data["canonical_audio_text"] == "BR no GTA 6. E BR não dorme em Vice City."
    assert data["canonical_closing_line"] == "E BR não dorme em Vice City"
    assert data["voice"] == "Voice B"
    assert data["voice_short_name"] == "pt-BR-ThalitaMultilingualNeural"
    assert data["gta6_pronunciation_human_approved"] is True
    assert data["vice_city_pronunciation_human_approved"] is True
    assert data["contains_canonical_closing_line"] is True
    assert data["automatic_substitution_allowed"] is False
    assert data["regeneration_allowed_without_new_human_review"] is False
    assert data["youtube_publication"] is False
    assert data["job18_frozen"] is True
