import json
from pathlib import Path

from app.services.pronunciation_service import _edge_synthesis_groups, resolve_synthesis_plan

ROOT=Path(__file__).resolve().parents[1]
CANDIDATE=ROOT/"config"/"pronunciation_character_aliases.candidate.json"
PRODUCTION=ROOT/"config"/"pronunciation_lexicon.json"

def load(path):
    return json.loads(path.read_text(encoding="utf-8"))

def test_candidate_requires_real_acoustic_selection():
    d=load(CANDIDATE)
    assert d["reference"]["video_id"]=="VQRLujxTm3c"
    assert d["reference"]["channel"]=="Rockstar Games"
    assert "Official Rockstar acoustic ground truth" in d["reference"]["authority_scope"]
    assert d["policy"]["only_forced_en_us_term"]=="Vice City"
    chars={x["identity"]:x for x in d["entries"] if str(x.get("identity","")).startswith("character-")}
    assert set(chars)=={"character-jason","character-lucia"}
    assert all(x["locale"]=="pt-BR" for x in chars.values())
    assert chars["character-jason"]["reference_status"]=="ROCKSTAR_TRAILER2_ACOUSTIC_SELECTION_REQUIRED"
    assert chars["character-lucia"]["reference_status"]=="HUMAN_CORRECTED_ALIAS"
    assert all("synthesis_text" not in x for x in chars.values())
    assert all(x.get("synthesis_candidates") for x in chars.values())
    assert chars["character-lucia"]["human_selected_synthesis_alias"]=="Lucía"

def test_runtime_aliases_do_not_split_ptbr_sentence(tmp_path):
    d=load(CANDIDATE)
    for x in d["entries"]:
        if x["identity"]=="character-jason":
            x["synthesis_text"]="Djeison"
        if x["identity"]=="character-lucia":
            x["synthesis_text"]="Lucía"
    d["version"]+="+test"
    p=tmp_path/"runtime.json"
    p.write_text(json.dumps(d,ensure_ascii=False),encoding="utf-8")
    text="Jason e Lucia seguem juntos."
    plan=resolve_synthesis_plan(text,lexicon_path=p)
    assert plan.canonical_text==text and plan.canonical_text_preserved
    groups=_edge_synthesis_groups(plan)
    assert plan.foreign_span_count==0
    assert len(groups)==1 and groups[0]["locale"]=="pt-BR"

def test_vice_city_remains_only_en_us_span(tmp_path):
    d=load(CANDIDATE)
    for x in d["entries"]:
        if x["identity"]=="character-jason":
            x["synthesis_text"]="Djeison"
        if x["identity"]=="character-lucia":
            x["synthesis_text"]="Lucía"
    d["version"]+="+test"
    p=tmp_path/"runtime.json"
    p.write_text(json.dumps(d,ensure_ascii=False),encoding="utf-8")
    plan=resolve_synthesis_plan("Jason e Lucia atravessam Vice City.",lexicon_path=p)
    foreign=[x for x in plan.spans if x.locale!="pt-BR"]
    assert len(foreign)==1 and foreign[0].pronunciation_identity=="vice-city"
    assert all(
        x.locale=="pt-BR"
        for x in plan.spans
        if x.pronunciation_identity in {"character-jason","character-lucia"}
    )

def test_only_human_approved_character_alias_is_promoted_to_production():
    production=load(PRODUCTION)
    entries={x["identity"]:x for x in production["entries"]}
    assert "character-jason" not in entries
    assert entries["character-lucia"]["locale"]=="pt-BR"
    assert entries["character-lucia"]["strategy"]=="alias"
    assert entries["character-lucia"]["synthesis_text"]=="Lucía"
    assert "human-approved synthesis-only alias" in entries["character-lucia"]["source"]
