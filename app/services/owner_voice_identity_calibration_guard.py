"""Fail-closed dedup guard for every BR_OWNER_V1 identity calibration.

Why: survey run 39200354064 showed 40 of the 54 calibration inliers are exact
sha256 copies (clips 45-53 x5; 101 x3; 120, 121 x2), biasing the centroid, the
pairwise/centroid p10 floors, leave-one-out outlier detection and the window
p10 toward one recording session (docs/architecture/br-owner-identity-calibration-dedup-v1.md).

Rules (proposed remediation A+C; recalculated values are NOT owner-approved):
- Calibrate on one sample per unique source clip (sha256). Segments of the same
  source clip are one sample (mean embedding / pooled windows), never independent.
- Require >= 12 unique clips.
- Effective floor = max(recorded, recalculated-with-duplicates, recalculated-dedup):
  nothing ever gets looser. Inliers = dedup inliers that were also inliers before.
- The whole-audio gate additionally requires the legacy (duplicate-weighted)
  centroid at its floor, so a centroid shift can never admit a weaker clone.
- Status stays RECALCULATED_DEDUP_PENDING_OWNER_APPROVAL until Luiz approves.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from app.services.owner_voice_speaker_identity_service import (
    _centroid,
    _quantile,
    _unit,
    calibrate_owner_identity_profile,
    calibrate_owner_window_consistency,
    calibrate_segment_identity_threshold,
    cosine_similarity,
)

# Last calibrated values (duplicate-weighted, 54 inliers / 57 materialized),
# observed identically in clone runs 38094520428 and 38158052098.
RECORDED_IDENTITY_FLOORS: dict[str, float] = {
    "clone_centroid_min_similarity": 0.8685941796030944,   # policy: 0.868594 binding
    "clone_reference_min_similarity": 0.7931407403048752,
    "window_consistency_min_similarity": 0.593494,
}
RECORDED_SOURCE = "CLONE_RUNS_38094520428_38158052098_54_INLIERS_40_EXACT_DUPLICATES"
MIN_UNIQUE_CALIBRATION_CLIPS = 12
GUARD_STATUS = "RECALCULATED_DEDUP_PENDING_OWNER_APPROVAL"
GUARD_RULE = "EFFECTIVE=MAX(RECORDED,RECALCULATED_WITH_DUPLICATES,RECALCULATED_DEDUP)"
OWNER_APPROVED_RECALCULATED_FLOORS = False   # flips only with an explicit owner record

_FLOOR_KEYS = ("clone_centroid_min_similarity", "clone_reference_min_similarity")


def _idkey(rid: str) -> tuple[int, str]:
    head = str(rid).split("s")[0].split("#")[0].split("d")[0]
    return (int(head) if head.isdigit() else 1 << 30, str(rid))


def multiplicity_from_materialization(materialized: Mapping[str, Any]) -> dict[str, int]:
    """Copies per kept reference (itself + rejected duplicates), keyed by input id."""
    mult = {str(int(r["telegram_input_id"])): 1 for r in materialized.get("references") or ()}
    for d in materialized.get("duplicate_references_rejected") or ():
        key = str(int(d["duplicate_of_input_id"]))
        if key in mult:
            mult[key] += 1
    return mult


def group_calibration_samples(
    embeddings: Mapping[str, Sequence[float]], *, sha_by_id: Mapping[str, str],
    source_by_id: Mapping[str, str] | None = None,
) -> tuple[dict[str, list[float]], dict[str, list[str]]]:
    """One sample per unique source clip: key = sha256 of the source clip audio."""
    src = dict(source_by_id or {})
    groups: dict[str, list[str]] = {}
    for rid in sorted((str(k) for k in embeddings), key=_idkey):
        source = str(src.get(rid, rid))
        sha = sha_by_id.get(source) or sha_by_id.get(rid)
        if not sha:
            raise ValueError("OWNER_CALIBRATION_SOURCE_SHA256_REQUIRED")
        groups.setdefault(str(sha), []).append(rid)
    grouped: dict[str, list[float]] = {}
    members: dict[str, list[str]] = {}
    for ids in groups.values():
        whole = [r for r in ids if str(src.get(r, r)) == r]
        rep = whole[0] if whole else str(src.get(ids[0], ids[0]))
        grouped[rep] = _centroid([embeddings[r] for r in ids])
        members[rep] = ids
    return grouped, members


def _stats(vectors: Mapping[str, Sequence[float]], ids: Sequence[str]) -> dict[str, Any]:
    centroid = _centroid([vectors[k] for k in ids])
    sims = {k: cosine_similarity(vectors[k], centroid) for k in ids}
    pairs = [cosine_similarity(vectors[a], vectors[b]) for i, a in enumerate(ids) for b in ids[i + 1:]]
    return {
        "centroid": centroid, "sims": sims,
        "clone_centroid_min_similarity": float(_quantile(list(sims.values()), 0.10)),
        "clone_reference_min_similarity": float(_quantile(pairs, 0.10)) if pairs else 1.0,
    }


def calibrate_guarded_identity_profile(
    embeddings: Mapping[str, Sequence[float]], *, sha_by_id: Mapping[str, str],
    source_by_id: Mapping[str, str] | None = None,
    multiplicity_by_id: Mapping[str, int] | None = None,
    recorded: Mapping[str, float] = RECORDED_IDENTITY_FLOORS,
) -> dict[str, Any]:
    grouped, members = group_calibration_samples(embeddings, sha_by_id=sha_by_id, source_by_id=source_by_id)
    if len(grouped) < MIN_UNIQUE_CALIBRATION_CLIPS:
        raise ValueError(f"OWNER_IDENTITY_CALIBRATION_REQUIRES_12_UNIQUE_CLIPS:{len(grouped)}")
    dedup = calibrate_owner_identity_profile(grouped)

    # Legacy multiset = what the old calibration saw (copies still in the input
    # plus copies rejected at load), reproduced exactly for the max() floor.
    mult = {str(k): max(1, int(v)) for k, v in dict(multiplicity_by_id or {}).items()}
    legacy_emb: dict[str, Sequence[float]] = {}
    for rid, vec in embeddings.items():
        for k in range(mult.get(str(rid), 1)):
            legacy_emb[str(rid) if k == 0 else f"{rid}#dup{k}"] = vec
    legacy = calibrate_owner_identity_profile(legacy_emb) if len(legacy_emb) > len(grouped) else None
    legacy_in = {str(x).split("#")[0] for x in legacy["inlier_ids"]} if legacy else None

    final = [r for r in dedup["inlier_ids"] if legacy_in is None or all(m in legacy_in for m in members[r])]
    if len(final) < 3:
        raise RuntimeError("OWNER_SPEAKER_PROFILE_TOO_FEW_INLIERS")
    st = _stats({k: _unit(v) for k, v in grouped.items()}, final)
    recalculated = {k: st[k] for k in _FLOOR_KEYS}
    with_dups = {k: float(legacy[k]) for k in _FLOOR_KEYS} if legacy else {}
    effective = {k: max([float(recorded[k]), recalculated[k], *([with_dups[k]] if with_dups else [])]) for k in _FLOOR_KEYS}

    prof = dict(dedup)
    prof.update({
        "inlier_ids": final,
        "inlier_count": len(final),
        "outlier_ids": sorted(set(grouped) - set(final), key=_idkey),
        "outlier_count": len(grouped) - len(final),
        "centroid": st["centroid"],
        "reference_similarity_to_centroid": dict(st["sims"]),
        **effective,
    })
    prof["reporting"] = {
        **{k: round(v, 6) for k, v in effective.items()},
        "reference_similarity_to_centroid": {k: round(v, 6) for k, v in st["sims"].items()},
    }
    if legacy:
        prof["guard_legacy_centroid"] = list(legacy["centroid"])
        prof["guard_legacy_centroid_min_similarity"] = max(
            float(recorded["clone_centroid_min_similarity"]), float(legacy["clone_centroid_min_similarity"]))
    prof["identity_calibration_guard"] = {
        "status": GUARD_STATUS,
        "owner_approved": bool(OWNER_APPROVED_RECALCULATED_FLOORS),
        "rule": GUARD_RULE,
        "recorded": {k: float(recorded[k]) for k in _FLOOR_KEYS},
        "recorded_source": RECORDED_SOURCE,
        "recalculated_dedup": {k: round(v, 6) for k, v in recalculated.items()},
        "recalculated_with_duplicates": {k: round(v, 6) for k, v in with_dups.items()},
        "effective": {k: round(v, 6) for k, v in effective.items()},
        "unique_clip_count": len(grouped),
        "sample_count_with_duplicates": len(legacy_emb),
        "duplicate_sample_count": len(legacy_emb) - len(grouped),
        "inlier_count": len(final),
        "legacy_centroid_also_required": bool(legacy),
        "min_unique_clips": MIN_UNIQUE_CALIBRATION_CLIPS,
    }
    return prof


def calibrate_guarded_window_consistency(
    scores_by_reference: Mapping[str, Sequence[float]], *, sha_by_id: Mapping[str, str],
    source_by_id: Mapping[str, str] | None = None,
    recorded_min: float = RECORDED_IDENTITY_FLOORS["window_consistency_min_similarity"],
) -> dict[str, Any]:
    """Window p10 with one entry per unique source clip; floor never below recorded."""
    src = dict(source_by_id or {})
    pooled: dict[str, list[float]] = {}
    seen_whole: set[tuple[str, str]] = set()
    for rid in sorted((str(k) for k in scores_by_reference), key=_idkey):
        source = str(src.get(rid, rid))
        sha = str(sha_by_id.get(source) or sha_by_id.get(rid) or "")
        if not sha:
            raise ValueError("OWNER_CALIBRATION_SOURCE_SHA256_REQUIRED")
        if source == rid:  # exact copies of a whole clip contribute once
            if (sha, "whole") in seen_whole:
                continue
            seen_whole.add((sha, "whole"))
            pooled.setdefault(sha, []).extend(float(x) for x in scores_by_reference[rid])
        else:
            pooled.setdefault(sha, []).extend(float(x) for x in scores_by_reference[rid])
    cal = calibrate_owner_window_consistency(pooled)
    recalculated = float(cal["min_similarity"])
    out = dict(cal)
    out["min_similarity"] = round(max(float(recorded_min), recalculated), 6)
    out["identity_calibration_guard"] = {
        "status": GUARD_STATUS, "owner_approved": bool(OWNER_APPROVED_RECALCULATED_FLOORS),
        "rule": "EFFECTIVE=MAX(RECORDED,RECALCULATED_DEDUP)",
        "recorded_min_similarity": float(recorded_min), "recalculated_dedup_min_similarity": recalculated,
        "unique_clip_count": len(pooled),
    }
    return out


def weighted_group_quantile(values_by_group: Mapping[str, Sequence[float]], q: float) -> float:
    """Quantile where every source clip carries total weight 1 (windows share it)."""
    pts: list[tuple[float, float]] = []
    for vals in values_by_group.values():
        vals = [float(v) for v in vals]
        if vals:
            pts.extend((v, 1.0 / len(vals)) for v in vals)
    if not pts:
        raise ValueError("SIMILARITY_DISTRIBUTION_REQUIRED")
    pts.sort()
    total = sum(w for _, w in pts)
    target = float(q) * total
    acc = 0.0
    for v, w in pts:
        acc += w
        if acc >= target - 1e-12:
            return v
    return pts[-1][0]


def calibrate_guarded_segment_identity_threshold(
    window_similarities_by_clip: Mapping[str, Sequence[float]], *, window_seconds: float,
    reference_similarities_by_clip: Mapping[str, Sequence[float]] | None = None,
) -> dict[str, Any]:
    """Authorized duration-matched p10 (OWNER_AUTHORIZED_20261011_*), never looser:
    max(p10 over all windows, p10 with each source clip weighted once)."""
    flat = [float(v) for vs in window_similarities_by_clip.values() for v in vs]
    ref_flat = None if reference_similarities_by_clip is None else [
        float(v) for vs in reference_similarities_by_clip.values() for v in vs]
    base = calibrate_segment_identity_threshold(flat, window_seconds=window_seconds,
                                                window_similarities_to_reference=ref_flat)
    out = dict(base)
    g_c = weighted_group_quantile(window_similarities_by_clip, 0.10)
    out["centroid_min_similarity"] = max(float(base["centroid_min_similarity"]), g_c)
    guard = {"status": GUARD_STATUS, "owner_approved": bool(OWNER_APPROVED_RECALCULATED_FLOORS),
             "rule": "EFFECTIVE=MAX(WINDOW_P10,SOURCE_CLIP_WEIGHTED_P10)",
             "window_centroid_min_similarity": float(base["centroid_min_similarity"]),
             "grouped_centroid_min_similarity": g_c,
             "source_clip_count": sum(1 for v in window_similarities_by_clip.values() if v)}
    if ref_flat is not None and "reference_min_similarity" in base:
        g_r = weighted_group_quantile(reference_similarities_by_clip or {}, 0.10)
        out["reference_min_similarity"] = max(float(base["reference_min_similarity"]), g_r)
        guard["window_reference_min_similarity"] = float(base["reference_min_similarity"])
        guard["grouped_reference_min_similarity"] = g_r
    out["identity_calibration_guard"] = guard
    return out
