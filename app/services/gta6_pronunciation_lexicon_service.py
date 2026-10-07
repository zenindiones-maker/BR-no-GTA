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


GTA6_SYNTHESIS_OVERRIDES: tuple[dict[str, str], ...] = (
    {"canonical_text":"GTA 6","spoken_text":"Gê Tê A seis","language":"Portuguese"},
    {"canonical_text":"GTA VI","spoken_text":"Gê Tê A seis","language":"Portuguese"},
    *tuple(
        {"canonical_text":term,"spoken_text":term,"language":"English"}
        for term in GTA6_CANONICAL_PRONUNCIATION_TERMS
    ),
)


def build_gta6_pronunciation_segments(text: str) -> tuple[dict[str, str | bool], ...]:
    raw=str(text or "")
    if not raw.strip():
        return ()
    overrides=sorted(
        GTA6_SYNTHESIS_OVERRIDES,
        key=lambda row:len(row["canonical_text"]),
        reverse=True,
    )
    pattern=re.compile(
        "|".join(re.escape(row["canonical_text"]) for row in overrides),
        flags=re.IGNORECASE,
    )
    by_key={row["canonical_text"].casefold():row for row in overrides}
    segments: list[dict[str, str | bool]]=[]
    cursor=0

    def append_context(value: str) -> None:
        cleaned=value.strip()
        if cleaned and re.search(r"[A-Za-zÀ-ÿ0-9]",cleaned):
            segments.append({
                "canonical_text":cleaned,
                "spoken_text":cleaned,
                "language":"Portuguese",
                "is_pronunciation_target":False,
            })

    for match in pattern.finditer(raw):
        append_context(raw[cursor:match.start()])
        matched=match.group(0)
        rule=by_key[matched.casefold()]
        segments.append({
            "canonical_text":rule["canonical_text"],
            "spoken_text":rule["spoken_text"],
            "language":rule["language"],
            "is_pronunciation_target":True,
        })
        cursor=match.end()
    append_context(raw[cursor:])
    return tuple(segments)
