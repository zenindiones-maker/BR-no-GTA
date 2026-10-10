"""Build a deterministic, non-executing edit decision list from approved shot coverage.

The manifest is a handoff to the authorized render executor, not permission to render.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from app.services.run001_script_to_screen_contract import verify_script_to_screen, ScreenContractError

def build_edit_decision_list(script: dict, plan: dict, assets: dict) -> dict:
    coverage = verify_script_to_screen(script, plan)
    if not isinstance(assets, dict):
        raise ScreenContractError("ASSET_CATALOG_REQUIRED")
    timeline = []
    for shot in sorted(plan["shots"], key=lambda s: (s["start_ms"], s["end_ms"])):
        asset = assets.get(shot["asset_id"])
        if not isinstance(asset, dict):
            raise ScreenContractError("MISSING_MATERIALIZED_ASSET")
        path = asset.get("path")
        digest = asset.get("sha256")
        if not isinstance(path, str) or not path or not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ScreenContractError("INVALID_ASSET_PROVENANCE")
        if asset.get("source_ref") != shot["source_ref"] or asset.get("rights_status") != "CLEARED":
            raise ScreenContractError("ASSET_SOURCE_OR_RIGHTS_MISMATCH")
        media = Path(path)
        if not media.is_file() or not media.stat().st_size:
            raise ScreenContractError("ASSET_NOT_ON_DISK")
        h = hashlib.sha256()
        with media.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                h.update(block)
        if h.hexdigest() != digest:
            raise ScreenContractError("ASSET_HASH_MISMATCH")
        media_kind = asset.get("media_kind", "image")
        if media_kind not in ("image", "video"):
            raise ScreenContractError("UNSUPPORTED_ASSET_KIND")
        if media_kind == "video" and (not isinstance(shot.get("source_in_ms"), int) or isinstance(shot.get("source_in_ms"), bool) or shot["source_in_ms"] < 0):
            raise ScreenContractError("SOURCE_IN_REQUIRED")
        timeline.append({
            "media_kind": media_kind,
            **({"source_in_ms": shot["source_in_ms"]} if media_kind == "video" else {}),
            "segment_id": shot["segment_id"],
            "asset_id": shot["asset_id"],
            "media_path": str(media.resolve()),
            "media_sha256": digest,
            "start_ms": shot["start_ms"],
            "end_ms": shot["end_ms"],
            "visual_purpose": shot["visual_purpose"],
            "evidence_ref": shot["evidence_ref"],
        })
    return {
        "schema": "BRScriptToScreenEDL/v1",
        "status": "READY_FOR_RENDERER_ADAPTATION",
        "coverage_sha256": coverage["input_sha256"],
        "shots": timeline,
        "render_authorized": False,
        "semantic_qa": "PENDING_RENDERED_FRAME_REVIEW",
        "upload_authorized": False,
    }
