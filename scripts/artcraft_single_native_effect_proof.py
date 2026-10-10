#!/usr/bin/env python3
"""Real EffectCraft demo PNG from exact pinned binary in external no-network sandbox."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from artcraft_film_effect_interop import (
    EFFECT_SHA, BoundaryError, check_manifest, check_fixture_pack, check_png,
    run, verify_binary,
)


def main():
    ap = argparse.ArgumentParser()
    for arg in ("manifest", "fixtures", "binary", "build-receipt", "output"):
        ap.add_argument("--" + arg, type=Path, required=True)
    a = ap.parse_args()
    out = a.output
    evidence = {
        "schema": "BRArtCraftNativeEffectcraftPNG/v1",
        "upstream_commit": EFFECT_SHA,
        "harness_authority": "NONE", "production_approved": False,
        "native_executed": False, "gate": "FAIL",
    }
    try:
        check_manifest(a.manifest)
        br = json.loads(a.build_receipt.read_text(encoding="utf-8"))
        if br.get("pinned_sha") != EFFECT_SHA or br.get("source_status") != "verified":
            raise BoundaryError("BAD_PINNED_EFFECT_BUILD_SOURCE")
        for stage in ("build_status", "tests_status", "cli_status", "cli_smoke_status"):
            if br.get(stage) != "success":
                raise BoundaryError("EFFECT_BUILD_GATE_NOT_PASS:" + stage)
        artifact = br.get("compiled_artifact", {})
        if artifact.get("filename") != "effectcraft-cli" or artifact.get("debug_stripped") is not True:
            raise BoundaryError("EFFECT_BINARY_RECEIPT_INVALID")
        binary = verify_binary(a.binary, artifact.get("sha256", ""))
        if binary.stat().st_size != artifact.get("bytes"):
            raise BoundaryError("EFFECT_BINARY_SIZE_MISMATCH")
        evidence["binary_sha256"] = artifact["sha256"]
        evidence["synthetic_reference"] = check_fixture_pack(a.fixtures)
        if out.exists() and (out.is_symlink() or not out.is_dir() or any(out.iterdir())):
            raise BoundaryError("EFFECT_OUTPUT_NOT_EMPTY")
        out.mkdir(parents=True, exist_ok=True)
        frame = out / "real-effectcraft-frame.png"
        env = {
            "HOME": "/tmp", "XDG_CACHE_HOME": "/tmp", "TMPDIR": "/tmp",
            "PATH": "/usr/bin:/bin", "LC_ALL": "C", "CARGO_NET_OFFLINE": "true",
        }
        evidence["native_executed"] = True
        evidence["argv_contract"] = "effectcraft-cli render-frame --demo --frame 0 --max-side 320 --out PNG --json"
        evidence["execution"] = run([
            str(binary), "render-frame", "--demo", "--frame", "0",
            "--max-side", "320", "--out", str(frame), "--json",
        ], cwd=out, timeout=120, env=env)
        evidence["frame"] = check_png(frame)
        evidence["gate"] = "PASS"
    except Exception as exc:
        evidence["error"] = type(exc).__name__ + ":" + str(exc)[:300]
    finally:
        out.mkdir(parents=True, exist_ok=True)
        (out / "native-effectcraft-receipt.json").write_text(
            json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8",
        )
        print("EFFECTCRAFT_REAL_NATIVE_FRAME_GATE=" + evidence["gate"])
        print("EFFECTCRAFT_EXECUTED=" + str(evidence["native_executed"]))
        print("EFFECTCRAFT_PRODUCTION_ADMISSION=FORBIDDEN")
    return 0 if evidence["gate"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
