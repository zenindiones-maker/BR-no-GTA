"""BR_OWNER_V1 Qwen reference bounding (v5d).

Run 38147026694 used a single 36.014 s canonical owner clip as Qwen ref_audio
(composite selection rejected it for exceeding 30 s) and segment 3 ran away.
This module keeps the reference owner-only but bounds it: a 10-20 s window cut
inside silence gaps of the canonical clip, identity re-verified against the
owner centroid, and ref_text = ASR transcript of exactly that trimmed audio.
No voice data is printed or persisted here; thresholds are not changed.
"""
from __future__ import annotations

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


def candidate_reference_windows(spans: Sequence[tuple[float, float]], total_seconds: float) -> list[Window]:
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
            if WINDOW_MIN_SECONDS<=b-a<=WINDOW_MAX_SECONDS:
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
