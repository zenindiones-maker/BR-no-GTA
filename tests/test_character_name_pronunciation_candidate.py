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
    assert plan.canonical_text==source
    assert plan.canonical_text_preserved is True
    assert plan.voice=="BR_OWNER_V1"
    assert plan.default_locale=="pt-BR"
    # Léxico ativo vazio (acoustic-only pending): nada de respelling nem chunk estrangeiro.
    assert plan.rendered_text==source
    assert plan.foreign_span_count==0
    unrelated=resolve_synthesis_plan("A produção continua com nome inventado Klovix.")
    assert unrelated.foreign_span_count==0

def test_vice_city_exact_owner_reading_remains_ptbr_without_foreign_chunk():
    plan=resolve_synthesis_plan("A ação continua em Vice City.")
    assert plan.canonical_text_preserved is True
    assert plan.foreign_span_count==0
    assert all(s.locale=="pt-BR" for s in plan.spans)
    # A leitura do dono continua governada no dicionário crítico da audição.
    owner=load(ROOT/"config"/"gta6_owner_audio_pronunciation_dictionary_v1.json")
    assert "vaicy siti" in json.dumps(owner,ensure_ascii=False)

def test_current_governed_names_do_not_fall_back_to_generic_voice():
    d=load(PRODUCTION)
    assert d["entries"]==[]
    assert d["policy"]["acoustic_reference_required"] is True
    assert d["policy"]["same_owner_voice_required"] is True
    plan=resolve_synthesis_plan("Jason e Lucia em Vice City.")
    assert plan.voice==DEFAULT_VOICE=="BR_OWNER_V1"
