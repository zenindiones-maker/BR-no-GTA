#!/usr/bin/env python3
"""Run exactly one SHA-pinned FilmCraft real frame under externally enforced Docker isolation."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from artcraft_film_effect_interop import (FILM_SHA, BoundaryError, check_manifest,
                                          check_fixture_pack, check_png, run, verify_binary)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--fixtures", type=Path, required=True)
    p.add_argument("--binary", type=Path, required=True)
    p.add_argument("--build-receipt", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    receipt = {
        "schema": "BRArtCraftSingleNativeFilmProof/v1",
        "upstream": "storytold/filmcraft", "expected_commit": FILM_SHA,
        "harness_authority": "NONE", "production_approved": False,
        "native_executed": False, "gate": "FAIL",
    }
    try:
        check_manifest(args.manifest)
        build = json.loads(args.build_receipt.read_text())
        if build.get("pinned_sha") != FILM_SHA or build.get("source_status") != "verified":
            raise BoundaryError("BUILD_SOURCE_IDENTITY_MISMATCH")
        for stage in ("build_status", "tests_status", "cli_status", "cli_smoke_status"):
            if build.get(stage) != "success":
                raise BoundaryError("BUILD_STAGE_MISSING_SUCCESS:" + stage)
        artifact = build.get("compiled_artifact", {})
        if artifact.get("filename") != "filmcraft-cli" or not artifact.get("debug_stripped", False):
            raise BoundaryError("COMPILED_ARTIFACT_PROVENANCE_INVALID")
        binary = verify_binary(args.binary, artifact.get("sha256", ""))
        if binary.stat().st_size != artifact.get("bytes"):
            raise BoundaryError("BINARY_SIZE_MISMATCH")
        receipt["binary_sha256"] = artifact["sha256"]
        receipt["reference_fixture"] = check_fixture_pack(args.fixtures)
        if receipt["reference_fixture"]["integrity"] != "PASS":
            raise BoundaryError("SYNTHETIC_FIXTURE_GATE_FAILED")
        if args.output.exists() and (args.output.is_symlink() or not args.output.is_dir()):
            raise BoundaryError("INVALID_OUTPUT_DIRECTORY")
        args.output.mkdir(parents=True, exist_ok=True)
        frame = args.output / "real-filmcraft-frame.png"
        if frame.exists():
            raise BoundaryError("PREEXISTING_OUTPUT_FORBIDDEN")
        import os
        env = {"HOME": "/tmp", "XDG_CACHE_HOME": "/tmp", "TMPDIR": "/tmp",
               "PATH": "/usr/bin:/bin", "LC_ALL": "C", "CARGO_NET_OFFLINE": "true"}
        receipt["native_executed"] = True
        receipt["command"] = "filmcraft-cli --demo render --seconds 2 --out [bounded-png] --scale 0.16"
        receipt["execution"] = run([
            str(binary), "--demo", "render", "--seconds", "2",
            "--out", str(frame), "--scale", "0.16"
        ], cwd=args.output, timeout=90, env=env)
        receipt["frame"] = check_png(frame)
        # At 0s the built-in demo begins with an intentional fade-to-black.
        # Decode an actual interior frame and reject flat/empty images; PNG
        # validity alone was a documented false-positive quality gate.
        import subprocess
        px = subprocess.run(
            ["ffmpeg", "-hide_banner", "-v", "error", "-nostdin",
             "-i", str(frame), "-frames:v", "1", "-pix_fmt", "rgb24",
             "-f", "rawvideo", "pipe:1"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=25, check=False,
        )
        if px.returncode or len(px.stdout) != receipt["frame"]["width"] * receipt["frame"]["height"] * 3:
            raise BoundaryError("REAL_FRAME_DECODE_FAILED")
        sample = px.stdout[::max(1, len(px.stdout) // 2048)]
        dynamic = max(sample) - min(sample)
        if dynamic < 15 or len(set(sample)) < 12:
            raise BoundaryError("RENDERED_FRAME_IS_VISUALLY_EMPTY_OR_FLAT")
        receipt["frame"]["sample_luma_channel_span"] = dynamic
        receipt["frame"]["sample_distinct_channel_values"] = len(set(sample))
        receipt["gate"] = "PASS"
    except Exception as exc:
        receipt["error"] = f"{type(exc).__name__}:{str(exc)[:350]}"
    finally:
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / "native-filmcraft-receipt.json").write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n")
        print("BR_FILMCRAFT_REAL_NATIVE_FRAME_GATE=" + receipt["gate"])
        print("ARTCRAFT_REAL_CLI_EXECUTED=" + str(receipt["native_executed"]))
        print("ARTCRAFT_PRODUCTION_PROMOTION=FORBIDDEN")
    return 0 if receipt["gate"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
