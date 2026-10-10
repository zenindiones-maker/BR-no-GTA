#!/usr/bin/env python3
"""Fail-closed isolated FilmCraft + EffectCraft headless CLI interoperability study.

Neither MCP nor scripting is exposed. Native CLIs must be run in an external,
credential-free, no-network sandbox. This provides no Harness authority.
"""
from __future__ import annotations

import argparse
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import time
from typing import Any

FILM_SHA = '7b6c134472287db4367fca80bcb498240ba36567'
EFFECT_SHA = '30aaddf7c23329dcdfc72a5bf65b55747bbd6be1'
TICKS_PER_SECOND = 254_016_000_000
SCHEMA = 'BRArtCraftFilmEffectInterop/v1'
ALLOWED = {'filmcraft': FILM_SHA, 'effectcraft': EFFECT_SHA}
MAX_OUTPUT = 24_000_000


class BoundaryError(ValueError):
    """A validity or trust boundary was violated."""


def ticks_for_frame(frame: int, fps_num: int = 30, fps_den: int = 1) -> int:
    if not isinstance(frame, int) or isinstance(frame, bool) or frame < 0:
        raise BoundaryError('INVALID_FRAME_INDEX')
    if fps_num <= 0 or fps_den <= 0 or fps_num > 240_000 or fps_den > 10_000:
        raise BoundaryError('INVALID_FRAME_RATE')
    ticks = Fraction(frame * fps_den * TICKS_PER_SECOND, fps_num)
    if ticks.denominator != 1:
        raise BoundaryError('FRAME_NOT_IN_EXACT_TICK_GRID')
    return int(ticks)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(65536), b''):
            h.update(block)
    return h.hexdigest()


def check_manifest(path: Path) -> dict:
    doc = json.loads(path.read_text(encoding='utf-8'))
    if doc.get('schema') != 'BRArtCraftPinnedSourceStudy/v1':
        raise BoundaryError('MANIFEST_SCHEMA_INVALID')
    entries = doc.get('projects')
    if not isinstance(entries, list) or len(entries) != 7:
        raise BoundaryError('MANIFEST_NOT_SEVEN')
    lookup = {e['name']: e for e in entries}
    if len(lookup) != 7:
        raise BoundaryError('MANIFEST_DUPLICATE_PROJECT')
    for name, sha in ALLOWED.items():
        e = lookup.get(name)
        if e is None or e.get('commit_sha') != sha or e.get('repository') != 'storytold/' + name:
            raise BoundaryError('PINNED_SOURCE_MISMATCH_' + name.upper())
    return doc


def safe_fixture(path: Path, base: Path, *, max_bytes: int = MAX_OUTPUT) -> Path:
    if path.is_symlink() or not path.is_file():
        raise BoundaryError('FIXTURE_NOT_REGULAR_FILE')
    base = base.resolve(strict=True)
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(base):
        raise BoundaryError('FIXTURE_PATH_ESCAPES_ROOT')
    if path.stat().st_size > max_bytes or path.stat().st_size == 0:
        raise BoundaryError('FIXTURE_SIZE_OUT_OF_BOUNDS')
    return resolved


def run(args: list[str], *, cwd: Path, timeout: int, env: dict[str, str] | None = None) -> dict[str, Any]:
    if timeout <= 0 or timeout > 120:
        raise BoundaryError('INVALID_TIMEOUT')
    start = time.monotonic()
    try:
        p = subprocess.run(args, cwd=cwd, env=env, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise BoundaryError('CHILD_PROCESS_TIMEOUT') from exc
    if p.returncode != 0:
        raise BoundaryError('CHILD_PROCESS_EXIT_NONZERO:' + str(p.returncode))
    return {'exit': p.returncode, 'duration_s': round(time.monotonic() - start, 3),
            'stdout_bytes': len(p.stdout), 'stderr_bytes': len(p.stderr)}


def probe_media(path: Path) -> dict[str, Any]:
    if shutil.which('ffprobe') is None:
        raise BoundaryError('FFPROBE_NOT_AVAILABLE')
    p = subprocess.run(['ffprobe', '-v', 'error', '-count_frames',
                        '-show_entries', 'stream=codec_name,codec_type,width,height,pix_fmt,r_frame_rate,sample_rate,channels,nb_read_frames:format=duration',
                        '-of', 'json', str(path)], stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, timeout=30, check=False)
    if p.returncode != 0 or len(p.stdout) > 150_000:
        raise BoundaryError('MEDIA_PROBE_FAILED')
    data = json.loads(p.stdout)
    streams = data.get('streams', [])
    if len(streams) != 2:
        raise BoundaryError('REFERENCE_STREAM_COUNT_UNEXPECTED')
    video = next((x for x in streams if x.get('codec_type') == 'video'), None)
    audio = next((x for x in streams if x.get('codec_type') == 'audio'), None)
    if video is None or audio is None:
        raise BoundaryError('REFERENCE_AV_STREAM_MISSING')
    required_video = {'codec_name': 'h264', 'pix_fmt': 'yuv420p', 'width': 320,
                      'height': 180, 'r_frame_rate': '30/1'}
    if any(video.get(key) != val for key, val in required_video.items()):
        raise BoundaryError('REFERENCE_VIDEO_PROFILE_MISMATCH')
    if video.get('nb_read_frames') != '150':
        raise BoundaryError('REFERENCE_FRAME_COUNT_MISMATCH')
    if audio.get('codec_name') != 'aac' or audio.get('sample_rate') != '48000' or audio.get('channels') != 2:
        raise BoundaryError('REFERENCE_AUDIO_PROFILE_MISMATCH')
    duration = float(data.get('format', {}).get('duration', '-1'))
    if not 4.99 <= duration <= 5.01:
        raise BoundaryError('REFERENCE_DURATION_MISMATCH')
    return {'video': {k: video[k] for k in required_video},
            'frames': 150, 'audio': {'codec': 'aac', 'sample_rate': 48000, 'channels': 2},
            'duration_s': duration, 'ticks_per_second': TICKS_PER_SECOND,
            'last_frame_tick': ticks_for_frame(149)}


def check_png(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise BoundaryError('RENDER_NOT_REGULAR_PNG')
    n = path.stat().st_size
    if n < 45 or n > MAX_OUTPUT:
        raise BoundaryError('RENDER_PNG_SIZE_INVALID')
    with path.open('rb') as f:
        header = f.read(33)
    if header[:8] != b'\x89PNG\r\n\x1a\n' or header[12:16] != b'IHDR':
        raise BoundaryError('RENDER_NOT_PNG')
    width, height = struct.unpack('>II', header[16:24])
    if width < 1 or height < 1 or width > 3840 or height > 2160:
        raise BoundaryError('RENDER_DIMENSIONS_UNSAFE')
    return {'width': width, 'height': height, 'bytes': n, 'sha256': sha256(path)}


def verify_binary(binary: Path, expected_hash: str) -> Path:
    if not re.fullmatch(r'[0-9a-f]{64}', expected_hash):
        raise BoundaryError('INVALID_BINARY_DIGEST')
    if binary.is_symlink() or not binary.is_file():
        raise BoundaryError('BINARY_NOT_REGULAR_FILE')
    if not os.access(binary, os.X_OK):
        raise BoundaryError('BINARY_NOT_EXECUTABLE')
    if sha256(binary) != expected_hash:
        raise BoundaryError('BINARY_DIGEST_MISMATCH')
    return binary.resolve(strict=True)


def check_fixture_pack(directory: Path) -> dict:
    manifest = directory / 'MANIFEST.json'
    safe_fixture(manifest, directory)
    meta = json.loads(manifest.read_text(encoding='utf-8'))
    if meta.get('schema') != 'BRArtCraftInteroperabilityFixtures/v1':
        raise BoundaryError('FIXTURE_MANIFEST_INVALID')
    entries = meta.get('files', [])
    if not isinstance(entries, list) or len(entries) != 9:
        raise BoundaryError('FIXTURE_FILES_INCOMPLETE')
    for e in entries:
        name = e.get('name', '')
        if not re.fullmatch(r'[a-zA-Z0-9_.-]+', name):
            raise BoundaryError('FIXTURE_UNSAFE_FILENAME')
        file = safe_fixture(directory / name, directory)
        if sha256(file) != e.get('sha256') or file.stat().st_size != e.get('bytes'):
            raise BoundaryError('FIXTURE_HASH_MISMATCH_' + name)
    profile = probe_media(directory / 'reference_5s_320x180_30fps.mp4')
    pngs = [check_png(directory / f'frame_{i:02}.png') for i in range(5)]
    if any(p['width'] != 320 or p['height'] != 180 for p in pngs):
        raise BoundaryError('FIXTURE_FRAME_DIMENSIONS_INVALID')
    return {'integrity': 'PASS', 'files': len(entries), 'profile': profile}


def cli_frame_probes(film: Path, effect: Path, film_digest: str, effect_digest: str, work: Path) -> dict:
    """Native execution is opt-in and MUST happen in an external no-network sandbox."""
    f = verify_binary(film, film_digest)
    e = verify_binary(effect, effect_digest)
    work.mkdir(mode=0o700, parents=True, exist_ok=True)
    if any(work.iterdir()):
        raise BoundaryError('OUTPUT_DIRECTORY_NOT_EMPTY')
    with tempfile.TemporaryDirectory(prefix='artcraft-probe-', dir=work) as td:
        tmp = Path(td)
        out_f = tmp / 'film-frame.png'
        out_e = tmp / 'effect-frame.png'
        env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'),
               'HOME': td, 'XDG_CACHE_HOME': td, 'CARGO_NET_OFFLINE': 'true'}
        film_run = run([str(f), '--demo', 'render', '--seconds', '0',
                        '--out', str(out_f), '--scale', '0.16'], cwd=tmp, env=env, timeout=60)
        effect_run = run([str(e), 'render-frame', '--demo', '--frame', '0',
                          '--max-side', '320', '--out', str(out_e), '--json'], cwd=tmp, env=env, timeout=60)
        return {'native_execution': 'PASS', 'filmcraft': {**film_run, 'frame': check_png(out_f)},
                'effectcraft': {**effect_run, 'frame': check_png(out_e)},
                'warning': 'Separate demo frames; pixel-equivalence not asserted; not production video approval'}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--manifest', type=Path, required=True)
    ap.add_argument('--fixtures', type=Path, required=True)
    ap.add_argument('--receipt', type=Path, required=True)
    ap.add_argument('--native', action='store_true')
    ap.add_argument('--filmcraft-bin', type=Path)
    ap.add_argument('--effectcraft-bin', type=Path)
    ap.add_argument('--film-sha256')
    ap.add_argument('--effect-sha256')
    ap.add_argument('--sandbox-work', type=Path)
    args = ap.parse_args(argv)
    receipt: dict[str, Any] = {'schema': SCHEMA, 'scope': 'isolated_research_only',
                               'harness_authority': 'NONE', 'production_approved': False,
                               'native_executed': False, 'gpu_verified': False}
    try:
        check_manifest(args.manifest)
        receipt['pins'] = dict(ALLOWED)
        receipt['synthetic_fixture'] = check_fixture_pack(args.fixtures)
        receipt['reference_baseline'] = 'PASS'
        if args.native:
            if not all([args.filmcraft_bin, args.effectcraft_bin, args.film_sha256,
                        args.effect_sha256, args.sandbox_work]):
                raise BoundaryError('NATIVE_BINARY_AND_DIGEST_REQUIRED')
            if os.environ.get('ARTCRAFT_EXTERNAL_NETWORK_SANDBOX') != 'CONFIRMED':
                raise BoundaryError('EXTERNAL_SANDBOX_REQUIRED')
            receipt['native'] = cli_frame_probes(args.filmcraft_bin, args.effectcraft_bin,
                                                 args.film_sha256, args.effect_sha256, args.sandbox_work)
            receipt['native_executed'] = True
        else:
            receipt['native'] = {'status': 'NOT_EXECUTED', 'reason': 'Pinned CLIs not yet available'}
        receipt['gate'] = 'PASS' if args.native else 'BASELINE_ONLY'
    except (BoundaryError, OSError, KeyError, ValueError, subprocess.TimeoutExpired) as exc:
        receipt['gate'] = 'FAIL'
        receipt['error'] = str(exc)[:150]
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print('BR_ARTCRAFT_INTEROP_GATE=' + receipt['gate'])
    print('RECEIPT=' + str(args.receipt))
    return 1 if receipt['gate'] == 'FAIL' else 0


if __name__ == '__main__':
    raise SystemExit(main())
