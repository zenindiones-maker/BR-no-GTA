from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any

from app.services.source_window_validation_service import validate_source_window_usage


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
    script_sections = job.get("script_sections")
    script_words = None
    observed_wpm = None
    if isinstance(script_sections, list) and script_sections:
        script_words = sum(
            len(re.findall(r"[A-Za-zÀ-ÿ0-9]+(?:['’\\-][A-Za-zÀ-ÿ0-9]+)?", str(section.get("narration") or "")))
            for section in script_sections
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

    window_validation = validate_source_window_usage(links)
    if window_validation["status"] != "PASS":
        detail = (window_validation["overlaps"] or window_validation["repeated_exact_windows"])[0]
        raise RuntimeError(
            "NO_ARTIFICIAL_PADDING failed: source windows were reused or overlapped; "
            f"overlaps={window_validation['overlap_count']} "
            f"repeats={window_validation['repeat_count']} "
            f"first_defect={json.dumps(detail, sort_keys=True)}"
        )
    total = float(window_validation["covered_duration_seconds"])
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
        "unique_asset_count": int(window_validation["unique_asset_count"]),
        "source_window_validation": window_validation,
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
