from __future__ import annotations

from app.services.voice_casting_service import (
    ROUND1_RATE,
    assign_blind_ids,
    build_speech_text,
    lexical_alignment,
    select_diagnostic_excerpt,
    select_round1_candidates,
)


def _inventory():
    return {
        "voices": [
            {"ShortName":"pt-BR-AntonioNeural","Gender":"Male","Locale":"pt-BR","Status":"GA"},
            {"ShortName":"pt-BR-FabioNeural","Gender":"Male","Locale":"pt-BR","Status":"GA"},
            {"ShortName":"pt-BR-HumbertoNeural","Gender":"Male","Locale":"pt-BR","Status":"GA"},
            {"ShortName":"pt-BR-FranciscaNeural","Gender":"Female","Locale":"pt-BR","Status":"GA"},
        ]
    }


def test_round1_prefers_live_male_pool_without_quality_ranking():
    selected, meta=select_round1_candidates(_inventory(),casting_id="cast-1")
    assert len(selected)==3
    assert all(item["Gender"]=="Male" for item in selected)
    assert meta["pool_mode"]=="male-primary"
    assert meta["selection_is_quality_ranking"] is False


def test_round1_can_supplement_when_live_male_pool_cannot_make_top2():
    inv={"voices":[
        {"ShortName":"pt-BR-AntonioNeural","Gender":"Male","Locale":"pt-BR","Status":"GA"},
        {"ShortName":"pt-BR-FranciscaNeural","Gender":"Female","Locale":"pt-BR","Status":"GA"},
        {"ShortName":"pt-BR-ThalitaNeural","Gender":"Female","Locale":"pt-BR","Status":"GA"},
    ]}
    selected, meta=select_round1_candidates(inv,casting_id="cast-2")
    assert len(selected)>=2
    assert any(item["Gender"]=="Male" for item in selected)
    assert meta["pool_mode"]=="male-primary-supplemented-live-inventory"


def test_blind_ids_are_deterministic_and_public_view_has_no_identity():
    selected,_=select_round1_candidates(_inventory(),casting_id="cast-3")
    public_a, private_a=assign_blind_ids(selected,casting_id="cast-3")
    public_b, private_b=assign_blind_ids(selected,casting_id="cast-3")
    assert public_a==public_b
    assert private_a==private_b
    assert all(set(item)=={"blind_id"} for item in public_a)
    assert all("voice_short_name" in item for item in private_a)


def test_diagnostic_excerpt_is_real_video_a_text_window():
    sections=[{
        "section_id":"A01",
        "narration":(
            "Se você tentar responder hoje qual é a situação real de GTA 6 usando apenas memória, é fácil começar o vídeo errado. "
            "A própria data de lançamento mostra por quê. "
            "Em maio de 2025, a Rockstar anunciou 26 de maio de 2026. "
            "Depois, em novembro daquele ano, publicou uma nova atualização e substituiu esse cronograma por 19 de novembro de 2026. "
            "Em 2026, a página oficial, a abertura das pré-vendas e a comunicação corporativa da Take-Two continuam apontando para 19 de novembro. "
            "Então nosso ponto de partida é simples: não vamos tratar uma informação como atual só porque ela foi verdadeira em algum momento."
        )
    }]
    section_id,text=select_diagnostic_excerpt(sections)
    assert section_id=="A01"
    assert text in sections[0]["narration"]
    assert "Rockstar" in text
    assert "2026" in text
    assert 58 <= len(text.split()) <= 95


def test_speech_text_preserves_editorial_and_audits_changes():
    editorial=(
        "GTA 6 mudou de data. Em maio de 2025, a Rockstar anunciou 26 de maio de 2026. "
        "Depois, a Take-Two confirmou 19 de novembro de 2026."
    )
    cast=build_speech_text("A01",editorial)
    assert cast.editorial_text==editorial
    assert cast.speech_text!=editorial
    assert "GTA seis" in cast.speech_text
    assert "dois mil e vinte e seis" in cast.speech_text
    assert "Take Two" in cast.speech_text
    assert all(item["original"] and item["spoken"] and item["rule"] and item["reason"] for item in cast.transformations)


def test_lexical_alignment_is_not_an_automatic_voice_ranker():
    assert lexical_alignment("rockstar anunciou gta seis","a rockstar anunciou gta seis")==1.0
    assert ROUND1_RATE=="+0%"
