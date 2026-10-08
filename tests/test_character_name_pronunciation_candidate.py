import json
from pathlib import Path

from app.services.pronunciation_service import (
    DEFAULT_LOCALE, DEFAULT_VOICE, resolve_synthesis_plan,
)

ROOT=Path(__file__).resolve().parents[1]
PRODUCTION=ROOT/"config"/"pronunciation_lexicon.json"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_owner_only_and_explicitly_governed_foreign_chunks():
    d=load(PRODUCTION)
    policy=d["policy"]
    assert d["default_locale"]=="pt-BR"
    assert DEFAULT_VOICE=="BR_OWNER_V1"
    assert DEFAULT_LOCALE=="pt-BR"
    assert policy["same_owner_voice_required"] is True
    assert policy["human_gate_for_critical_terms"] is True
    assert policy["canonical_text_immutable"] is True
    assert policy["governed_foreign_chunks_only"] is True
    assert policy["arbitrary_foreign_chunks_forbidden"] is True
    assert policy["generic_name_autodetection_enabled"] is False
    entries=d["entries"]
    assert all(e["critical"] is True for e in entries)
    assert all(e["locale"] in ("pt-BR","en-US") for e in entries)


def test_canonical_script_and_explicit_governed_code_switch():
    source="Lucia atravessa Vice City em Leonida."
    plan=resolve_synthesis_plan(source)
    d=load(PRODUCTION)
    known={e["identity"] for e in d["entries"]}
    assert plan.canonical_text==source
    assert plan.canonical_text_preserved is True
    assert plan.voice=="BR_OWNER_V1"
    assert plan.default_locale=="pt-BR"
    assert "vaicy siti" in plan.rendered_text
    assert plan.foreign_span_count>=1
    for span in plan.spans:
        if span.locale!="pt-BR":
            assert span.pronunciation_identity in known
            assert span.source=="lexicon"
            assert span.critical is True
    unrelated=resolve_synthesis_plan("A produção continua com nome inventado Klovix.")
    assert unrelated.foreign_span_count==0


def test_vice_city_exact_owner_reading_remains_ptbr_without_foreign_chunk():
    plan=resolve_synthesis_plan("A ação continua em Vice City.")
    hits=[s for s in plan.spans if s.pronunciation_identity=="vice-city"]
    assert len(hits)==1
    assert plan.canonical_text_preserved is True
    assert hits[0].locale=="pt-BR"
    assert hits[0].synthesis_text.startswith("vaicy siti")
    assert hits[0].synthesis_text.endswith(".")
    assert plan.foreign_span_count==0


def test_current_governed_names_do_not_fall_back_to_generic_voice():
    entries={e["identity"]:e for e in load(PRODUCTION)["entries"]}
    assert "character-jason" in entries
    assert entries["character-jason"]["strategy"]=="canonical-owner-acoustic"
    assert entries["character-lucia"]["strategy"]=="canonical-owner-acoustic"
    assert entries["character-lucia"]["term"]=="Lucia"
    assert entries["vice-city"]["synthesis_text"]=="vaicy siti"
    assert all(e["source"] for e in entries.values())
