# BR-no-GTA — Production Forensics / Launch Readiness V10

**Status: isolated implementation and CI evidence only, NOT production promotion.**
DeepSeek Harness retains sole authority. This patch does not generate/clone BR_OWNER_V1,
modify Telegram, publish to YouTube, mutate canonical memory or rewrite production
queues. The main runtime and existing work in other branches remain unchanged.

## What the existing production system already has

- Production plan, research, render and recovery workflows, human review and owner-voice services;
- render_artifact_validator.py checks existence, MP4 extension, video track and positive duration;
- a professional creative requirement of authentic Brazilian Portuguese narration and final human approval;
- V4–V9 independently test REA software investigation, Iris local visual capture and technical reconstruction fidelity.

Those components do not collectively certify that a real 20–25 minute video is ready to upload.
**The video validator's structural PASS is not a product-quality PASS.**

## V10 actual improvement

The capability production.technical-media-forensics is registered under the existing
Harness RESEARCH authority with allowed_media_roots. Strict output profile
br_no_gta_1080p_master demands a local owner-made MP4 with:

- exactly one H.264 video track, 1920×1080, 30 FPS nominal and average, yuv420p;
- exactly one stereo AAC audio track at 48 kHz;
- duration between 1200 and 1500 seconds without artificial padding;
- bounded FFmpeg decode and audio-volume samples at the beginning, middle and end;
- advisory blackdetect/freezedetect events; black screens or static animation
  can be intentional, so warnings are not automatic artistic failures;
- all selected windows silent triggers hard blocking, a single quiet production
  scene triggers manual inspection instead of an invalid blanket failure.

A separate synthetic_ci_canary profile validates 320×180, 30fps and 0.5–10s,
**never** as a real 20-minute production. It is intentionally impossible to
pass a canary as a production master.

All outputs contain file SHA-256, stream measurements, window positions,
failure codes and a digest of the receipt. A receipt SHA only proves internal
consistency, not independent authenticity. Only the inspected window(s) were
decoded; full-duration playback, long-form audio loudness, subtitles/overlays,
editorial truth, license provenance, color compliance, style continuity,
semantic timing and exact owner voice identity remain separate gates.

Every receipt explicitly says identity_verified=false, human_review_approved=false,
publish_authorized=false, memory_write=NOT_ATTEMPTED. The harness wrapper further
enforces production_ready=false and publication=FORBIDDEN.

## Real positive/negative tests

The CI uses a clean Ubuntu 24.04 runner with explicit FFmpeg install.
It encodes four original test conditions and runs the actual Harness
CapabilityAdapter with persisted RESEARCH permission:

1. A short owned animated MP4 with an audible sine tone must pass **only** the canary
   technical check;
2. a short MP4 with an AAC track containing silence must fail sampled audio;
3. a video-only MP4 must fail missing-audio detection;
4. the short technical canary tested as a production master must fail duration
   and resolution, even if validly encoded.

Each result feeds the V10 readiness board, which classifies a concrete next
experiment without starting a job, rerunning a failure blindly or promoting a
capability. Tests also cover unauthorized inputs, revoked authorization,
tampered receipts, forbidden publication claims and deliberate quiet scenes.

## Actual blockers before BR-no-GTA can start normal production deliveries

1. **BR_OWNER_V1 private audition**: the last inspected 2026-10-08 failed clone
   workflow run 37774437402 ended with exit 143, with no observed new
   CLONE_TELEGRAM_MESSAGE_ID in that run. An earlier successful test run
   of the contract does not approve the human clone. Voice must remain
   single-source and owner-reviewed, no substitute.
2. **Voice/scene temporal match**: audition must be approved first; then a
   separately authorized production sample must validate exact narration and
   pronunciation of “Vice City” → “vaicy siti”, speaker identity and
   fluency in the private review pipeline.
3. **A real editorial package**: fact/evidence map, 20–25 minute script,
   authentic visual assets, no debug overlays/burned captions, reviewed
   creative narrative and rights.
4. **Complete render**: a real 1920×1080 30fps 20–25 minute output,
   segment coverage, durable resume evidence and full-decode verification
   beyond V10's bounded windows.
5. **Human approval and private publishing**: separate authorized Telegram
   review and eventual PRIVATE HD YouTube upload; never infer final approval
   from technical format success.

### Production modes and milestones

- RESEARCH_ONLY: safe to develop the original editorial package and isolated
  technical canary; no public upload.
- PREPRODUCTION_CANDIDATE: owned footage and script evaluated, voice gate
  still pending.
- PRODUCTION_APPROVAL_REQUIRED: only after independently authenticated owner
  voice, full render/creative QA and owner review; V10 cannot set this state.
- PUBLICATION: forbidden to any V10 measurement or synthesized receipt alone.

## Source and measurement references

- FFprobe structured stream metadata, show_entries and JSON format:
  https://ffmpeg.org/ffprobe.html
- FFmpeg blackdetect, freezedetect, volumedetect and null-output decoding:
  https://ffmpeg.org/ffmpeg-filters.html
- VMAF full-reference comparison is optional and only relevant to matching,
  frame-aligned source/candidate visuals, never unrelated original animation:
  https://github.com/Netflix/vmaf/blob/master/resource/doc/ffmpeg.md
- Qwen3-TTS single-speaker fine-tuning benefits from a consistent owner
  reference; this is NOT evidence of voice identity approval:
  https://github.com/QwenLM/Qwen3-TTS/blob/main/finetuning/README.md

**Acceptance boundary:** CI success on synthetic material proves only
technical smoke checks. Production readiness requires a real original episode,
separate private owner-voice acceptance, independently reviewed provenance
and explicit human publication approval.
