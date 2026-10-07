from __future__ import annotations

import re
from typing import Iterable


GTA6_CANONICAL_PRONUNCIATION_TERMS: tuple[str, ...] = (
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
)

GTA6_PRONUNCIATION_SOURCE_URLS: tuple[str, ...] = (
    "https://www.rockstargames.com/VI",
    "https://www.rockstargames.com/VI/only-in-leonida",
    "https://www.rockstargames.com/VI/media/videos",
)

# Deliberately no Portuguese respellings or guessed IPA aliases here.
# Canonical spelling authority is Rockstar Games; acoustic pronunciation authority
# is the authorized human owner's Telegram reference audio.
def gta6_pronunciation_hotwords() -> str:
    return " ".join(GTA6_CANONICAL_PRONUNCIATION_TERMS)


def _normalized(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


def gta6_lexicon_hits(text: str) -> tuple[str, ...]:
    haystack = f" {_normalized(text)} "
    hits: list[str] = []
    for term in GTA6_CANONICAL_PRONUNCIATION_TERMS:
        needle = _normalized(term)
        if needle and f" {needle} " in haystack:
            hits.append(term)
    return tuple(hits)


def contains_gta6_pronunciation_target(text: str) -> bool:
    return bool(gta6_lexicon_hits(text))


def iter_gta6_pronunciation_terms() -> Iterable[str]:
    return iter(GTA6_CANONICAL_PRONUNCIATION_TERMS)
