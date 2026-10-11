"""BR_OWNER_V1 Qwen reference bounding (v5d).

Run 38147026694 used a single 36.014 s canonical owner clip as Qwen ref_audio
(composite selection rejected it for exceeding 30 s) and segment 3 ran away.
This module keeps the reference owner-only but bounds it: a 10-20 s window cut
inside silence gaps of the canonical clip, identity re-verified against the
owner centroid, and ref_text = ASR transcript of exactly that trimmed audio.
No voice data is printed or persisted here; thresholds are not changed.
"""
from __future__ import annotations

import itertools
import re
import unicodedata
from typing import Callable, Sequence

MAX_QWEN_REFERENCE_SECONDS = 30.0
WINDOW_MIN_SECONDS = 10.0
WINDOW_MAX_SECONDS = 20.0
COMPOSITE_MIN_SECONDS = 20.0
COMPOSITE_MAX_SECONDS = 30.0
MAX_CANDIDATE_WINDOWS = 12

Window = tuple[float, float]


def candidate_reference_windows(
    spans: Sequence[tuple[float, float]], total_seconds: float, *,
    min_seconds: float = WINDOW_MIN_SECONDS, max_seconds: float = WINDOW_MAX_SECONDS,
) -> list[Window]:
    """Windows whose edges sit at clip edges or gap midpoints between speech spans."""
    spans=sorted((float(s),float(e)) for s,e in spans if float(e)>float(s))
    if not spans:
        return []
    bounds=[max(0.0,spans[0][0]-0.15)]
    for (_s0,e0),(s1,_e1) in zip(spans,spans[1:]):
        if s1>e0:
            bounds.append(round((e0+s1)/2,3))
    bounds.append(min(float(total_seconds),spans[-1][1]+0.15))
    wins=[]
    for i,a in enumerate(bounds):
        for b in bounds[i+1:]:
            if float(min_seconds)<=b-a<=float(max_seconds):
                wins.append((round(a,3),round(b,3)))
    # prefer longer windows (more timbre context) when many exist
    wins.sort(key=lambda w:(-(w[1]-w[0]),w[0]))
    return wins[:MAX_CANDIDATE_WINDOWS]


def choose_reference_window(
    windows: Sequence[Window], similarity: Callable[[Window], float], *, min_similarity: float,
) -> tuple[Window, float]:
    if not windows:
        raise RuntimeError("OWNER_REFERENCE_WINDOW_NOT_FOUND")
    scored=[(float(similarity(w)),w) for w in windows]
    sim,best=max(scored,key=lambda x:(x[0],x[1][1]-x[1][0]))
    if sim<float(min_similarity):
        raise RuntimeError("OWNER_REFERENCE_WINDOW_IDENTITY_BELOW_FLOOR")
    return best,sim


def _norm(text: str) -> str:
    text=unicodedata.normalize("NFC",str(text or "")).lower()
    text=re.sub(r"[^\w\s]"," ",text)
    return " ".join(text.split())


def validate_qwen_reference(*, duration_seconds: float, ref_text: str, asr_transcript: str) -> None:
    if not 0.0<float(duration_seconds)<=MAX_QWEN_REFERENCE_SECONDS:
        raise RuntimeError("OWNER_QWEN_REFERENCE_TOO_LONG")
    if not _norm(ref_text) or _norm(ref_text)!=_norm(asr_transcript):
        raise RuntimeError("OWNER_QWEN_REF_TEXT_AUDIO_MISMATCH")


def validate_composite_total(durations: Sequence[float], *, gap_seconds: float) -> float:
    total=sum(float(d) for d in durations)+max(0,len(durations)-1)*float(gap_seconds)
    if not COMPOSITE_MIN_SECONDS<=total<=COMPOSITE_MAX_SECONDS:
        raise RuntimeError("OWNER_QWEN_COMPOSITE_DURATION_OUT_OF_RANGE")
    return total


COMPOSITE_PART_MIN_SECONDS = 6.0
COMPOSITE_PART_MAX_SECONDS = 15.0
COMPOSITE_MAX_COMBINATIONS = 48


def choose_composite_windows(
    candidates_by_clip: dict[str, Sequence[tuple[Window, float]]],
    composite_similarity: Callable[[tuple[tuple[str, Window], ...]], float],
    *, min_window_similarity: float, gap_seconds: float,
) -> tuple[tuple[tuple[str, Window], ...], float]:
    """2-3 windows from DIFFERENT owner clips, each >= min sim, total 20-30 s
    (with gaps), chosen to maximize the composite embedding similarity."""
    pool={}
    for clip,cands in candidates_by_clip.items():
        ok=sorted(((float(sim),tuple(w)) for w,sim in cands if float(sim)>=float(min_window_similarity)),reverse=True)
        if ok:
            pool[str(clip)]=[w for _s,w in ok[:2]]
    clips=sorted(pool,key=lambda c:-max(float(s) for w,s in candidates_by_clip[c]))[:5]
    combos=[]
    for k in (2,3):
        for chosen in itertools.combinations(clips,k):
            for wins in itertools.product(*(pool[c] for c in chosen)):
                parts=tuple(zip(chosen,wins))
                total=sum(w[1]-w[0] for w in wins)+(k-1)*float(gap_seconds)
                if COMPOSITE_MIN_SECONDS<=total<=COMPOSITE_MAX_SECONDS:
                    combos.append(parts)
    if not combos:
        raise RuntimeError("OWNER_QWEN_COMPOSITE_NOT_AVAILABLE")
    best=None
    for parts in combos[:COMPOSITE_MAX_COMBINATIONS]:
        sim=float(composite_similarity(parts))
        if best is None or sim>best[1]:
            best=(parts,sim)
    return best


NEAR_DUPLICATE_EMBEDDING_SIMILARITY = 0.995


def _cos(a: Sequence[float], b: Sequence[float]) -> float:
    num=sum(float(x)*float(y) for x,y in zip(a,b))
    da=sum(float(x)**2 for x in a)**0.5
    db=sum(float(y)**2 for y in b)**0.5
    return num/(da*db) if da and db else 0.0


def dedupe_reference_pool(
    rows: Sequence[dict], embeddings: dict, similarities: dict, *, min_similarity: float,
) -> tuple[list[dict], dict[str,int]]:
    """Owner clips for a multi-clip composite: one per audio content (SHA-256),
    near-duplicate embeddings (cos > 0.995) dropped, each >= min_similarity."""
    for r in rows:
        if not str(r.get("sha256") or ""):
            raise RuntimeError("OWNER_REFERENCE_SHA256_REQUIRED")
    ordered=sorted(rows,key=lambda r:-float(similarities.get(str(r["reference_id"]),-1.0)))
    seen=set();kept=[];exact=near=0
    for r in ordered:
        rid=str(r["reference_id"]);sha=str(r["sha256"])
        if sha in seen:
            exact+=1
            continue
        seen.add(sha)
        if float(similarities.get(rid,-1.0))<float(min_similarity):
            continue
        if any(_cos(embeddings[rid],embeddings[str(k["reference_id"])])>NEAR_DUPLICATE_EMBEDDING_SIMILARITY for k in kept):
            near+=1
            continue
        kept.append(r)
    return kept,{"candidates":len(rows),"exact_duplicates":exact,
                 "near_duplicates":near,"distinct_qualifying":len(kept)}
