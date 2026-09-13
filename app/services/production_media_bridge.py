"""Explicit composition of already selected segments, without media acquisition."""
from copy import deepcopy
import math
from app.database.content_segment_repository import get_content_segment
from app.database.content_unit_repository import get_content_unit


def bind_selected_segments(production_plan, scene_segment_ids):
    plan = deepcopy(production_plan)
    scenes = plan["scenes"]
    if len(scene_segment_ids) != len(scenes):
        raise ValueError("Each production scene requires its selected segment_id")
    for scene, segment_id in zip(scenes, scene_segment_ids):
        if type(segment_id) is not int or segment_id <= 0:
            raise ValueError("Selected segment_id must be a positive integer")
        segment = get_content_segment(segment_id)
        if not segment:
            raise ValueError("Selected content segment is missing")
        unit = get_content_unit(segment["content_unit_id"])
        if not unit or any(unit[key] != plan[key] for key in ("content_item_id", "script_id", "idea_id")):
            raise ValueError("Selected segment belongs to another production lineage")
        for key in ("asset_ref", "source_url"):
            if not isinstance(segment.get(key), str) or not segment[key].strip():
                raise ValueError(f"Selected segment missing {key}")
        start, end, duration = (segment[key] for key in ("source_start_seconds", "source_end_seconds", "duration_seconds"))
        if not all(type(v) in (int, float) and math.isfinite(v) for v in (start, end, duration)) or start < 0 or duration <= 0 or end < start + duration:
            raise ValueError("Invalid selected source window")
        if abs(scene["duration_seconds"] - duration) > .001:
            raise ValueError("Scene/selected segment duration mismatch; production decision required")
        scene.update({key: segment[key] for key in ("content_unit_id", "asset_ref", "source_url", "source_start_seconds", "source_end_seconds")})
        scene["segment_id"] = segment_id
        # Logical identity only. Physical paths are assigned by the cloud worker.
        scene.pop("media_path", None)
        scene.pop("file_path", None)
    return plan
