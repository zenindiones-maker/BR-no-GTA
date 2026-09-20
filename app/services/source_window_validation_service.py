from __future__ import annotations

import math
from typing import Any

DEFAULT_OVERLAP_TOLERANCE_SECONDS = 0.05


def validate_source_window_usage(
    semantic_links: list[dict[str, Any]],
    *,
    overlap_tolerance_seconds: float = DEFAULT_OVERLAP_TOLERANCE_SECONDS,
) -> dict[str, Any]:
    if not isinstance(semantic_links, list) or not semantic_links:
        raise ValueError("semantic media lineage is required")
    by_asset: dict[str, list[dict[str, Any]]] = {}
    total = 0.0
    for item in semantic_links:
        if not isinstance(item, dict):
            raise ValueError("semantic link must be an object")
        asset_ref = str(item.get("asset_ref") or "").strip()
        section_id = str(item.get("section_id") or "").strip()
        if not asset_ref or not section_id:
            raise ValueError("semantic link requires asset_ref and section_id")
        start = float(item.get("source_start_seconds"))
        length = float(item.get("duration_seconds"))
        if not math.isfinite(start) or not math.isfinite(length) or start < 0 or length <= 0:
            raise ValueError("semantic link contains invalid source timing")
        if length > 12.001:
            raise ValueError("visual cut exceeds long-form professional cadence")
        record = {
            "asset_ref": asset_ref,
            "segment_id": int(item.get("segment_id")),
            "section_id": section_id,
            "start": start,
            "end": start + length,
            "duration_seconds": length,
        }
        by_asset.setdefault(asset_ref, []).append(record)
        total += length

    overlaps: list[dict[str, Any]] = []
    repeated_exact_windows: list[dict[str, Any]] = []
    for asset_ref, intervals in by_asset.items():
        ordered = sorted(intervals, key=lambda value: (value["start"], value["end"], value["segment_id"]))
        seen: set[tuple[float, float]] = set()
        for current in ordered:
            key = (round(current["start"], 6), round(current["end"], 6))
            if key in seen:
                repeated_exact_windows.append({
                    "asset_ref": asset_ref,
                    "segment_id": current["segment_id"],
                    "section_id": current["section_id"],
                    "start": key[0],
                    "end": key[1],
                })
            seen.add(key)
        for previous, current in zip(ordered, ordered[1:]):
            overlap = min(previous["end"], current["end"]) - max(previous["start"], current["start"])
            if overlap > overlap_tolerance_seconds:
                overlaps.append({
                    "asset_ref": asset_ref,
                    "previous_segment_id": previous["segment_id"],
                    "current_segment_id": current["segment_id"],
                    "previous_section_id": previous["section_id"],
                    "current_section_id": current["section_id"],
                    "previous_start_seconds": previous["start"],
                    "previous_end_seconds": previous["end"],
                    "current_start_seconds": current["start"],
                    "current_end_seconds": current["end"],
                    "overlap_seconds": overlap,
                })

    return {
        "status": "PASS" if not overlaps and not repeated_exact_windows else "FAIL",
        "NO_ARTIFICIAL_PADDING": "PASS" if not overlaps and not repeated_exact_windows else "FAIL",
        "NO_REPEATED_SOURCE_WINDOWS": "PASS" if not repeated_exact_windows else "FAIL",
        "NO_OVERLAPPING_SOURCE_WINDOWS": "PASS" if not overlaps else "FAIL",
        "semantic_segment_count": len(semantic_links),
        "unique_asset_count": len(by_asset),
        "covered_duration_seconds": total,
        "overlap_count": len(overlaps),
        "repeat_count": len(repeated_exact_windows),
        "overlaps": overlaps,
        "repeated_exact_windows": repeated_exact_windows,
        "overlap_tolerance_seconds": overlap_tolerance_seconds,
    }
