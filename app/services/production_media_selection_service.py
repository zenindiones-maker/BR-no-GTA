from __future__ import annotations

from typing import Any
import math
import time

from app.database.content_repository import get_content_item
from app.database.media_knowledge_repository import MediaKnowledgeRepository
from app.database.production_plan_repository import get_production_plan_by_content_item_id
from app.services.media_selection_service import (
    MediaSelectionError,
    _extract_candidate_windows,
    select_media_segments,
)


MEDIA_POOL_METADATA_KEY = "media_pool"
MEDIA_POOL_SCHEMA_VERSION = "1"
_GAP_TOLERANCE_SECONDS = 0.001


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _preflight_continuous_source(
    *,
    knowledge: dict[str, Any],
    required_duration_seconds: float,
) -> None:
    """Legacy single-source continuous coverage guard kept for compatibility."""
    candidates = _extract_candidate_windows(knowledge)
    if not candidates:
        raise MediaSelectionError("MediaKnowledge não possui nenhuma cena utilizável.")
    candidates = sorted(candidates, key=lambda item: (item["start_seconds"], item["end_seconds"]))
    window_start = candidates[0]["start_seconds"]
    window_end = window_start + required_duration_seconds
    coverage_cursor = window_start
    for candidate in candidates:
        if candidate["end_seconds"] <= coverage_cursor:
            continue
        if candidate["start_seconds"] > coverage_cursor + _GAP_TOLERANCE_SECONDS:
            break
        coverage_cursor = max(coverage_cursor, candidate["end_seconds"])
        if coverage_cursor + _GAP_TOLERANCE_SECONDS >= window_end:
            return
    raise MediaSelectionError(
        "Mídia disponível insuficiente para cobrir todo o ProductionPlan sem reutilização; "
        "nenhum ContentSegment foi criado."
    )


def _continuous_ranges(knowledge: dict[str, Any]) -> list[dict[str, float]]:
    """Collapse scene windows into reusable-free continuous source ranges."""
    candidates = sorted(
        _extract_candidate_windows(knowledge),
        key=lambda item: (item["start_seconds"], item["end_seconds"]),
    )
    ranges: list[dict[str, float]] = []
    for candidate in candidates:
        start = float(candidate["start_seconds"])
        end = float(candidate["end_seconds"])
        if not ranges or start > ranges[-1]["end_seconds"] + _GAP_TOLERANCE_SECONDS:
            ranges.append({"start_seconds": start, "end_seconds": end})
            continue
        ranges[-1]["end_seconds"] = max(ranges[-1]["end_seconds"], end)
    for item in ranges:
        item["duration_seconds"] = item["end_seconds"] - item["start_seconds"]
    return ranges


def _validate_scene_durations(scene_durations: list[float]) -> list[float]:
    if not isinstance(scene_durations, list) or not scene_durations:
        raise MediaSelectionError("ProductionPlan não possui cenas válidas.")
    normalized: list[float] = []
    for index, value in enumerate(scene_durations, start=1):
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
            raise MediaSelectionError(f"Cena {index} possui duração inválida.")
        normalized.append(float(value))
    return normalized


def build_media_pool_plan(
    *,
    knowledge_payloads: dict[int, dict[str, Any]],
    scene_durations: list[float],
    allocation_seed: int = 0,
) -> dict[str, Any]:
    """Plan every scene against multiple immutable MediaKnowledge sources before persistence.

    Planning is intentionally pure: no ContentUnit/ContentSegment is written until every
    scene has a non-overlapping continuous interval. This makes insufficient media fail
    closed before partial production lineage can be created.
    """
    durations = _validate_scene_durations(scene_durations)
    if not isinstance(knowledge_payloads, dict) or not knowledge_payloads:
        raise MediaSelectionError("MediaKnowledge pool está vazio.")

    knowledge_ids = list(knowledge_payloads)
    if any(not _positive_int(value) for value in knowledge_ids):
        raise MediaSelectionError("MediaKnowledge pool possui id inválido.")

    # Rotate deterministic tie-breaking by content identity so A/B do not always start
    # from the same source when the same pool is reused.
    ordered_ids = sorted(knowledge_ids)
    rotation = int(allocation_seed) % len(ordered_ids) if ordered_ids else 0
    ordered_ids = ordered_ids[rotation:] + ordered_ids[:rotation]
    source_rank = {knowledge_id: index for index, knowledge_id in enumerate(ordered_ids)}

    slots: list[dict[str, Any]] = []
    source_capacity: dict[int, float] = {}
    for knowledge_id in ordered_ids:
        knowledge = knowledge_payloads[knowledge_id]
        if not isinstance(knowledge, dict) or not knowledge:
            raise MediaSelectionError(f"MediaKnowledge inválido: {knowledge_id}")
        source_path = knowledge.get("source_path")
        if not isinstance(source_path, str) or not source_path.strip():
            raise MediaSelectionError(f"MediaKnowledge {knowledge_id} não possui source_path válido.")
        metadata = knowledge.get("metadata") or {}
        if isinstance(metadata, dict) and metadata.get(MEDIA_POOL_METADATA_KEY) is not None:
            raise MediaSelectionError("MediaKnowledge pools não podem ser aninhados.")

        ranges = _continuous_ranges(knowledge)
        capacity = sum(float(item["duration_seconds"]) for item in ranges)
        source_capacity[knowledge_id] = capacity
        for range_index, item in enumerate(ranges):
            slots.append(
                {
                    "knowledge_id": knowledge_id,
                    "source_path": source_path.strip(),
                    "range_index": range_index,
                    "cursor": float(item["start_seconds"]),
                    "end_seconds": float(item["end_seconds"]),
                }
            )

    required_seconds = sum(durations)
    total_capacity = sum(source_capacity.values())
    if total_capacity + _GAP_TOLERANCE_SECONDS < required_seconds:
        raise MediaSelectionError(
            "MediaKnowledge pool insuficiente: "
            f"required={required_seconds:.3f}s available={total_capacity:.3f}s; "
            "nenhum ContentSegment foi criado."
        )

    assignments: list[dict[str, Any]] = []
    for scene_index, duration in enumerate(durations, start=1):
        eligible: list[tuple[float, int, int]] = []
        for slot_index, slot in enumerate(slots):
            remaining = float(slot["end_seconds"]) - float(slot["cursor"])
            if remaining + _GAP_TOLERANCE_SECONDS >= duration:
                eligible.append((remaining, source_rank[int(slot["knowledge_id"])], slot_index))
        if not eligible:
            remaining_total = sum(
                max(0.0, float(slot["end_seconds"]) - float(slot["cursor"]))
                for slot in slots
            )
            raise MediaSelectionError(
                "MediaKnowledge pool fragmentado: nenhuma fonte contínua comporta "
                f"a cena {scene_index} ({duration:.3f}s); remaining={remaining_total:.3f}s; "
                "nenhum ContentSegment foi criado."
            )

        # Best-fit minimizes stranded tails; source rank is the deterministic tie-breaker.
        _, _, slot_index = min(eligible, key=lambda item: (item[0], item[1], item[2]))
        slot = slots[slot_index]
        start = float(slot["cursor"])
        end = start + duration
        slot["cursor"] = end
        assignments.append(
            {
                "scene_order": scene_index,
                "knowledge_id": int(slot["knowledge_id"]),
                "source_path": str(slot["source_path"]),
                "source_start_seconds": start,
                "source_end_seconds": end,
                "duration_seconds": duration,
            }
        )

    used_ids = list(dict.fromkeys(item["knowledge_id"] for item in assignments))
    return {
        "status": "ready",
        "required_seconds": required_seconds,
        "available_seconds": total_capacity,
        "scene_count": len(durations),
        "knowledge_ids": ordered_ids,
        "used_knowledge_ids": used_ids,
        "source_capacity_seconds": source_capacity,
        "assignments": assignments,
    }


def preflight_production_segment_plan(
    *,
    scene_durations: list[float],
    assignments: list[dict[str, Any]],
) -> dict[str, Any]:
    """Validate every requested segment against its source bounds before persistence."""
    started = time.perf_counter_ns()
    durations = _validate_scene_durations(scene_durations)
    if not isinstance(assignments, list) or len(assignments) != len(durations):
        raise MediaSelectionError(
            "Production segment preflight: quantidade de assignments incompatível com as cenas."
        )

    checks: list[dict[str, Any]] = []
    for scene_index, (requested_duration, assignment) in enumerate(
        zip(durations, assignments),
        start=1,
    ):
        if not isinstance(assignment, dict):
            raise MediaSelectionError(
                f"Production segment preflight: assignment inválido na cena {scene_index}."
            )
        start = assignment.get("source_start_seconds")
        end = assignment.get("source_end_seconds")
        planned = assignment.get("duration_seconds")
        for name, value in (
            ("source_start_seconds", start),
            ("source_end_seconds", end),
            ("duration_seconds", planned),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
            ):
                raise MediaSelectionError(
                    f"Production segment preflight: {name} inválido na cena {scene_index}."
                )
        start = float(start)
        end = float(end)
        planned = float(planned)
        if start < 0 or end <= start:
            raise MediaSelectionError(
                f"Production segment preflight: source bounds inválidos na cena {scene_index}."
            )
        source_duration = end - start
        if planned <= 0 or requested_duration <= 0:
            raise MediaSelectionError(
                f"Production segment preflight: duração não positiva na cena {scene_index}."
            )
        if planned - source_duration > _GAP_TOLERANCE_SECONDS:
            raise MediaSelectionError(
                "Production segment preflight: requested segment duration exceeds "
                f"available source duration na cena {scene_index}: "
                f"requested={planned:.9f}s available={source_duration:.9f}s."
            )
        if abs(planned - requested_duration) > _GAP_TOLERANCE_SECONDS:
            raise MediaSelectionError(
                "Production segment preflight: duração planejada diverge da timeline "
                f"na cena {scene_index}: requested={requested_duration:.9f}s "
                f"planned={planned:.9f}s."
            )
        checks.append(
            {
                "scene_order": int(assignment.get("scene_order") or scene_index),
                "source_start_seconds": start,
                "source_end_seconds": end,
                "source_duration_seconds": source_duration,
                "requested_segment_duration_seconds": planned,
                "timeline_duration_seconds": requested_duration,
                "delta_seconds": planned - source_duration,
                "status": "PASS",
            }
        )

    finished = time.perf_counter_ns()
    return {
        "status": "PASS",
        "scene_count": len(checks),
        "DETERMINISTIC_FAILURE_DETECTION_MS": round(
            (finished - started) / 1_000_000.0,
            3,
        ),
        "checks": checks,
    }


def _resolve_media_pool(
    repository: MediaKnowledgeRepository,
    knowledge_id: int,
) -> tuple[dict[int, dict[str, Any]], dict[str, Any]]:
    root = repository.get_payload(knowledge_id)
    metadata = root.get("metadata") or {}
    pool = metadata.get(MEDIA_POOL_METADATA_KEY) if isinstance(metadata, dict) else None
    if pool is None:
        return {knowledge_id: root}, {"pool_id": None, "knowledge_ids": [knowledge_id]}
    if not isinstance(pool, dict) or str(pool.get("schema_version")) != MEDIA_POOL_SCHEMA_VERSION:
        raise MediaSelectionError("MediaKnowledge pool possui schema inválido.")
    child_ids = pool.get("knowledge_ids")
    if not isinstance(child_ids, list) or not child_ids:
        raise MediaSelectionError("MediaKnowledge pool não possui knowledge_ids.")
    normalized: list[int] = []
    for value in child_ids:
        if not _positive_int(value):
            raise MediaSelectionError("MediaKnowledge pool possui knowledge_id inválido.")
        if value == knowledge_id:
            raise MediaSelectionError("MediaKnowledge pool não pode referenciar a si próprio.")
        if value not in normalized:
            normalized.append(value)
    payloads = {value: repository.get_payload(value) for value in normalized}
    return payloads, {"pool_id": knowledge_id, "knowledge_ids": normalized}


def inspect_media_pool(
    *,
    knowledge_id: int,
    scene_durations: list[float],
    allocation_seed: int = 0,
) -> dict[str, Any]:
    """Read-only readiness inspection for an authorized pool or legacy source."""
    if not _positive_int(knowledge_id):
        raise ValueError("knowledge_id deve ser um inteiro positivo.")
    repository = MediaKnowledgeRepository()
    payloads, identity = _resolve_media_pool(repository, knowledge_id)
    plan = build_media_pool_plan(
        knowledge_payloads=payloads,
        scene_durations=scene_durations,
        allocation_seed=allocation_seed,
    )
    return {**plan, **identity}


def select_production_media(
    *,
    content_item_id: int,
    knowledge_id: int,
) -> dict[str, Any]:
    """Materialize one ContentSegment per ProductionPlan scene from an immutable media pool."""
    if not _positive_int(content_item_id):
        raise ValueError("content_item_id deve ser um inteiro positivo.")
    if not _positive_int(knowledge_id):
        raise ValueError("knowledge_id deve ser um inteiro positivo.")

    production_record = get_production_plan_by_content_item_id(content_item_id)
    if production_record is None:
        raise RuntimeError(f"ProductionPlan não encontrado para content_item_id={content_item_id}.")
    production_plan = production_record.get("production_plan")
    if not isinstance(production_plan, dict):
        raise RuntimeError("Registro persistido não contém ProductionPlan válido.")
    if production_plan.get("content_item_id") != content_item_id:
        raise RuntimeError("ProductionPlan possui content_item_id incompatível.")

    script_id = production_plan.get("script_id")
    idea_id = production_plan.get("idea_id")
    objective = production_plan.get("objective")
    if not _positive_int(script_id):
        raise RuntimeError("ProductionPlan não possui script_id válido.")
    if not _positive_int(idea_id):
        raise RuntimeError("ProductionPlan não possui idea_id válido.")
    if not isinstance(objective, str) or not objective.strip():
        raise RuntimeError("ProductionPlan não possui objective válido.")

    scenes = production_plan.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        raise RuntimeError("ProductionPlan não possui cenas válidas.")
    scene_durations: list[float] = []
    for scene_index, scene in enumerate(scenes, start=1):
        if not isinstance(scene, dict):
            raise RuntimeError(f"Cena inválida na posição {scene_index}.")
        duration = scene.get("duration_seconds")
        if not isinstance(duration, (int, float)) or isinstance(duration, bool) or duration <= 0:
            raise RuntimeError(f"Cena {scene_index} possui duração inválida.")
        narration = scene.get("narration")
        if not isinstance(narration, str) or not narration.strip():
            raise RuntimeError(f"Cena {scene_index} não possui narração válida.")
        scene_durations.append(float(duration))

    content_item = get_content_item(content_item_id)
    if content_item is None:
        raise RuntimeError(f"ContentItem não encontrado: {content_item_id}.")
    title = content_item.get("title")
    if not isinstance(title, str) or not title.strip():
        raise RuntimeError("ContentItem não possui título válido.")

    repository = MediaKnowledgeRepository()
    payloads, pool_identity = _resolve_media_pool(repository, knowledge_id)
    plan = build_media_pool_plan(
        knowledge_payloads=payloads,
        scene_durations=scene_durations,
        allocation_seed=content_item_id,
    )
    segment_preflight = preflight_production_segment_plan(
        scene_durations=scene_durations,
        assignments=plan["assignments"],
    )

    segment_ids: list[int] = []
    content_unit_ids: list[int] = []
    selections: list[dict[str, Any]] = []

    for scene_index, (scene, assignment) in enumerate(zip(scenes, plan["assignments"]), start=1):
        duration = float(scene["duration_seconds"])
        narrative_block = scene.get("narrative_block")
        scene_title = (
            narrative_block.strip()
            if isinstance(narrative_block, str) and narrative_block.strip()
            else f"{title.strip()} — Cena {scene_index}"
        )
        source_knowledge_id = int(assignment["knowledge_id"])
        selection = select_media_segments(
            knowledge=payloads[source_knowledge_id],
            content_item_id=content_item_id,
            script_id=script_id,
            idea_id=idea_id,
            title=scene_title,
            objective=objective.strip(),
            hook=scene["narration"].strip(),
            narration=scene["narration"].strip(),
            media_format="landscape_16_9",
            target_duration_seconds=duration,
            max_segments=1,
            source_cursor_seconds=float(assignment["source_start_seconds"]),
            continuous_window=True,
        )
        segments = selection.get("segments")
        if not isinstance(segments, list) or len(segments) != 1:
            raise RuntimeError(f"Cena {scene_index} precisa produzir exatamente um ContentSegment.")
        segment = segments[0]
        segment_id = segment.get("id")
        segment_duration = segment.get("duration_seconds")
        if not _positive_int(segment_id):
            raise RuntimeError(f"Cena {scene_index} não produziu segment_id válido.")
        if (
            not isinstance(segment_duration, (int, float))
            or isinstance(segment_duration, bool)
            or abs(float(segment_duration) - duration) > _GAP_TOLERANCE_SECONDS
        ):
            raise RuntimeError(f"Cena {scene_index}: duração do segmento não corresponde à duração da cena.")
        content_unit = selection.get("content_unit")
        if not isinstance(content_unit, dict) or not _positive_int(content_unit.get("id")):
            raise RuntimeError(f"Cena {scene_index} não produziu ContentUnit válido.")

        segment_ids.append(int(segment_id))
        content_unit_ids.append(int(content_unit["id"]))
        selections.append(
            {
                "scene_order": scene.get("order", scene_index),
                "knowledge_id": source_knowledge_id,
                "content_unit_id": int(content_unit["id"]),
                "segment_id": int(segment_id),
                "duration_seconds": float(segment_duration),
                "source_start_seconds": float(assignment["source_start_seconds"]),
                "source_end_seconds": float(assignment["source_end_seconds"]),
                "asset_ref": selection.get("asset_ref"),
                "source_url": selection.get("source_url"),
            }
        )

    if len(segment_ids) != len(scenes):
        raise RuntimeError("A composição não produziu exatamente um segment_id por cena.")

    return {
        "content_item_id": content_item_id,
        "knowledge_id": knowledge_id,
        "pool_id": pool_identity["pool_id"],
        "knowledge_ids": pool_identity["knowledge_ids"],
        "used_knowledge_ids": plan["used_knowledge_ids"],
        "content_unit_ids": content_unit_ids,
        "segment_ids": segment_ids,
        "scene_count": len(scenes),
        "required_seconds": plan["required_seconds"],
        "available_seconds": plan["available_seconds"],
        "selections": selections,
        "segment_preflight": segment_preflight,
        "status": "selected",
    }
