from pathlib import Path

from app.services.pronunciation_service import _edge_synthesis_groups, resolve_synthesis_plan

ROOT=Path(__file__).resolve().parents[1]
CANDIDATE=ROOT/"config"/"pronunciation_character_aliases.candidate.json"

def test_character_aliases_are_synthesis_only_ptbr():
    text="A Rockstar descreve Jason e Lucia em material oficial."
    plan=resolve_synthesis_plan(text,lexicon_path=CANDIDATE)
    spans={span.pronunciation_identity:span for span in plan.spans if span.pronunciation_identity}
    assert plan.canonical_text==text
    assert plan.canonical_text_preserved is True
    assert spans["character-jason"].text=="Jason"
    assert spans["character-jason"].synthesis_text=="Djêisson"
    assert spans["character-jason"].locale=="pt-BR"
    assert spans["character-lucia"].text=="Lucia"
    assert spans["character-lucia"].synthesis_text=="Lussía"
    assert spans["character-lucia"].locale=="pt-BR"
    assert plan.foreign_span_count==0
    groups=_edge_synthesis_groups(plan)
    assert len(groups)==1
    assert groups[0]["locale"]=="pt-BR"

def test_character_aliases_do_not_create_en_us_chunks_around_vice_city():
    text="Jason e Lucia atravessam Vice City."
    plan=resolve_synthesis_plan(text,lexicon_path=CANDIDATE)
    foreign=[span for span in plan.spans if span.locale!="pt-BR"]
    assert len(foreign)==1
    assert foreign[0].pronunciation_identity=="vice-city"
    character=[span for span in plan.spans if span.pronunciation_identity in {"character-jason","character-lucia"}]
    assert character
    assert all(span.locale=="pt-BR" for span in character)

def test_default_production_lexicon_is_not_promoted_implicitly():
    text="Jason e Lucia atravessam Leonida."
    plan=resolve_synthesis_plan(text)
    assert "character-jason" not in plan.lexicon_hits
    assert "character-lucia" not in plan.lexicon_hits
    assert plan.rendered_text==text

def test_candidate_lexicon_version_changes_cache_identity():
    plan=resolve_synthesis_plan("Jason e Lucia",lexicon_path=CANDIDATE)
    assert plan.lexicon_version=="2026.09.19.4-character-candidate.1"
