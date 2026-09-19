from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "video-engine" / "backend"))

from vedit.graph import CompileOptions, compile_project
from vedit.model import Clip, Project, Settings, TextStyle, Track


def _late_text_project() -> Project:
    project = Project(settings=Settings(width=320, height=180, fps=10.0))
    project.tracks = [
        Track(
            kind="video",
            name="captions",
            clips=[
                Clip(
                    id="late-caption",
                    type="text",
                    start=10.0,
                    duration=2.0,
                    text=TextStyle(text="BR no GTA 6"),
                )
            ],
        )
    ]
    return project


def test_timestamp_placement_eliminates_prestart_tpad_without_changing_overlay_window():
    project = _late_text_project()
    legacy = compile_project(
        project,
        CompileOptions(audio=False, timeline_placement="legacy_tpad"),
    )
    optimized = compile_project(
        project,
        CompileOptions(audio=False, timeline_placement="timestamp"),
    )

    assert "tpad=start_duration=10:start_mode=add" in legacy.filtergraph
    assert "tpad=start_duration=10:start_mode=add" not in optimized.filtergraph
    assert "setpts=PTS-STARTPTS+10/TB" in optimized.filtergraph
    assert "between(t,10,12)" in legacy.filtergraph
    assert "between(t,10,12)" in optimized.filtergraph


def test_unknown_timeline_placement_fails_closed():
    project = _late_text_project()
    try:
        compile_project(
            project,
            CompileOptions(audio=False, timeline_placement="unknown"),
        )
    except ValueError as exc:
        assert "unsupported timeline placement" in str(exc)
    else:
        raise AssertionError("unknown timeline placement must fail closed")
