#!/usr/bin/env bash
set -euo pipefail

OUT_DIR="${1:-/tmp/br-media-smoke}"
mkdir -p "$OUT_DIR"
rm -f "$OUT_DIR"/fast-preview.mp4 "$OUT_DIR"/master-final.mp4 "$OUT_DIR"/preview.json "$OUT_DIR"/master.json

for cmd in ffmpeg ffprobe python3; do
  command -v "$cmd" >/dev/null 2>&1 || {
    echo "BR_MEDIA_SMOKE=BLOCKED_MISSING_$cmd"
    exit 20
  }
done

ENCODERS="$(ffmpeg -hide_banner -encoders 2>/dev/null)"
grep -qE '[[:space:]]libx264[[:space:]]' <<<"$ENCODERS" || {
  echo "FFMPEG_H264_ENCODER=FAIL"
  exit 21
}
grep -qE '[[:space:]]aac[[:space:]]' <<<"$ENCODERS" || {
  echo "FFMPEG_AAC_ENCODER=FAIL"
  exit 22
}

PREVIEW_START="$(date +%s%3N)"
ffmpeg -hide_banner -loglevel error   -f lavfi -i testsrc2=size=1280x720:rate=30   -f lavfi -i sine=frequency=880:sample_rate=48000   -t 1   -threads 2   -c:v libx264 -preset ultrafast -crf 28 -profile:v main -pix_fmt yuv420p   -c:a aac -b:a 96k   -movflags +faststart   -y "$OUT_DIR/fast-preview.mp4"
PREVIEW_END="$(date +%s%3N)"

MASTER_START="$(date +%s%3N)"
ffmpeg -hide_banner -loglevel error   -f lavfi -i testsrc2=size=1920x1080:rate=30   -f lavfi -i sine=frequency=1000:sample_rate=48000   -t 1   -threads 2   -c:v libx264 -preset veryfast -crf 18 -profile:v high -pix_fmt yuv420p   -c:a aac -b:a 192k   -movflags +faststart   -y "$OUT_DIR/master-final.mp4"
MASTER_END="$(date +%s%3N)"

ffprobe -v error   -show_entries stream=codec_type,codec_name,width,height,pix_fmt,r_frame_rate,profile   -of json "$OUT_DIR/fast-preview.mp4" >"$OUT_DIR/preview.json"

ffprobe -v error   -show_entries stream=codec_type,codec_name,width,height,pix_fmt,r_frame_rate,profile   -of json "$OUT_DIR/master-final.mp4" >"$OUT_DIR/master.json"

python3 - "$OUT_DIR/preview.json" "$OUT_DIR/master.json" <<'PY'
import json
import sys

def streams(path):
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    video = next(s for s in data["streams"] if s["codec_type"] == "video")
    audio = next(s for s in data["streams"] if s["codec_type"] == "audio")
    return video, audio

pv, pa = streams(sys.argv[1])
mv, ma = streams(sys.argv[2])

assert pv["codec_name"] == "h264"
assert pv["width"] == 1280 and pv["height"] == 720
assert pv["pix_fmt"] == "yuv420p"
assert pv["r_frame_rate"] == "30/1"
assert pa["codec_name"] == "aac"

assert mv["codec_name"] == "h264"
assert mv["width"] == 1920 and mv["height"] == 1080
assert mv["pix_fmt"] == "yuv420p"
assert mv["r_frame_rate"] == "30/1"
assert mv["profile"] == "High"
assert ma["codec_name"] == "aac"
PY

PREVIEW_MS="$((PREVIEW_END - PREVIEW_START))"
MASTER_MS="$((MASTER_END - MASTER_START))"
PREVIEW_SIZE="$(stat -c '%s' "$OUT_DIR/fast-preview.mp4")"
MASTER_SIZE="$(stat -c '%s' "$OUT_DIR/master-final.mp4")"

echo "FAST_PREVIEW=PASS"
echo "FAST_PREVIEW_TARGET=1280x720_30_H264_MAIN_AAC"
echo "FAST_PREVIEW_ELAPSED_MS=$PREVIEW_MS"
echo "FAST_PREVIEW_SIZE_BYTES=$PREVIEW_SIZE"
echo "MASTER_FINAL_CODEC_SMOKE=PASS"
echo "MASTER_FINAL_TARGET=1920x1080_30_H264_HIGH_YUV420P_AAC"
echo "MASTER_FINAL_ELAPSED_MS=$MASTER_MS"
echo "MASTER_FINAL_SIZE_BYTES=$MASTER_SIZE"
echo "FFMPEG_THREADS=2"
echo "PAID_FALLBACK=FALSE"
