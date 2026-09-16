import pytest

from app.services.media_selection_service import MediaSelectionError
from app.services.production_media_selection_service import build_media_pool_plan


def _knowledge(source: str, ranges: list[tuple[float, float]]):
    return {
        "source_path": source,
        "scenes": [
            {
                "index": index,
                "start_seconds": start,
                "end_seconds": end,
                "duration_seconds": end - start,
                "detection_method": "test",
            }
            for index, (start, end) in enumerate(ranges)
        ],
        "metadata": {},
    }


def test_pool_combines_multiple_sources_without_reuse():
    plan = build_media_pool_plan(
        knowledge_payloads={
            1: _knowledge("remote://media-worker/a", [(0.0, 900.0)]),
            2: _knowledge("remote://media-worker/b", [(0.0, 600.0)]),
        },
        scene_durations=[30.0] * 50,
        allocation_seed=4,
    )

    assert plan["status"] == "ready"
    assert plan["required_seconds"] == 1500.0
    assert plan["available_seconds"] == 1500.0
    assert set(plan["used_knowledge_ids"]) == {1, 2}
    assert len(plan["assignments"]) == 50

    intervals: dict[int, list[tuple[float, float]]] = {}
    for assignment in plan["assignments"]:
        intervals.setdefault(assignment["knowledge_id"], []).append(
            (assignment["source_start_seconds"], assignment["source_end_seconds"])
        )
    for source_intervals in intervals.values():
        ordered = sorted(source_intervals)
        for previous, current in zip(ordered, ordered[1:]):
            assert previous[1] <= current[0] + 0.001


def test_pool_rejects_insufficient_aggregate_coverage_before_persistence():
    with pytest.raises(MediaSelectionError, match="nenhum ContentSegment foi criado"):
        build_media_pool_plan(
            knowledge_payloads={
                1: _knowledge("remote://media-worker/a", [(0.0, 899.0)]),
                2: _knowledge("remote://media-worker/b", [(0.0, 600.0)]),
            },
            scene_durations=[30.0] * 50,
        )


def test_pool_rejects_fragmentation_even_when_total_seconds_are_enough():
    with pytest.raises(MediaSelectionError, match="fragmentado"):
        build_media_pool_plan(
            knowledge_payloads={
                1: _knowledge(
                    "remote://media-worker/a",
                    [(0.0, 20.0), (30.0, 50.0)],
                )
            },
            scene_durations=[30.0],
        )


def test_pool_seed_changes_equal_capacity_tie_breaking_for_ab_isolation():
    payloads = {
        1: _knowledge("remote://media-worker/a", [(0.0, 60.0)]),
        2: _knowledge("remote://media-worker/b", [(0.0, 60.0)]),
    }
    a = build_media_pool_plan(
        knowledge_payloads=payloads,
        scene_durations=[30.0],
        allocation_seed=0,
    )
    b = build_media_pool_plan(
        knowledge_payloads=payloads,
        scene_durations=[30.0],
        allocation_seed=1,
    )
    assert a["assignments"][0]["knowledge_id"] != b["assignments"][0]["knowledge_id"]
