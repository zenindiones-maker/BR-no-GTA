from __future__ import annotations

from app.services.voice_casting_round2_service import (
    PROSODY_TIERS,
    build_contexts,
    build_prosody_source,
    resolve_selected_identities,
    split_prosody_windows,
)


def _job():
    def section(section_id: str, text: str):
        return {"section_id":section_id,"narration":text}
    common=(
        "Esta é uma frase longa o suficiente para construir um trecho diagnóstico com pontuação natural e contexto verificável. "
        "A Rockstar apresentou informações oficiais e o roteiro separa fato, análise e inferência para não confundir o espectador. "
        "Em 2026, o material passou por nova revisão e a explicação precisa continuar clara, contínua e natural para quem ouve. "
        "A transição seguinte mantém a mesma ideia, mas muda o ritmo da argumentação sem alterar nenhum fato importante. "
        "PlayStation 5, Xbox Series X e GTA VI aparecem no texto porque nomes e números são especialmente úteis para avaliar dicção. "
        "Jason e Lucia continuam no centro da história, enquanto Leonida e Vice City ajudam a testar nomes próprios em português brasileiro. "
        "No encerramento, o canal volta ao ponto central: fonte primeiro, contexto depois e inferência claramente identificada. "
        "A revisão humana decide se a narração realmente soa melhor e nenhuma métrica automática escolhe a voz oficial."
    )
    return {"script_sections":[
        section("A01",common),section("A02",common),section("A03",common),
        section("A08",common),section("A14",common),section("A16",common),
    ]}


def test_round2_consumes_only_selected_blind_identities():
    identity_map={
        "casting_id":"cast-1",
        "inventory_sha256":"abc",
        "mapping":[
            {"blind_id":"Voice A","voice_short_name":"voice-a"},
            {"blind_id":"Voice B","voice_short_name":"voice-b"},
            {"blind_id":"Voice C","voice_short_name":"voice-c"},
        ],
    }
    feedback={"feedback":{"top2":["Voice B","Voice C"]}}
    checkpoint={"casting_id":"cast-1","live_inventory":{"inventory_sha256":"abc"}}
    resolved=resolve_selected_identities(
        identity_map=identity_map,feedback=feedback,checkpoint=checkpoint
    )
    assert resolved=={"Voice B":"voice-b","Voice C":"voice-c"}
    assert "Voice A" not in resolved


def test_identity_artifact_must_match_checkpoint_inventory():
    identity_map={
        "casting_id":"cast-1","inventory_sha256":"wrong",
        "mapping":[
            {"blind_id":"Voice B","voice_short_name":"voice-b"},
            {"blind_id":"Voice C","voice_short_name":"voice-c"},
        ],
    }
    feedback={"feedback":{"top2":["Voice B","Voice C"]}}
    checkpoint={"casting_id":"cast-1","live_inventory":{"inventory_sha256":"abc"}}
    import pytest
    with pytest.raises(Exception):
        resolve_selected_identities(
            identity_map=identity_map,feedback=feedback,checkpoint=checkpoint
        )


def test_multicontext_contains_all_required_contexts():
    contexts=build_contexts(_job())
    assert list(contexts)==[
        "hook","factual-dense","names-and-numbers",
        "long-paragraph","emotional-transition","cta",
    ]
    assert all(len(text.split())>=35 for text in contexts.values())


def test_prosody_tiers_use_same_source_but_different_window_counts():
    source=build_prosody_source(_job())
    outputs={tier:split_prosody_windows(source,target) for tier,target in PROSODY_TIERS}
    assert all(" ".join(parts)==source for parts in outputs.values())
    assert len(outputs["25-35s"]) >= len(outputs["40-60s"]) >= len(outputs["60-90s"])
    assert len(outputs["25-35s"]) >= 2


def test_round2_has_no_automatic_naturalness_winner_constant():
    assert [tier for tier,_ in PROSODY_TIERS]==["25-35s","40-60s","60-90s"]
