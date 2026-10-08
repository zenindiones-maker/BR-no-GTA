from __future__ import annotations

from app.services.gta6_pronunciation_lexicon_service import (
    GTA6_CANONICAL_PRONUNCIATION_TERMS,
    GTA6_PRONUNCIATION_SOURCE_URLS,
    gta6_lexicon_hits,
    gta6_pronunciation_hotwords,
    build_gta6_pronunciation_segments,
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


def test_gta6_segment_plan_forces_portuguese_letter_names_and_english_proper_nouns():
    segments=build_gta6_pronunciation_segments(
        "BR no GTA 6: Rockstar Games, Vice City, Jason Duval e Lucia Caminos."
    )
    spoken=[row["spoken_text"] for row in segments]
    languages=[row["language"] for row in segments]

    assert "Gê Tê A seis" in spoken
    assert any(row["spoken_text"]=="Rockstar Games" and row["language"]=="English" for row in segments)
    assert any(row["spoken_text"]=="vaicy siti" and row["language"]=="Portuguese" for row in segments)
    assert any(row["spoken_text"]=="Jason Duval" and row["language"]=="English" for row in segments)
    assert any(row["spoken_text"]=="Lucia Caminos" and row["language"]=="English" for row in segments)
    assert "Auto" not in languages


def test_gta6_segment_plan_keeps_portuguese_context_separate_from_foreign_terms():
    segments=build_gta6_pronunciation_segments(
        "Hoje vamos para Vice City no estado de Leonida e depois Mount Kalaga."
    )
    assert segments[0]["language"]=="Portuguese"
    assert any(row["spoken_text"]=="vaicy siti" and row["language"]=="Portuguese" for row in segments)
    assert any(row["spoken_text"]=="Leonida" and row["language"]=="English" for row in segments)
    assert any(row["spoken_text"]=="Mount Kalaga" and row["language"]=="English" for row in segments)


def test_gta6_segment_plan_covers_full_official_proper_noun_set():
    text=" | ".join(GTA6_CANONICAL_PRONUNCIATION_TERMS)
    segments=build_gta6_pronunciation_segments(text)
    english_targets={row["spoken_text"] for row in segments if row["language"]=="English"}
    assert set(GTA6_CANONICAL_PRONUNCIATION_TERMS)-{"Vice City"} <= english_targets
    assert any(row["canonical_text"]=="Vice City" and row["spoken_text"]=="vaicy siti" and row["language"]=="Portuguese" for row in segments)
