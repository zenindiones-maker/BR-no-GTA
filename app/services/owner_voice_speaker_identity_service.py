from __future__ import annotations

import math
from statistics import median
from typing import Any, Mapping, Sequence

PROFILE_SCHEMA="OwnerSpeakerIdentityProfile/v1"
VOICE_IDENTITY_ID="BR_OWNER_V1"
REFERENCE_SOURCE="TELEGRAM_HUMAN_OWNER"
SPEAKER_MODEL_ID="speechbrain/spkrec-ecapa-voxceleb"
SPEAKER_MODEL_REVISION="d82a13ef4f90e62dc5e152e312a6891247f23fb8"


def _unit(values: Sequence[float]) -> list[float]:
    row=[float(x) for x in values]
    norm=math.sqrt(sum(x*x for x in row))
    if not row or norm<=0.0:
        raise ValueError("SPEAKER_EMBEDDING_INVALID")
    return [x/norm for x in row]


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    ua=_unit(a); ub=_unit(b)
    if len(ua)!=len(ub):
        raise ValueError("SPEAKER_EMBEDDING_DIMENSION_MISMATCH")
    return max(-1.0,min(1.0,sum(x*y for x,y in zip(ua,ub))))


def _centroid(rows: Sequence[Sequence[float]]) -> list[float]:
    if not rows:
        raise ValueError("OWNER_SPEAKER_EMBEDDINGS_REQUIRED")
    normalized=[_unit(row) for row in rows]
    width=len(normalized[0])
    if any(len(row)!=width for row in normalized):
        raise ValueError("SPEAKER_EMBEDDING_DIMENSION_MISMATCH")
    return _unit([sum(row[i] for row in normalized)/len(normalized) for i in range(width)])


def _quantile(values: Sequence[float], q: float) -> float:
    ordered=sorted(float(x) for x in values)
    if not ordered:
        raise ValueError("SIMILARITY_DISTRIBUTION_REQUIRED")
    if len(ordered)==1:
        return ordered[0]
    pos=max(0.0,min(1.0,float(q)))*(len(ordered)-1)
    lo=int(math.floor(pos)); hi=int(math.ceil(pos))
    if lo==hi:
        return ordered[lo]
    fraction=pos-lo
    return ordered[lo]*(1.0-fraction)+ordered[hi]*fraction


def calibrate_owner_window_consistency(
    scores_by_reference: Mapping[str,Sequence[float]],
) -> dict[str,Any]:
    rows={}
    for key,values in dict(scores_by_reference or {}).items():
        finite=[
            max(-1.0,min(1.0,float(value)))
            for value in values
            if math.isfinite(float(value))
        ]
        if finite:
            rows[str(key)]=finite
    if len(rows)<3:
        raise ValueError("OWNER_WINDOW_CONSISTENCY_REQUIRES_REFERENCES")
    reference_p10={
        key:_quantile(values,0.10)
        for key,values in rows.items()
    }
    threshold=_quantile(list(reference_p10.values()),0.10)
    return {
        "schema_version":"OwnerReferenceWindowConsistencyCalibration/v1",
        "calibration_source":"OWNER_REFERENCE_WINDOW_DISTRIBUTION",
        "reference_count":len(rows),
        "window_count":sum(len(values) for values in rows.values()),
        "min_similarity":round(float(threshold),6),
        "reference_p10_median":round(float(median(reference_p10.values())),6),
    }


def evaluate_reference_window_consistency(
    scores: Sequence[float],
    calibration: Mapping[str,Any],
) -> dict[str,Any]:
    finite=[
        max(-1.0,min(1.0,float(value)))
        for value in scores
        if math.isfinite(float(value))
    ]
    if not finite:
        raise ValueError("OWNER_REFERENCE_WINDOW_SCORES_REQUIRED")
    threshold=float(calibration["min_similarity"])
    reference_p10=float(_quantile(finite,0.10))
    return {
        "passed":reference_p10>=threshold,
        "reference_p10":round(reference_p10,6),
        "reference_median":round(float(median(finite)),6),
        "min_similarity":threshold,
        "calibration_source":str(calibration.get("calibration_source") or ""),
    }


def calibrate_owner_identity_profile(
    embeddings: Mapping[str,Sequence[float]],
) -> dict[str,Any]:
    if len(embeddings)<3:
        raise ValueError("OWNER_SPEAKER_PROFILE_REQUIRES_AT_LEAST_THREE_REFERENCES")
    ids=sorted(str(key) for key in embeddings)
    vectors={key:_unit(embeddings[key]) for key in ids}
    loo={}
    for key in ids:
        others=[vectors[other] for other in ids if other!=key]
        loo[key]=cosine_similarity(vectors[key],_centroid(others))
    values=list(loo.values())
    med=float(median(values))
    p10=float(_quantile(values,0.10))
    mad=float(median([abs(x-med) for x in values]))
    robust_lower=med-(3.0*1.4826*mad)
    outliers=sorted(
        key for key,value in loo.items()
        if value<p10 and value<robust_lower
    )
    inliers=[key for key in ids if key not in set(outliers)]
    if len(inliers)<3:
        raise RuntimeError("OWNER_SPEAKER_PROFILE_TOO_FEW_INLIERS")
    centroid=_centroid([vectors[key] for key in inliers])
    centroid_sims={key:cosine_similarity(vectors[key],centroid) for key in inliers}
    pairwise=[
        cosine_similarity(vectors[a],vectors[b])
        for i,a in enumerate(inliers)
        for b in inliers[i+1:]
    ]
    clone_centroid_min=float(_quantile(list(centroid_sims.values()),0.10))
    clone_reference_min=float(_quantile(pairwise,0.10))
    return {
        "schema_version":PROFILE_SCHEMA,
        "voice_identity_id":VOICE_IDENTITY_ID,
        "reference_source":REFERENCE_SOURCE,
        "speaker_model_id":SPEAKER_MODEL_ID,
        "speaker_model_revision":SPEAKER_MODEL_REVISION,
        "reference_count":len(ids),
        "inlier_count":len(inliers),
        "outlier_count":len(outliers),
        "inlier_ids":inliers,
        "outlier_ids":outliers,
        "intra_speaker_similarity_median":round(med,6),
        "intra_speaker_similarity_p10":round(p10,6),
        "robust_mad":round(mad,6),
        "clone_centroid_min_similarity":round(clone_centroid_min,6),
        "clone_reference_min_similarity":round(clone_reference_min,6),
        "reference_similarity_to_centroid":{key:round(value,6) for key,value in centroid_sims.items()},
        "centroid":centroid,
        "threshold_calibration":"OWNER_INTRA_SPEAKER_P10",
    }


def evaluate_clone_identity_gate(
    profile: Mapping[str,Any],
    *,
    clone_embedding: Sequence[float],
    canonical_embedding: Sequence[float],
) -> dict[str,Any]:
    if profile.get("schema_version")!=PROFILE_SCHEMA:
        raise ValueError("OWNER_SPEAKER_PROFILE_INVALID")
    centroid=profile.get("centroid")
    if not isinstance(centroid,list):
        raise ValueError("OWNER_SPEAKER_CENTROID_REQUIRED")
    to_centroid=cosine_similarity(clone_embedding,centroid)
    to_reference=cosine_similarity(clone_embedding,canonical_embedding)
    centroid_min=float(profile["clone_centroid_min_similarity"])
    reference_min=float(profile["clone_reference_min_similarity"])
    return {
        "passed":to_centroid>=centroid_min and to_reference>=reference_min,
        "similarity_to_centroid":round(to_centroid,6),
        "similarity_to_reference":round(to_reference,6),
        "centroid_min_similarity":centroid_min,
        "reference_min_similarity":reference_min,
        "calibration":"OWNER_INTRA_SPEAKER_P10",
    }


def select_canonical_reference(
    candidates: Sequence[Mapping[str,Any]],
    profile: Mapping[str,Any],
) -> dict[str,Any]:
    inliers=set(str(x) for x in profile.get("inlier_ids") or [])
    similarities=dict(profile.get("reference_similarity_to_centroid") or {})
    threshold=float(profile["clone_centroid_min_similarity"])
    eligible=[]
    for raw in candidates:
        row=dict(raw)
        ref_id=str(row.get("reference_id") or row.get("telegram_input_id") or "")
        sim=float(similarities.get(ref_id,-1.0))
        technical=bool(
            ref_id in inliers
            and row.get("single_speaker") is True
            and row.get("clear_speech") is True
            and row.get("no_overlap") is True
            and row.get("no_music") is True
            and float(row.get("ptbr_probability") or 0.0)>=0.90
            and float(1.0 if row.get("clipping_ratio") is None else row.get("clipping_ratio"))<=0.01
            and float(row.get("speech_ratio") or 0.0)>=0.55
            and float(row.get("duration_seconds") or 0.0)>0.0
            and sim>=threshold
        )
        if not technical:
            continue
        row["identity_inlier"]=True
        row["identity_similarity_to_centroid"]=sim
        row["canonical_reference_identity_match"]=True
        duration=float(row.get("duration_seconds") or 0.0)
        preferred=10.0<=duration<=20.0
        row["_rank"]=(
            0 if preferred else 1,
            -sim,
            -float(row.get("ptbr_probability") or 0.0),
            -float(row.get("snr_db") or 0.0),
            float(row.get("clipping_ratio") or 0.0),
            abs(duration-15.0),
            str(row.get("sha256") or ""),
        )
        eligible.append(row)
    if not eligible:
        raise RuntimeError("NO_CANONICAL_OWNER_REFERENCE_ELIGIBLE")
    eligible.sort(key=lambda row:row["_rank"])
    selected=dict(eligible[0]); selected.pop("_rank",None)
    return selected


def sanitized_profile(profile: Mapping[str,Any]) -> dict[str,Any]:
    return {
        key:value for key,value in dict(profile).items()
        if key not in {"centroid","reference_similarity_to_centroid"}
    }
