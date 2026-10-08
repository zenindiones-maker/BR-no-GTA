from __future__ import annotations

import json
from pathlib import Path

from app.services.gta6_pronunciation_lexicon_service import build_gta6_pronunciation_segments


def _entry(filename):
    data=json.loads(Path("config",filename).read_text(encoding="utf-8"))
    return next(x for x in data["entries"] if x.get("term")=="Vice City"),data


def test_owner_spoken_vice_city_is_same_in_runtime_editorial_and_evidence():
    runtime,_=_entry("pronunciation_lexicon.json")
    candidate,_=_entry("pronunciation_ptbr_candidate.json")
    evidence,_=_entry("pronunciation_evidence_registry.json")
    actual=build_gta6_pronunciation_segments("Vice City")
    assert actual[0]["spoken_text"]=="vaicy siti"
    assert runtime["synthesis_text"]=="vaicy siti"
    assert candidate["synthesis_text"]=="vaicy siti"
    assert evidence["synthesis"]=="vaicy siti"
    assert candidate["validation_status"]=="PENDING_HUMAN_REVIEW"
    assert evidence["status"]=="OWNER_EXPLICIT_TARGET_ACOUSTIC_AUDITION_PENDING"
    assert "Váis Síti" in evidence["source_ref"]
    assert "Váis Síti" in candidate["source"]
    assert _entry("pronunciation_ptbr_candidate.json")[1]["policy"]["automatic_promotion"] is False
    assert _entry("pronunciation_lexicon.json")[1]["policy"]["same_owner_voice_required"] is True


def test_canonical_vice_city_is_not_wrongly_replaced_in_script():
    source="A gente vai conhecer Vice City em GTA 6."
    segments=build_gta6_pronunciation_segments(source)
    assert any(s["canonical_text"]=="Vice City" and s["spoken_text"]=="vaicy siti" for s in segments)
    assert "Vice City" in source
