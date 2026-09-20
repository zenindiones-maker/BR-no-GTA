import json
from pathlib import Path

from app.services.pronunciation_service import _edge_synthesis_groups, resolve_synthesis_plan
from scripts.voice_bc_character_review import candidate_cache_key, sample_set, script_inventory

ROOT=Path(__file__).resolve().parents[1]
CANDIDATE=ROOT/"config"/"pronunciation_character_aliases.bc-review.json"
PRODUCTION=ROOT/"config"/"pronunciation_lexicon.json"

def load(path):
    return json.loads(path.read_text(encoding="utf-8"))

def runtime_lexicon(tmp_path):
    d=load(CANDIDATE)
    for item in d["entries"]:
        if item["identity"]=="character-jason":
            item["synthesis_text"]="Djeison"
        if item["identity"]=="character-lucia":
            item["synthesis_text"]="Lussía"
    d["version"]+="+test"
    p=tmp_path/"runtime.json"
    p.write_text(json.dumps(d,ensure_ascii=False),encoding="utf-8")
    return p

def test_review_casting_is_exactly_b_and_c():
    d=load(CANDIDATE)
    assert d["reference"]["video_id"]=="VQRLujxTm3c"
    assert d["reference"]["channel"]=="Rockstar Games"
    assert d["review_casting"]["allowed_blind_ids"]==["B","C"]
    assert d["review_casting"]["official_voice"]=="B"
    assert d["review_casting"]["challenger_voice"]=="C"
    assert d["review_casting"]["voices"]=={
        "B":"pt-BR-ThalitaMultilingualNeural",
        "C":"pt-BR-FranciscaNeural",
    }
    assert d["review_casting"]["automatic_promotion"] is False

def test_character_aliases_stay_inside_ptbr_group(tmp_path):
    p=runtime_lexicon(tmp_path)
    plan=resolve_synthesis_plan("Jason e Lucia seguem juntos.",lexicon_path=p)
    groups=_edge_synthesis_groups(plan)
    assert plan.canonical_text_preserved
    assert plan.foreign_span_count==0
    assert len(groups)==1
    assert groups[0]["locale"]=="pt-BR"

def test_vice_city_is_only_foreign_span(tmp_path):
    p=runtime_lexicon(tmp_path)
    plan=resolve_synthesis_plan("Jason e Lucia atravessam Vice City.",lexicon_path=p)
    foreign=[x for x in plan.spans if x.locale!="pt-BR"]
    assert len(foreign)==1
    assert foreign[0].pronunciation_identity=="vice-city"
    assert all(
        x.locale=="pt-BR"
        for x in plan.spans
        if x.pronunciation_identity in {"character-jason","character-lucia"}
    )

def test_candidate_is_not_implicitly_promoted_to_production():
    ids={x["identity"] for x in load(PRODUCTION)["entries"]}
    assert "character-jason" not in ids
    assert "character-lucia" not in ids

def test_sample_parser_finds_real_pair_and_conversational_sentence():
    text=(
        "E por que esse assunto importa hoje, e não mês que vem? "
        "A Rockstar descreve Jason e Lucia sendo arrastados para uma conspiração. "
        "E responde aqui nos comentários: o que você acha?"
    )
    assert script_inventory(text)==["Jason","Lucia"]
    samples=sample_set(text)
    assert len(samples)==6
    assert samples[3][2]=="jason-lucia"
    assert "Jason" in samples[3][1] and "Lucia" in samples[3][1]
    assert samples[5][2]=="canonical-emotional-conversational"

def test_candidate_cache_key_preserves_diacritic_identity():
    assert candidate_cache_key("Djeison") != candidate_cache_key("Djêison")
    assert candidate_cache_key("Lucia") != candidate_cache_key("Lucía")
    assert candidate_cache_key("Lussía") != candidate_cache_key("Lussiá")


def test_lucia_human_alias_is_exactly_lucia_with_acute_i():
    d=load(CANDIDATE)
    entry=next(x for x in d["entries"] if x["identity"]=="character-lucia")
    assert entry["human_selected_synthesis_alias"]=="Lucía"
    assert entry["synthesis_candidates"]==["Lucía"]
    assert "Lussiá" not in entry["synthesis_candidates"]
    assert entry["locale"]=="pt-BR"
