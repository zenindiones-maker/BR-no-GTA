from __future__ import annotations

import argparse
from pathlib import Path

from fastapi import HTTPException
from pydantic import BaseModel
import uvicorn

from vedit import api
from vedit.store import Store


class AgentRename(BaseModel):
    track_id: str
    name: str


PROJECT_PATH: Path | None = None
# Stable IDs are part of the reviewed visual fixture identity. The previous
# baseline candidates were captured with these exact IDs; making them explicit
# removes UUID noise without weakening pixel-exact regression checks.
QA_CLIP_IDS = {
    "desktop": ("c06931e57", "c673445d8"),
    "desktop-narrow": ("c3b662c49", "c1250a986"),
}


def build_store(project_path: Path, *, identity_profile: str = "desktop") -> Store:
    try:
        color_clip_id, title_clip_id = QA_CLIP_IDS[identity_profile]
    except KeyError as exc:
        raise ValueError("unknown Browser QA identity profile") from exc
    project_path.parent.mkdir(parents=True, exist_ok=True)
    store = Store.create(
        name="Browser QA Project",
        preset="1080p",
        path=str(project_path),
    )
    store.set_track("V1", name="Video principal")
    store.set_track("A1", name="Audio principal")
    blue = store.add_color(
        "#204060",
        track_id="V1",
        start=0.0,
        duration=4.0,
    )
    blue.id = color_clip_id
    store.set_clip(blue.id, name="QA Blue")
    overlay = store.add_track("video", name="Overlay QA")
    title = store.add_text(
        "Browser QA title",
        track_id=overlay.id,
        start=0.5,
        duration=2.5,
    )
    title.id = title_clip_id
    store.set_clip(title.id, name="QA Title")
    store.save()
    return store


def reset_store(*, identity_profile: str = "desktop") -> Store:
    assert PROJECT_PATH is not None
    store = build_store(PROJECT_PATH, identity_profile=identity_profile)
    api.attach(store)
    return store


@api.app.get("/__qa/ready")
def qa_ready():
    store = api.S.need()
    return {
        "status": "ready",
        "project": store.summary("full"),
        "single_store": api.S.store is store,
    }


@api.app.post("/__qa/reset")
def qa_reset(identity_profile: str = "desktop"):
    if identity_profile not in QA_CLIP_IDS:
        raise HTTPException(400, "unknown Browser QA identity profile")
    store = reset_store(identity_profile=identity_profile)
    return {
        "status": "reset",
        "project": store.summary("full"),
        "revision": api.S.revision(),
        "single_store": api.S.store is store,
    }


@api.app.post("/__qa/agent/rename")
def qa_agent_rename(body: AgentRename):
    if body.track_id not in {"V1", "V2", "A1"}:
        raise HTTPException(400, "track outside Browser QA fixture")
    name = body.name.strip()
    if not name or len(name) > 80:
        raise HTTPException(400, "invalid Browser QA track name")
    store = api.S.need()
    store.set_track(body.track_id, name=name)
    return {
        "project": store.summary("full"),
        "revision": api.S.revision(),
        "same_store": api.S.store is store,
    }


def main() -> None:
    global PROJECT_PATH
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8760)
    parser.add_argument(
        "--project",
        default="/tmp/vedit-browser-qa/project.json",
    )
    args = parser.parse_args()
    PROJECT_PATH = Path(args.project)
    reset_store()
    api.mount_frontend()
    uvicorn.run(
        api.app,
        host=args.host,
        port=args.port,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
