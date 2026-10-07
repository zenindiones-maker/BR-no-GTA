from __future__ import annotations

import re
from difflib import SequenceMatcher
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

VICE_CITY_ASR_EVIDENCE_ALIASES: tuple[str, ...] = (
    "Vice City",
    "Vise City",
    "Vici City",
    "Vice Siti",
    "Vise Siti",
    "Vici Siti",
    "Vais City",
    "Vais Siti",
    "Vaice City",
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


def gta6_target_evidence_score(text: str, target: str) -> float:
    haystack=_normalized(text)
    needle=_normalized(target)
    if not haystack or not needle:
        return 0.0

    aliases=(target,)
    if needle==_normalized("Vice City"):
        aliases=VICE_CITY_ASR_EVIDENCE_ALIASES

    hay_words=haystack.split()
    best=0.0
    for alias in aliases:
        alias_norm=_normalized(alias)
        alias_words=alias_norm.split()
        if not alias_words:
            continue
        if f" {alias_norm} " in f" {haystack} ":
            return 1.0
        min_width=max(1,len(alias_words)-1)
        max_width=min(len(hay_words),len(alias_words)+1)
        for width in range(min_width,max_width+1):
            for start in range(0,len(hay_words)-width+1):
                window=" ".join(hay_words[start:start+width])
                score=SequenceMatcher(None,window,alias_norm).ratio()
                best=max(best,float(score))
    return round(max(0.0,min(1.0,best)),6)


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


def build_gta6_pronunciation_batches(text: str) -> tuple[dict[str, str | bool], ...]:
    atomic=list(build_gta6_pronunciation_segments(text))
    batches: list[dict[str, str | bool]]=[]
    index=0
    while index<len(atomic):
        row=atomic[index]
        if row["language"]!="English":
            batches.append(dict(row))
            index+=1
            continue

        spoken=[str(row["spoken_text"])]
        canonical=[str(row["canonical_text"])]
        index+=1
        while index<len(atomic):
            next_row=atomic[index]
            if next_row["language"]=="English":
                spoken.append(str(next_row["spoken_text"]))
                canonical.append(str(next_row["canonical_text"]))
                index+=1
                continue
            connector=_normalized(str(next_row["spoken_text"]))
            if (
                next_row["language"]=="Portuguese"
                and next_row["is_pronunciation_target"] is False
                and connector in {"e","and"}
                and index+1<len(atomic)
                and atomic[index+1]["language"]=="English"
            ):
                index+=1
                next_target=atomic[index]
                spoken.append(str(next_target["spoken_text"]))
                canonical.append(str(next_target["canonical_text"]))
                index+=1
                continue
            break
        batches.append({
            "canonical_text":" | ".join(canonical),
            "spoken_text":". ".join(spoken),
            "language":"English",
            "is_pronunciation_target":True,
        })
    return tuple(batches)
