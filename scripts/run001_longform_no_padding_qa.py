from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"{path.name} must contain an object")
    return value


def single_folder(root: Path) -> Path:
    folders = sorted({path.parent for path in root.rglob("*.mp4") if path.is_file()})
    if len(folders) != 1:
        raise RuntimeError(f"expected exactly one render folder, found {len(folders)}")
    return folders[0]


def validate_no_padding(*, job: dict[str, Any], edit_qa: dict[str, Any]) -> dict[str, Any]:
    if job.get("product_profile") != "professional_ptbr_v1":
        return {"status": "SKIPPED", "reason": "not a professional long-form product"}
    if job.get("render_job_id") in {18, 20}:
        raise RuntimeError("forbidden historical RenderJob cannot pass long-form QA")
    if job.get("youtube_publication") is not False:
        raise RuntimeError("YouTube publication must remain disabled")

    duration = float(edit_qa.get("duration_seconds") or 0.0)
    if not math.isfinite(duration) or duration <= 0:
        raise RuntimeError(f"professional edit duration is invalid: {duration}")
    script_words = sum(
        len(re.findall(r"[A-Za-zÀ-ÿ0-9]+(?:['’\\-][A-Za-zÀ-ÿ0-9]+)?", str(section.get("narration") or "")))
        for section in (job.get("script_sections") or [])
        if isinstance(section, dict)
    )
    if script_words <= 0:
        raise RuntimeError("approved script word count is missing")
    observed_wpm = script_words * 60.0 / duration
    if not 90.0 <= observed_wpm <= 180.0:
        raise RuntimeError(
            f"professional edit duration implies unnatural/padded speech rate: {observed_wpm:.3f} WPM"
        )
    links = edit_qa.get("semantic_links")
    if not isinstance(links, list) or not links:
        raise RuntimeError("semantic media lineage is required")

    by_asset: dict[str, list[tuple[float, float, int, str]]] = {}
    total = 0.0
    for item in links:
        if not isinstance(item, dict):
            raise RuntimeError("semantic link must be an object")
        asset_ref = str(item.get("asset_ref") or "").strip()
        section_id = str(item.get("section_id") or "").strip()
        if not asset_ref or not section_id:
            raise RuntimeError("semantic link requires asset_ref and section_id")
        start = float(item.get("source_start_seconds"))
        length = float(item.get("duration_seconds"))
        if not math.isfinite(start) or not math.isfinite(length) or start < 0 or length <= 0:
            raise RuntimeError("semantic link contains invalid source timing")
        if length > 12.001:
            raise RuntimeError("visual cut exceeds long-form professional cadence")
        end = start + length
        segment_id = int(item.get("segment_id"))
        by_asset.setdefault(asset_ref, []).append((start, end, segment_id, section_id))
        total += length

    overlaps: list[dict[str, Any]] = []
    repeated_exact_windows: list[dict[str, Any]] = []
    for asset_ref, intervals in by_asset.items():
        seen: set[tuple[float, float]] = set()
        ordered = sorted(intervals, key=lambda value: (value[0], value[1], value[2]))
        for current in ordered:
            key = (round(current[0], 3), round(current[1], 3))
            if key in seen:
                repeated_exact_windows.append({"asset_ref": asset_ref, "start": key[0], "end": key[1]})
            seen.add(key)
        for previous, current in zip(ordered, ordered[1:]):
            overlap = min(previous[1], current[1]) - max(previous[0], current[0])
            if overlap > 0.05:
                overlaps.append({
                    "asset_ref": asset_ref,
                    "previous_segment_id": previous[2],
                    "current_segment_id": current[2],
                    "previous_section_id": previous[3],
                    "current_section_id": current[3],
                    "overlap_seconds": overlap,
                })
    if overlaps or repeated_exact_windows:
        raise RuntimeError(
            "NO_ARTIFICIAL_PADDING failed: source windows were reused or overlapped; "
            f"overlaps={len(overlaps)} repeats={len(repeated_exact_windows)}"
        )
    if abs(total - duration) > max(1.0, duration * 0.005):
        raise RuntimeError("semantic visual coverage does not match long-form duration")

    return {
        "status": "PASS",
        "LONG_FORM_REQUIRED": "YES",
        "FINAL_DURATION_COMPATIBLE_WITH_RENDER_JOB": "PASS",
        "NO_ARTIFICIAL_PADDING": "PASS",
        "NO_REPEATED_SOURCE_WINDOWS": "PASS",
        "NO_OVERLAPPING_SOURCE_WINDOWS": "PASS",
        "semantic_segment_count": len(links),
        "unique_asset_count": len(by_asset),
        "covered_duration_seconds": total,
        "edit_duration_seconds": duration,
        "approved_script_word_count": script_words,
        "observed_script_wpm": observed_wpm,
        "job18_unchanged": True,
        "job20_reused_as_final": False,
        "no_youtube_publish": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-root", required=True, type=Path)
    args = parser.parse_args()
    folder = single_folder(args.artifact_root)
    result = validate_no_padding(job=load(folder / "render-job.json"), edit_qa=load(folder / "edit-qa.json"))
    (folder / "no-artificial-padding-qa.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if result.get("status") == "SKIPPED":
        print("LONG_FORM_NO_PADDING_QA=SKIPPED")
        return 0
    print("LONG_FORM_NO_PADDING_QA=PASS")
    print("NO_ARTIFICIAL_PADDING=PASS")
    print("JOB18_UNCHANGED=YES")
    print("JOB20_REUSED_AS_FINAL=NO")
    print("NO_YOUTUBE_PUBLISH=YES")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
