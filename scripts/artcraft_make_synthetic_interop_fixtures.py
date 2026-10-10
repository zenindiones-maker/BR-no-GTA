#!/usr/bin/env python3
"""Synthetic-only FilmCraft/EffectCraft interoperability QA inputs."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import struct
import subprocess
import sys
import wave
import zlib


def png_chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack('>I', len(data)) + tag + data + struct.pack('>I', zlib.crc32(tag + data))


def write_png(path: Path, index: int, alpha: bool = False) -> None:
    w, h = 320, 180
    rows = []
    for y in range(h):
        row = bytearray(b'\x00')
        for x in range(w):
            r, g, b = (x + index * 25) % 256, (2 * y + index * 15) % 256, (x + y + index * 11) % 256
            if alpha:
                row.extend((r, g, b, x * 255 // (w - 1)))
            else:
                row.extend((r, g, b))
        rows.append(bytes(row))
    raw = b''.join(rows)
    header = b'\x89PNG\r\n\x1a\n'
    ihdr = struct.pack('>IIBBBBB', w, h, 8, 6 if alpha else 2, 0, 0, 0)
    path.write_bytes(header + png_chunk(b'IHDR', ihdr) + png_chunk(b'IDAT', zlib.compress(raw, 6)) + png_chunk(b'IEND', b''))


def generate(dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for i in range(5):
        write_png(dest / f'frame_{i:02}.png', i)
    write_png(dest / 'alpha_layer.png', 5, True)
    (dest / 'frames.ffconcat').write_text(
        'ffconcat version 1.0\n' +
        ''.join(f'file frame_{i:02}.png\nduration 0.033333333\n' for i in range(5))
    )
    with wave.open(str(dest / 'reference_audio_48k_stereo.wav'), 'wb') as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(48000)
        wav.writeframes(b''.join(struct.pack(
            '<hh',
            int(9000 * math.sin(2 * math.pi * 440 * i / 48000)),
            int(9000 * math.sin(2 * math.pi * 880 * i / 48000))
        ) for i in range(48000)))
    cmd = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin', '-y',
           '-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=30:duration=5',
           '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=5',
           '-map', '0:v', '-map', '1:a', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
           '-r', '30', '-frames:v', '150', '-c:a', 'aac', '-ar', '48000',
           '-ac', '2', '-t', '5', '-movflags', '+faststart',
           str(dest / 'reference_5s_320x180_30fps.mp4')]
    result = subprocess.run(cmd, capture_output=True, timeout=45, check=False)
    if result.returncode:
        raise RuntimeError('FFMPEG_SYNTHETIC_FIXTURE_FAILED:' + result.stderr[-700:].decode(errors='replace'))
    files = sorted(p for p in dest.iterdir() if p.is_file() and p.name != 'MANIFEST.json')
    manifest = {
        'schema': 'BRArtCraftInteroperabilityFixtures/v1',
        'purpose': 'Synthetic only; no owner voice/footage and no production approval',
        'files': [{'name': p.name, 'bytes': p.stat().st_size,
                   'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in files],
    }
    assert len(files) == 9, len(files)
    (dest / 'MANIFEST.json').write_text(json.dumps(manifest, sort_keys=True, indent=2) + '\n')
    print('ARTCRAFT_SYNTHETIC_FIXTURES=CREATED files=9')


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('usage: artcraft_make_synthetic_interop_fixtures.py DIRECTORY')
    generate(Path(sys.argv[1]))
