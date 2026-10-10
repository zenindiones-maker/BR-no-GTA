#!/usr/bin/env python3
"""Real SHA-pinned FilmCraft built-in demo -> short MP4 in external offline sandbox."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from artcraft_film_effect_interop import FILM_SHA, BoundaryError, check_manifest, verify_binary, check_png


def run(args: list[str], timeout: int, logfile: Path) -> None:
    try:
        p = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           timeout=timeout, check=False,
                           env={"HOME": "/tmp", "XDG_CACHE_HOME": "/tmp", "TMPDIR": "/tmp",
                                "PATH": "/usr/bin:/bin", "LC_ALL": "C"})
    except subprocess.TimeoutExpired as exc:
        raise BoundaryError("NATIVE_FILM_EXPORT_TIMEOUT") from exc
    logfile.write_bytes((p.stdout + b"\n" + p.stderr)[-30000:])
    if p.returncode != 0:
        raise BoundaryError("NATIVE_FILM_EXPORT_NONZERO:" + str(p.returncode) +
                            ":" + p.stderr.decode(errors="replace")[-650:])


def main() -> int:
    parser = argparse.ArgumentParser()
    for k in ("manifest", "binary", "build-receipt", "out"):
        parser.add_argument("--" + k, type=Path, required=True)
    parser.add_argument("--with-audio", action="store_true")
    a = parser.parse_args()
    report = {"schema": "BRArtCraftFilmCraftRealVideoExport/v1", "gate": "FAIL",
              "native_executed": False, "production_approved": False,
              "harness_authority": "NONE", "source_sha": FILM_SHA,
              "audio_requested": a.with_audio}
    try:
        check_manifest(a.manifest)
        d = json.loads(a.build_receipt.read_text())
        if d.get("pinned_sha") != FILM_SHA or d.get("source_status") != "verified":
            raise BoundaryError("WRONG_FILMCRAFT_SOURCE")
        for gate in ("build_status", "tests_status", "cli_status", "cli_smoke_status"):
            if d.get(gate) != "success":
                raise BoundaryError("FILMCRAFT_BUILD_RECEIPT_FAILED:" + gate)
        rec = d.get("compiled_artifact", {})
        binary = verify_binary(a.binary, rec.get("sha256", ""))
        if binary.stat().st_size != rec.get("bytes"):
            raise BoundaryError("FILMCRAFT_EXECUTABLE_SIZE_CHANGED")
        if a.out.exists() and (not a.out.is_dir() or a.out.is_symlink() or any(a.out.iterdir())):
            raise BoundaryError("OUTPUT_DIRECTORY_NOT_EMPTY")
        a.out.mkdir(parents=True, exist_ok=True)
        video = a.out / "real-filmcraft-five-seconds.mp4"
        report["binary_sha256"] = rec["sha256"]
        report["native_executed"] = True
        cmd = [str(binary), "--demo", "export", str(video), "--format", "h264",
               "--start", "0", "--end", "5", "--scale", "0.2"]
        if not a.with_audio:
            cmd.append("--no-audio")
        report["command_contract"] = "FilmCraft exact --demo 5s H264 " + ("with audio" if a.with_audio else "video only")
        run(cmd,
            300, a.out / "native-export-cli.log")
        if video.is_symlink() or not video.is_file() or not 0 < video.stat().st_size < 65_000_000:
            raise BoundaryError("NATIVE_EXPORT_NOT_BOUNDED_MP4")
        from artcraft_film_effect_interop import sha256
        report["video"] = {"bytes": video.stat().st_size, "sha256": sha256(video)}
        pp = subprocess.run([
            "ffprobe", "-v", "error", "-count_frames", "-show_entries",
            "stream=codec_type,codec_name,width,height,pix_fmt,nb_read_frames,r_frame_rate,sample_rate,channels:format=duration",
            "-of", "json", str(video)],
            capture_output=True, timeout=40, check=False,
        )
        if pp.returncode or len(pp.stdout) > 50000:
            raise BoundaryError("FFPROBE_EXPORT_FAILED")
        probe = json.loads(pp.stdout)
        vids = [x for x in probe.get("streams", []) if x.get("codec_type") == "video"]
        if len(vids) != 1:
            raise BoundaryError("EXPORT_VIDEO_STREAM_MISSING")
        auds = [x for x in probe.get("streams", []) if x.get("codec_type") == "audio"]
        if a.with_audio:
            if len(auds) != 1 or auds[0].get("codec_name") != "aac":
                raise BoundaryError("EXPORT_AAC_AUDIO_STREAM_MISSING")
            if auds[0].get("sample_rate") != "48000" or int(auds[0].get("channels", 0)) != 2:
                raise BoundaryError("EXPORT_AUDIO_SAMPLE_RATE_OR_STEREO_INVALID")
        elif auds:
            raise BoundaryError("UNAUTHORIZED_AUDIO_TRACK_IN_VIDEO_ONLY_TEST")
        v = vids[0]
        if v.get("codec_name") != "h264":
            raise BoundaryError("EXPORT_H264_REQUIRED")
        if not 1 <= v.get("width", 0) <= 1920 or not 1 <= v.get("height", 0) <= 1080:
            raise BoundaryError("EXPORT_DIMENSIONS_INVALID")
        frames = int(v.get("nb_read_frames", 0))
        if not 110 <= frames <= 130:
            raise BoundaryError("EXPORT_FRAME_COUNT_OUT_OF_EXPECTED_RANGE:" + str(frames))
        dur = float(probe.get("format", {}).get("duration", -1))
        if not 4.8 <= dur <= 5.2:
            raise BoundaryError("EXPORT_DURATION_INVALID:" + str(dur))
        report["video"].update({"codec": "h264", "width": v["width"], "height": v["height"],
                                "pix_fmt": v.get("pix_fmt"), "frames": frames, "duration": dur})
        if auds:
            report["audio"] = {"codec": "aac", "sample_rate": 48000, "channels": 2}
        frame = a.out / "real-film-export-2s.png"
        cv = subprocess.run(["ffmpeg", "-hide_banner", "-v", "error", "-nostdin",
                             "-ss", "2", "-i", str(video), "-frames:v", "1", "-y", str(frame)],
                            capture_output=True, timeout=60, check=False)
        if cv.returncode:
            raise BoundaryError("EXPORT_FRAME_EXTRACTION_FAILED")
        info = check_png(frame)
        raw = subprocess.run(["ffmpeg", "-hide_banner", "-v", "error", "-nostdin",
                              "-i", str(frame), "-frames:v", "1", "-pix_fmt", "rgb24",
                              "-f", "rawvideo", "pipe:1"],
                             capture_output=True, timeout=35, check=False)
        if raw.returncode or len(raw.stdout) != info["width"] * info["height"] * 3:
            raise BoundaryError("EXPORTED_FRAME_DECODE_FAILED")
        stride = max(1, len(raw.stdout) // 2048)
        sample = raw.stdout[::stride]
        if max(sample) - min(sample) < 15 or len(set(sample)) < 12:
            raise BoundaryError("EXPORT_VISUAL_CONTENT_FLAT")
        report["frame_2s"] = {**info, "distinct_sample_values": len(set(sample))}
        report["gate"] = "PASS"
    except Exception as e:
        report["error"] = type(e).__name__ + ":" + str(e)[:900]
    finally:
        a.out.mkdir(parents=True, exist_ok=True)
        (a.out / "filmcraft-real-video-receipt.json").write_text(json.dumps(report, indent=2) + "\n")
        print("FILMCRAFT_REAL_MP4_EXPORT_GATE=" + report["gate"])
        print("NATIVE_EXECUTED=" + str(report["native_executed"]))
        print("OWNER_PUBLICATION_APPROVED=FALSE")
    return 0 if report["gate"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
