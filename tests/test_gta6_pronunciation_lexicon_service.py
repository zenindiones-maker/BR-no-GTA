from __future__ import annotations

from app.services.gta6_pronunciation_lexicon_service import (
    GTA6_CANONICAL_PRONUNCIATION_TERMS,
    GTA6_PRONUNCIATION_SOURCE_URLS,
    gta6_lexicon_hits,
    gta6_pronunciation_hotwords,
)


def test_gta6_pronunciation_lexicon_uses_official_rockstar_spellings():
    required={
        "Rockstar Games",
        "Vice City",
        "Leonida",
        "Leonida Keys",
        "Port Gellhorn",
        "Ambrosia",
        "Grassrivers",
        "Mount Kalaga",
        "Jason Duval",
        "Lucia Caminos",
        "Cal Hampton",
        "Boobie Ike",
        "Dre'Quan Priest",
        "Real Dimez",
        "Raul Bautista",
        "Brian Heder",
    }
    assert required.issubset(set(GTA6_CANONICAL_PRONUNCIATION_TERMS))
    assert all("rockstargames.com" in url for url in GTA6_PRONUNCIATION_SOURCE_URLS)


def test_gta6_lexicon_is_canonical_not_invented_phonetic_respelling():
    hotwords=gta6_pronunciation_hotwords()
    assert "Rockstar Games" in hotwords
    assert "Vice City" in hotwords
    assert "Leonida" in hotwords
    assert "Váice" not in hotwords
    assert "Rókstar" not in hotwords


def test_gta6_lexicon_hits_code_switched_names_without_changing_spelling():
    hits=gta6_lexicon_hits(
        "Hoje: Vice City, Rockstar Games, Lucia Caminos e Dre'Quan Priest."
    )
    assert hits==(
        "Rockstar Games",
        "Vice City",
        "Lucia Caminos",
        "Dre'Quan Priest",
    )
