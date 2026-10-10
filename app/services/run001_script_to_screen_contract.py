"""Fail-closed script-to-screen coverage contract; no render or release authority."""
from __future__ import annotations
import hashlib
import json

class ScreenContractError(ValueError):
    pass

def verify_script_to_screen(script: dict, plan: dict) -> dict:
    """Require every narrated segment to have grounded, timed, distinct visual coverage."""
    segments = script.get("segments")
    shots = plan.get("shots")
    if not isinstance(segments, list) or not segments or not isinstance(shots, list) or not shots:
        raise ScreenContractError("MISSING_SCRIPT_SEGMENTS_OR_SHOTS")
    ids = [s.get("id") for s in segments]
    if any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
        raise ScreenContractError("INVALID_SEGMENT_IDENTITIES")
    if any(not isinstance(s.get("text"), str) or not s["text"].strip() for s in segments):
        raise ScreenContractError("EMPTY_NARRATION")
    by_segment = {i: [] for i in ids}
    for shot in shots:
        sid = shot.get("segment_id")
        if sid not in by_segment:
            raise ScreenContractError("SHOT_WITHOUT_SCRIPT_SEGMENT")
        if not all(isinstance(shot.get(k), str) and shot[k].strip() for k in ("asset_id", "source_ref", "visual_purpose", "evidence_ref")):
            raise ScreenContractError("UNPROVEN_VISUAL_ASSET")
        if shot.get("rights_status") != "CLEARED":
            raise ScreenContractError("UNCLEARED_MEDIA_RIGHTS")
        start, end = shot.get("start_ms"), shot.get("end_ms")
        if not isinstance(start, int) or isinstance(start, bool) or not isinstance(end, int) or isinstance(end, bool) or start < 0 or end <= start:
            raise ScreenContractError("INVALID_SHOT_TIMING")
        by_segment[sid].append((start, end))
    for segment in segments:
        start, end = segment.get("start_ms"), segment.get("end_ms")
        if not isinstance(start, int) or isinstance(start, bool) or not isinstance(end, int) or isinstance(end, bool) or start < 0 or end <= start:
            raise ScreenContractError("INVALID_SEGMENT_TIMING")
        cursor = start
        for a, b in sorted(by_segment[segment["id"]]):
            if a > cursor or a < start or b > end:
                raise ScreenContractError("UNCOVERED_OR_OUT_OF_BOUNDS_NARRATION")
            cursor = max(cursor, b)
        if cursor != end:
            raise ScreenContractError("UNCOVERED_NARRATION")
    digest = hashlib.sha256(json.dumps({"script": script, "plan": plan}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return {"schema": "BRScriptToScreenCoverage/v1", "status": "PASS", "input_sha256": digest, "segments_covered": len(ids), "shots_checked": len(shots), "semantic_alignment": "REQUIRES_INDEPENDENT_PERCEPTUAL_QA", "render_authorized": False, "upload_authorized": False}
