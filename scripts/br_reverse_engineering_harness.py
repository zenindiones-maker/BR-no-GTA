#!/usr/bin/env python3
"""Execute already-authorized reverse engineering through canonical Harness routing.

This CLI NEVER issues authority. A live persisted authorization ID must be
provided by DeepSeek Harness. No fallback, publication or autonomous looping.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.harness_capability_adapter import CapabilityAdapter
from app.services.harness_collaboration_service import TaskEnvelope
from app.services.harness_routing_policy_service import HarnessRoutingRequest, route_harness_request
from app.services.reverse_engineering_harness_service import MEDIA_CAPABILITY_ID, REA_CAPABILITY_ID, WEB_HAR_CAPABILITY_ID


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Harness-governed, read-only reverse engineering")
    parser.add_argument("--authorization-id", required=True, help="Existing persisted Harness authorization ID")
    parser.add_argument("--mode", required=True, choices=["media", "rea-js", "web-har"])
    parser.add_argument("--input", required=True, help="Existing local artifact within approved auth lineage root")
    parser.add_argument("--rights", choices=["owned", "licensed", "observation_only"], required=True)
    parser.add_argument("--transcript")
    parser.add_argument("--goal", help="Human-provided original creative experiment objective")
    parser.add_argument("--candidate", help="Original media candidate for differential analysis")
    parser.add_argument("--candidate-rights", choices=["owned", "licensed"], help="Original candidate rights declaration")
    parser.add_argument("--detect-scenes", action="store_true")
    parser.add_argument("--audio-dynamics", action="store_true", help="Run FFmpeg overall signal stats")
    parser.add_argument("--adaptive-shot-window", type=float, help="Opt in to 0-90s adaptive scene observation")
    parser.add_argument("--output", required=True, help="New private JSON result file")
    args = parser.parse_args(argv)

    source = Path(args.input).expanduser()
    target = Path(args.output).expanduser()
    if target.exists() or target.is_symlink() or not target.is_absolute() or not target.parent.is_dir():
        raise PermissionError("REVERSE_ENGINEERING_OUTPUT_PATH_NOT_FRESH")
    if args.mode in {"rea-js", "web-har"} and (args.transcript or args.detect_scenes or args.goal or args.candidate or args.audio_dynamics or args.adaptive_shot_window is not None):
        raise PermissionError("REA_JS_MEDIA_FLAGS_FORBIDDEN")
    capability_id = {"media": MEDIA_CAPABILITY_ID, "rea-js": REA_CAPABILITY_ID, "web-har": WEB_HAR_CAPABILITY_ID}[args.mode]
    domain = {"media": "audiovisual-analysis", "rea-js": "software-investigation", "web-har": "website-observation"}[args.mode]
    decision = route_harness_request(HarnessRoutingRequest(
        intent=f"read-only {domain} evidence",
        authorized_action="RESEARCH",
        required_capability_id=capability_id,
        domain=domain,
        fallback_allowed=False, provider_required=False,
        learning_required=False,
    ))
    payload = {"source_path": str(source), "rights": args.rights}
    if args.mode == "media":
        if args.transcript:
            payload["transcript_path"] = args.transcript
        if args.detect_scenes:
            payload["include_scene_cuts"] = True
        if args.audio_dynamics:
            payload["include_audio_dynamics"] = True
        if args.adaptive_shot_window is not None:
            payload["adaptive_shot_window_seconds"] = args.adaptive_shot_window
        if args.goal:
            payload["owner_goal"] = args.goal
        if args.candidate:
            payload["candidate_path"] = args.candidate
            payload["candidate_rights"] = args.candidate_rights
    result = CapabilityAdapter().execute(
        authorization=args.authorization_id,
        task_envelope=TaskEnvelope(
            task_id=f"rea-evidence-{os.getpid()}",
            capability_id=capability_id,
            action="RESEARCH",
            objective="Observe authorized source only",
            allowed_tools=("ffmpeg", "ffprobe") if args.mode == "media" else (("rea",) if args.mode == "rea-js" else ()),
            cost_budget=0.0,
            retry_budget=0,
        ),
        routing_decision=decision,
        payload=payload,
    )
    content = json.dumps(result.to_dict(), sort_keys=True, ensure_ascii=False, indent=2) + "\n"
    fd = os.open(str(target), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(content)
    print("BR_REVERSE_ENGINEERING_HARNESS_RESULT=MEASURED")
    print("BR_REVERSE_ENGINEERING_PUBLISHING=FORBIDDEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
