from __future__ import annotations

from dataclasses import replace
import pytest

from app.services.pronunciation_service import (
    DEFAULT_VOICE,
    PRONUNCIATION_LAYER_VERSION,
    PronunciationError,
    SynthesisPlan,
    SynthesisSpan,
    build_azure_ssml,
    canonical_lexicon_entries,
    load_pronunciation_lexicon,
    pronunciation_cache_identity,
    provider_capabilities,
    resolve_synthesis_plan,
    synthesis_plan_cache_payload,
    validate_provider_plan,
)


# Política vigente (0e3d4389 + d2a2d86f, 10/10/2026): o léxico ATIVO de narração
# fica VAZIO até haver evidência acústica verificada dos dois trailers aprovados
# (f8IZhKcuEts, K6rVM6gn6k4). "Never resurrect prior human-rejected guesses
# merely for stale tests." A leitura do dono "vaicy siti" vive só no dicionário
# crítico da audição (config/gta6_owner_audio_pronunciation_dictionary_v1.json).


def test_lexicon_is_governed_owner_qwen_code_switch_without_respellings():
    lexicon=load_pronunciation_lexicon()
    assert lexicon["version"]=="2026.10.10.1-video-acoustic-only-pending"
    assert lexicon["default_locale"]=="pt-BR"
    assert lexicon["policy"]["governed_foreign_chunks_only"] is True
    assert lexicon["policy"]["foreign_language_chunks_forbidden"] is True
    assert lexicon["policy"]["arbitrary_foreign_chunks_forbidden"] is True
    assert lexicon["policy"]["same_owner_voice_required"] is True
    assert lexicon["policy"]["acoustic_reference_required"] is True
    assert lexicon["policy"]["pronunciation_reference_video_ids"]==["f8IZhKcuEts","K6rVM6gn6k4"]
    # Nenhuma respelling/leitura antiga é ressuscitada sem evidência acústica.
    assert lexicon["entries"]==[]

def test_governed_gta_names_code_switch_without_mutating_canonical_text():
    text="A Rockstar apresentou Jason, Lucia e Leonida no YouTube para PlayStation e Xbox."
    plan=resolve_synthesis_plan(text)
    assert plan.canonical_text_preserved
    assert plan.detected_span_count==0
    assert plan.rendered_text==text
    assert plan.lexicon_hits==()
    # Sem léxico verificado não existe chunk estrangeiro: uma faixa pt-BR contínua.
    assert plan.foreign_span_count==0
    assert all(span.locale=="pt-BR" for span in plan.spans)

def test_unknown_acronyms_do_not_force_language_switches():
    plan=resolve_synthesis_plan("RTX, NVIDIA e AMD entram na conversa.")
    assert plan.detected_span_count==0
    assert plan.foreign_span_count==0


def test_explicit_foreign_metadata_cannot_create_ungoverned_foreign_chunk():
    text="teste"
    plan=resolve_synthesis_plan(text,explicit_spans=[{
        "start":0,"end":len(text),"text":text,"locale":"en-US","strategy":"explicit-locale"
    }])
    assert plan.foreign_span_count==0
    assert plan.spans[0].locale=="pt-BR"


def test_vice_city_uses_owner_approved_brazilian_reading_without_mutating_canonical_text():
    text="A Rockstar mostrou Vice City e Jason comentou a novidade."
    plan=resolve_synthesis_plan(text)
    assert plan.canonical_text_preserved is True
    assert plan.rendered_text==text
    assert "vice-city" not in plan.lexicon_hits
    assert all(span.locale=="pt-BR" for span in plan.spans)

def test_qwen_provider_accepts_governed_vice_city_code_switch():
    plan=resolve_synthesis_plan("Hoje vamos entrar em Vice City e voltar aos detalhes.")
    caps=provider_capabilities("qwen3-tts",provider_version="0.1.1",voice=DEFAULT_VOICE)
    assert caps.supports_isolated_multilingual_chunks is True
    assert caps.supports_same_voice_multilingual is True
    validate_provider_plan(plan,caps)


def test_gta6_alias_preserves_ptbr_prosody_and_canonical_text():
    text="Hoje vamos falar de GTA 6 sem quebrar a fluidez."
    plan=resolve_synthesis_plan(text)
    assert plan.canonical_text==text and plan.canonical_text_preserved
    assert plan.rendered_text==text
    assert "Gê Tê A seis" not in plan.rendered_text
    assert all(span.locale=="pt-BR" for span in plan.spans)

def test_leonida_uses_canonical_spelling_in_governed_english_segment():
    text="As relações de poder em Leonida conectam as Keys e outras regiões."
    plan=resolve_synthesis_plan(text)
    assert plan.canonical_text==text
    assert plan.canonical_text_preserved is True
    assert plan.rendered_text==text
    assert plan.foreign_span_count==0

def test_bad_explicit_span_fails_closed():
    with pytest.raises(PronunciationError):
        resolve_synthesis_plan(
            "Vice City",
            explicit_spans=[{"start":0,"end":4,"text":"Vice City","locale":"en-US"}],
        )


def test_provider_without_same_owner_multilingual_identity_fails_closed():
    # O gate continua: qualquer chunk estrangeiro fora do léxico governado
    # (hoje vazio) é recusado antes de virar SSML.
    plan=SynthesisPlan(
        canonical_text="Vice City",
        default_locale="pt-BR",
        voice=DEFAULT_VOICE,
        resolver_version=PRONUNCIATION_LAYER_VERSION,
        lexicon_version="test",
        spans=(SynthesisSpan(0,9,"Vice City","en-US","language-switch","Vice City","lexicon"),),
        lexicon_hits=(),
        explicit_span_count=0,
        detected_span_count=0,
        resolution_wall_clock_seconds=0.0,
    )
    with pytest.raises(PronunciationError,match="foreign-language"):
        build_azure_ssml(plan)
    with pytest.raises(PronunciationError):
        validate_provider_plan(plan,provider_capabilities("qwen3-tts",provider_version="0.1.1",voice=DEFAULT_VOICE))

def test_uncertified_provider_fails_closed_if_phoneme_requested():
    plan=SynthesisPlan(
        canonical_text="Vice City",
        default_locale="pt-BR",
        voice=DEFAULT_VOICE,
        resolver_version=PRONUNCIATION_LAYER_VERSION,
        lexicon_version="test",
        spans=(
            SynthesisSpan(
                0,9,"Vice City","pt-BR","phoneme","Vice City","explicit",
                target_ipa="vaɪs ˈsɪti",
            ),
        ),
        lexicon_hits=(),
        explicit_span_count=1,
        detected_span_count=0,
        resolution_wall_clock_seconds=0.0,
    )
    capabilities=provider_capabilities(
        "owner-private-runtime",
        provider_version="test",
        voice=DEFAULT_VOICE,
    )
    with pytest.raises(PronunciationError,match="phoneme"):
        validate_provider_plan(plan,capabilities)


def test_cache_identity_changes_with_lexicon_version():
    plan=resolve_synthesis_plan("Vice City")
    first=pronunciation_cache_identity(
        plan,
        provider_id="owner-private-runtime",
        provider_version="1",
        voice=DEFAULT_VOICE,
        rate="+0%",
    )
    changed=replace(plan,lexicon_version=plan.lexicon_version+".next")
    second=pronunciation_cache_identity(
        changed,
        provider_id="owner-private-runtime",
        provider_version="1",
        voice=DEFAULT_VOICE,
        rate="+0%",
    )
    assert first["sha256"]!=second["sha256"]


def test_cache_payload_excludes_runtime_resolution_time():
    plan=resolve_synthesis_plan("E BR não dorme em Vice City")
    changed=replace(
        plan,
        resolution_wall_clock_seconds=plan.resolution_wall_clock_seconds+99.0,
    )
    assert synthesis_plan_cache_payload(plan)==synthesis_plan_cache_payload(changed)


def test_canonical_entries_cover_official_gta_targets_and_keep_owner_identity():
    assert tuple(canonical_lexicon_entries())==()
    plan=resolve_synthesis_plan("Jason e Lucia chegaram a Vice City.")
    assert plan.canonical_text=="Jason e Lucia chegaram a Vice City."
    assert plan.canonical_text_preserved
    assert plan.voice==DEFAULT_VOICE=="BR_OWNER_V1"
    assert all(span.locale=="pt-BR" for span in plan.spans)

def test_explicit_metadata_cannot_override_governed_vice_city_lexicon():
    text="Vice City"
    plan=resolve_synthesis_plan(text,explicit_spans=[{
        "start":0,
        "end":len(text),
        "text":text,
        "locale":"en-US",
        "strategy":"alias",
        "synthesis_text":"Váis Síti",
    }])
    # Metadata explícita nunca cria chunk estrangeiro e nunca altera o texto canônico.
    assert plan.canonical_text==text and plan.canonical_text_preserved
    assert plan.foreign_span_count==0
    assert all(span.locale=="pt-BR" for span in plan.spans)
    assert plan.lexicon_hits==()
