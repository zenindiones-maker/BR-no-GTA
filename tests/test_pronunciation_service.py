from __future__ import annotations

from dataclasses import replace
import json
import pytest

from app.services.pronunciation_service import (
    DEFAULT_VOICE, PRONUNCIATION_LAYER_VERSION, PronunciationError,
    SynthesisPlan, SynthesisSpan, build_azure_ssml, canonical_lexicon_entries,
    load_pronunciation_lexicon, pronunciation_cache_identity,
    provider_capabilities, resolve_synthesis_plan, synthesis_plan_cache_payload,
    validate_provider_plan, _edge_synthesis_groups, _edge_trim_window,
)

def test_lexicon_is_versioned_and_contains_vice_city():
    lexicon=load_pronunciation_lexicon()
    assert lexicon["version"]=="2026.09.19.3"
    vice=next(item for item in lexicon["entries"] if item["identity"]=="vice-city")
    assert vice["term"]=="Vice City" and vice["locale"]=="en-US"
    assert vice["target_ipa"]=="vaɪs ˈsɪti" and vice["critical"] is True

def test_vice_city_plan_preserves_canonical_text_and_marks_english_span():
    text="E BR não dorme em Vice City"
    plan=resolve_synthesis_plan(text)
    vice=next(span for span in plan.spans if span.pronunciation_identity=="vice-city")
    assert plan.canonical_text==text and plan.canonical_text_preserved
    assert "".join(span.text for span in plan.spans)==text
    assert vice.text=="Vice City" and vice.synthesis_text=="Vice City"
    assert vice.locale=="en-US" and vice.strategy=="isolated-multilingual"
    assert plan.human_approval_required is True

def test_mixed_language_sentence_resolves_multiple_domain_terms():
    plan=resolve_synthesis_plan("A Rockstar mostrou Vice City em GTA 6 no PlayStation 5.")
    identities={span.pronunciation_identity for span in plan.spans if span.pronunciation_identity}
    assert {"rockstar","vice-city","gta-6","playstation-5"}<=identities
    assert plan.canonical_text_preserved and plan.foreign_span_count>=3

def test_punctuation_is_preserved():
    text="Vice City, finalmente."
    plan=resolve_synthesis_plan(text)
    assert plan.canonical_text_preserved
    assert "," in "".join(span.text for span in plan.spans)

def test_canonical_lexicon_overrides_explicit_metadata_for_known_term():
    text="Vice City"
    plan=resolve_synthesis_plan(text,explicit_spans=[{"start":0,"end":len(text),"text":text,"locale":"en-GB","strategy":"explicit-locale"}])
    assert len(plan.spans)==1
    assert plan.spans[0].source=="lexicon"
    assert plan.spans[0].locale=="en-US"
    assert plan.spans[0].pronunciation_identity=="vice-city"

def test_bad_explicit_span_fails_closed():
    with pytest.raises(PronunciationError):
        resolve_synthesis_plan("Vice City",explicit_spans=[{"start":0,"end":4,"text":"Vice City","locale":"en-US"}])

def test_conservative_detection_handles_unknown_acronym_but_not_br():
    plan=resolve_synthesis_plan("RTX chega ao BR.")
    detected=[span for span in plan.spans if span.source=="detector"]
    assert any(span.text=="RTX" and span.locale=="en-US" for span in detected)
    assert not any(span.text=="BR" for span in detected)

def test_unknown_portuguese_text_falls_back_to_ptbr():
    plan=resolve_synthesis_plan("A cidade continua enorme e cheia de detalhes.")
    assert plan.foreign_span_count==0
    assert all(span.locale=="pt-BR" for span in plan.spans)

def test_gta6_alias_spells_acronym_without_mutating_canonical_text():
    text="GTA 6 chega depois."
    plan=resolve_synthesis_plan(text)
    gta=next(span for span in plan.spans if span.pronunciation_identity=="gta-6")
    assert gta.text=="GTA 6" and gta.synthesis_text=="gê tê á seis"
    assert gta.locale=="pt-BR" and gta.strategy=="alias"
    assert plan.canonical_text==text and plan.canonical_text_preserved
    assert plan.human_approval_required is True

def test_edge_capabilities_are_truthful():
    caps=provider_capabilities("edge-tts",provider_version="7.2.8",voice=DEFAULT_VOICE)
    assert caps.supports_ssml is False and caps.supports_phoneme is False
    assert caps.supports_custom_lexicon is False
    assert caps.supports_isolated_multilingual_chunks is True
    assert caps.supports_same_voice_multilingual is True
    assert caps.locale_enforcement=="auto-detect-per-isolated-chunk"

def test_azure_multilingual_boundary_supports_lang_but_does_not_claim_phoneme():
    caps=provider_capabilities("azure-speech",voice=DEFAULT_VOICE)
    assert caps.supports_ssml and caps.supports_language_spans
    assert caps.supports_same_voice_multilingual
    assert caps.supports_phoneme is False and caps.supports_custom_lexicon is False

def test_azure_ssml_uses_lang_for_vice_city_without_mutating_text():
    ssml=build_azure_ssml(resolve_synthesis_plan("E BR não dorme em Vice City"))
    assert '<lang xml:lang="en-US">Vice City</lang>' in ssml
    assert "Váiss" not in ssml and "Vaice" not in ssml

def test_edge_fails_closed_if_phoneme_requested_but_unsupported():
    plan=SynthesisPlan(
        canonical_text="Vice City",default_locale="pt-BR",voice=DEFAULT_VOICE,
        resolver_version=PRONUNCIATION_LAYER_VERSION,lexicon_version="test",
        spans=(SynthesisSpan(0,9,"Vice City","en-US","phoneme","Vice City","explicit",target_ipa="vaɪs ˈsɪti"),),
        lexicon_hits=(),explicit_span_count=1,detected_span_count=0,resolution_wall_clock_seconds=0.0,
    )
    with pytest.raises(PronunciationError,match="phoneme"):
        validate_provider_plan(plan,provider_capabilities("edge-tts",provider_version="7.2.8",voice=DEFAULT_VOICE))

def test_cache_identity_changes_when_lexicon_version_changes():
    plan=resolve_synthesis_plan("Vice City")
    first=pronunciation_cache_identity(plan,provider_id="edge-tts",provider_version="7.2.8",voice=DEFAULT_VOICE,rate="+0%")
    changed=replace(plan,lexicon_version=plan.lexicon_version+".next")
    second=pronunciation_cache_identity(changed,provider_id="edge-tts",provider_version="7.2.8",voice=DEFAULT_VOICE,rate="+0%")
    assert first["sha256"]!=second["sha256"]

def test_cache_payload_excludes_runtime_resolution_time():
    plan=resolve_synthesis_plan("E BR não dorme em Vice City")
    changed=replace(plan,resolution_wall_clock_seconds=plan.resolution_wall_clock_seconds+99.0)
    assert synthesis_plan_cache_payload(plan)==synthesis_plan_cache_payload(changed)
    first=pronunciation_cache_identity(plan,provider_id="edge-tts",provider_version="7.2.8",voice=DEFAULT_VOICE,rate="+0%")
    second=pronunciation_cache_identity(changed,provider_id="edge-tts",provider_version="7.2.8",voice=DEFAULT_VOICE,rate="+0%")
    assert first["sha256"]==second["sha256"]

def test_cache_identity_contains_full_contract():
    plan=resolve_synthesis_plan("E BR não dorme em Vice City")
    identity=pronunciation_cache_identity(plan,provider_id="edge-tts",provider_version="7.2.8",voice=DEFAULT_VOICE,rate="+0%",pitch="+0Hz")
    assert identity["canonical_text"]=="E BR não dorme em Vice City"
    assert identity["lexicon_version"]==plan.lexicon_version
    assert any(item["pronunciation_identity"]=="vice-city" for item in identity["spans"])

def test_lexicon_entries_are_data_not_tts_conditionals():
    entries=canonical_lexicon_entries()
    assert len(entries)>=10
    assert all("identity" in item and "locale" in item for item in entries)

def test_serialized_plan_has_observability_without_editorial_mutation():
    text="A Rockstar mostrou Vice City."
    payload=resolve_synthesis_plan(text).to_dict()
    encoded=json.dumps(payload,ensure_ascii=False)
    assert payload["canonical_text"]==text and payload["canonical_text_preserved"] is True
    assert payload["foreign_span_count"]>=2
    assert "Váiss" not in encoded and "Vaice" not in encoded


def test_gta6_alias_does_not_split_ptbr_sentence_prosody():
    text="Booooa meu povo, aqui é BR no GTA 6 e hoje vamos de novidades!"
    plan=resolve_synthesis_plan(text)
    assert plan.canonical_text==text and plan.canonical_text_preserved
    groups=_edge_synthesis_groups(plan)
    assert len(groups)==1
    assert groups[0]["locale"]=="pt-BR"
    assert "gê tê á seis" in groups[0]["synthesis_text"]
    assert groups[0]["synthesis_text"].startswith("Booooa meu povo")
    assert groups[0]["synthesis_text"].endswith("novidades!")


def test_vice_city_keeps_only_required_language_boundary():
    text="E BR não dorme em Vice City"
    plan=resolve_synthesis_plan(text)
    groups=_edge_synthesis_groups(plan)
    assert len(groups)==2
    assert [item["locale"] for item in groups]==["pt-BR","en-US"]
    assert groups[0]["synthesis_text"]=="E BR não dorme em "
    assert groups[1]["synthesis_text"]=="Vice City"
    assert groups[1]["pronunciation_identities"]==["vice-city"]


def test_mixed_branding_uses_one_ptbr_phrase_before_approved_vice_city():
    text="BR no GTA 6. E BR não dorme em Vice City."
    plan=resolve_synthesis_plan(text)
    groups=_edge_synthesis_groups(plan)
    assert len(groups)==2
    assert groups[0]["locale"]=="pt-BR"
    assert "gê tê á seis" in groups[0]["synthesis_text"]
    assert groups[1]["locale"]=="en-US"
    assert groups[1]["synthesis_text"].startswith("Vice City")


def test_language_boundary_trim_removes_provider_padding_without_clipping_words():
    boundaries=[
        {"offset_seconds":0.05,"duration_seconds":0.075},
        {"offset_seconds":1.3625,"duration_seconds":0.2125},
    ]
    start,end=_edge_trim_window(
        boundaries,
        1.92,
        trim_leading=False,
        trim_trailing=True,
    )
    assert start==0.0
    assert 1.62 < end < 1.66

    vice=[
        {"offset_seconds":0.0875,"duration_seconds":0.4125},
        {"offset_seconds":0.5,"duration_seconds":0.4},
    ]
    start2,end2=_edge_trim_window(
        vice,
        1.248,
        trim_leading=True,
        trim_trailing=False,
    )
    assert 0.04 < start2 < 0.06
    assert end2==1.248
    natural_gap=(end-(1.3625+0.2125)) + (0.0875-start2)
    assert 0.0 < natural_gap <= 0.15
