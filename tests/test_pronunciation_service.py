from __future__ import annotations

from dataclasses import replace
import pytest

from app.services.pronunciation_service import (
    DEFAULT_VOICE, PRONUNCIATION_LAYER_VERSION, PronunciationError,
    SynthesisPlan, SynthesisSpan, _edge_synthesis_groups, _edge_trim_window,
    build_azure_ssml, canonical_lexicon_entries, load_pronunciation_lexicon,
    pronunciation_cache_identity, provider_capabilities, resolve_synthesis_plan,
    synthesis_plan_cache_payload, validate_provider_plan,
)

def test_lexicon_has_only_human_approved_runtime_overrides():
    lexicon=load_pronunciation_lexicon()
    assert lexicon["version"]=="2026.09.20.4-human-leonida-pending"
    assert lexicon["default_locale"]=="pt-BR"
    assert lexicon["policy"]["only_forced_en_us_term"]=="Vice City"
    entries={item["identity"]:item for item in lexicon["entries"]}
    assert set(entries)=={"vice-city","gta-6","character-lucia","leonida"}
    assert entries["vice-city"]["locale"]=="en-US"
    assert entries["vice-city"]["target_ipa"]=="vaɪs ˈsɪti"
    assert entries["gta-6"]["locale"]=="pt-BR"
    assert entries["gta-6"]["synthesis_text"]=="gê tê á seis"
    assert entries["character-lucia"]["locale"]=="pt-BR"
    assert entries["character-lucia"]["synthesis_text"]=="Lucía"
    assert entries["leonida"]["locale"]=="pt-BR"
    assert entries["leonida"]["synthesis_text"]=="Leônida"

def test_names_and_brands_stay_in_ptbr_lane():
    text="A Rockstar apresentou Jason, Lucia e Leonida no YouTube para PlayStation e Xbox."
    plan=resolve_synthesis_plan(text)
    assert plan.canonical_text_preserved
    assert plan.foreign_span_count==0
    assert plan.detected_span_count==0
    assert all(span.locale=="pt-BR" for span in plan.spans)
    groups=_edge_synthesis_groups(plan)
    assert len(groups)==1
    assert groups[0]["locale"]=="pt-BR"
    assert groups[0]["synthesis_text"]==text.replace("Lucia","Lucía").replace("Leonida","Leônida")

def test_unknown_acronyms_do_not_force_language_switches():
    plan=resolve_synthesis_plan("RTX, NVIDIA e AMD entram na conversa.")
    assert plan.detected_span_count==0
    assert plan.foreign_span_count==0

def test_explicit_foreign_metadata_cannot_bypass_policy_for_non_vice_city():
    text="Rockstar"
    plan=resolve_synthesis_plan(text,explicit_spans=[{
        "start":0,"end":len(text),"text":text,"locale":"en-US","strategy":"explicit-locale"
    }])
    assert plan.foreign_span_count==0
    assert plan.spans[0].locale=="pt-BR"

def test_vice_city_is_only_forced_en_us_term():
    text="A Rockstar mostrou Vice City e Jason comentou a novidade."
    plan=resolve_synthesis_plan(text)
    foreign=[span for span in plan.spans if span.locale!="pt-BR"]
    assert len(foreign)==1
    assert foreign[0].text=="Vice City"
    assert foreign[0].locale=="en-US"
    assert foreign[0].target_ipa=="vaɪs ˈsɪti"

def test_ptbr_to_vice_city_to_ptbr_has_only_one_foreign_group():
    text="Hoje vamos entrar em Vice City e depois voltar aos detalhes da Rockstar."
    plan=resolve_synthesis_plan(text)
    groups=_edge_synthesis_groups(plan)
    assert [item["locale"] for item in groups]==["pt-BR","en-US","pt-BR"]
    assert groups[1]["synthesis_text"]=="Vice City"

def test_gta6_alias_preserves_ptbr_prosody_and_canonical_text():
    text="Hoje vamos falar de GTA 6 sem quebrar a fluidez."
    plan=resolve_synthesis_plan(text)
    gta=next(span for span in plan.spans if span.pronunciation_identity=="gta-6")
    assert gta.text=="GTA 6"
    assert gta.synthesis_text=="gê tê á seis"
    assert gta.locale=="pt-BR"
    assert plan.foreign_span_count==0
    assert len(_edge_synthesis_groups(plan))==1
    assert plan.canonical_text==text and plan.canonical_text_preserved

def test_leonida_alias_is_synthesis_only_and_stays_in_continuous_ptbr_context():
    text="As relações de poder em Leonida conectam as Keys e outras regiões."
    plan=resolve_synthesis_plan(text)
    leonida=next(span for span in plan.spans if span.pronunciation_identity=="leonida")
    assert leonida.text=="Leonida"
    assert leonida.synthesis_text=="Leônida"
    assert leonida.locale=="pt-BR"
    assert plan.canonical_text==text
    assert plan.canonical_text_preserved is True
    assert plan.foreign_span_count==0
    groups=_edge_synthesis_groups(plan)
    assert len(groups)==1
    assert groups[0]["locale"]=="pt-BR"
    assert "Leônida" in groups[0]["synthesis_text"]
    assert groups[0]["synthesis_text"]!="Leônida"

def test_bad_explicit_span_fails_closed():
    with pytest.raises(PronunciationError):
        resolve_synthesis_plan("Vice City",explicit_spans=[{"start":0,"end":4,"text":"Vice City","locale":"en-US"}])

def test_azure_ssml_only_wraps_vice_city_in_en_us():
    ssml=build_azure_ssml(resolve_synthesis_plan("A Rockstar voltou para Vice City com Jason."))
    assert ssml.count('<lang xml:lang="en-US">')==1
    assert '<lang xml:lang="en-US">Vice City</lang>' in ssml
    assert '<lang xml:lang="en-US">Rockstar</lang>' not in ssml
    assert '<lang xml:lang="en-US">Jason</lang>' not in ssml

def test_edge_capabilities_are_truthful():
    caps=provider_capabilities("edge-tts",provider_version="7.2.8",voice=DEFAULT_VOICE)
    assert caps.supports_ssml is False
    assert caps.supports_isolated_multilingual_chunks is True
    assert caps.supports_same_voice_multilingual is True

def test_edge_fails_closed_if_phoneme_requested_but_unsupported():
    plan=SynthesisPlan(
        canonical_text="Vice City",default_locale="pt-BR",voice=DEFAULT_VOICE,
        resolver_version=PRONUNCIATION_LAYER_VERSION,lexicon_version="test",
        spans=(SynthesisSpan(0,9,"Vice City","en-US","phoneme","Vice City","explicit",target_ipa="vaɪs ˈsɪti"),),
        lexicon_hits=(),explicit_span_count=1,detected_span_count=0,resolution_wall_clock_seconds=0.0,
    )
    with pytest.raises(PronunciationError,match="phoneme"):
        validate_provider_plan(plan,provider_capabilities("edge-tts",provider_version="7.2.8",voice=DEFAULT_VOICE))

def test_cache_identity_changes_with_lexicon_version():
    plan=resolve_synthesis_plan("Vice City")
    first=pronunciation_cache_identity(plan,provider_id="edge-tts",provider_version="7.2.8",voice=DEFAULT_VOICE,rate="+0%")
    changed=replace(plan,lexicon_version=plan.lexicon_version+".next")
    second=pronunciation_cache_identity(changed,provider_id="edge-tts",provider_version="7.2.8",voice=DEFAULT_VOICE,rate="+0%")
    assert first["sha256"]!=second["sha256"]

def test_cache_payload_excludes_runtime_resolution_time():
    plan=resolve_synthesis_plan("E BR não dorme em Vice City")
    changed=replace(plan,resolution_wall_clock_seconds=plan.resolution_wall_clock_seconds+99.0)
    assert synthesis_plan_cache_payload(plan)==synthesis_plan_cache_payload(changed)

def test_canonical_entries_include_human_approved_lucia_alias():
    entries=canonical_lexicon_entries()
    by_id={item["identity"]:item for item in entries}
    assert set(by_id)=={"vice-city","gta-6","character-lucia","leonida"}
    assert by_id["character-lucia"]["synthesis_text"]=="Lucía"
    plan=resolve_synthesis_plan("Jason e Lucia chegaram a Vice City.")
    assert plan.canonical_text=="Jason e Lucia chegaram a Vice City."
    assert plan.canonical_text_preserved
    assert sum(1 for span in plan.spans if span.locale=="en-US")==1
    assert next(span for span in plan.spans if span.pronunciation_identity=="character-lucia").locale=="pt-BR"

def test_language_boundary_trim_removes_provider_padding_without_clipping_words():
    boundaries=[{"offset_seconds":0.05,"duration_seconds":0.075},{"offset_seconds":1.3625,"duration_seconds":0.2125}]
    start,end=_edge_trim_window(boundaries,1.92,trim_leading=False,trim_trailing=True)
    assert start==0.0
    assert 1.70 < end < 1.73
    vice=[{"offset_seconds":0.0875,"duration_seconds":0.4125},{"offset_seconds":0.5,"duration_seconds":0.4}]
    start2,end2=_edge_trim_window(vice,1.248,trim_leading=True,trim_trailing=False)
    assert start2==0.0
    assert end2==1.248
