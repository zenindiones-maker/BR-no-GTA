# BR-no-GTA — Studio Reverse Engineering V6

Status: isolated research candidate; NOT promoted to canonical runtime.
Authority: DeepSeek Harness only. No second agent authority, memory writes, publication, Owner Voice model access, billing or network upload.

## Four executable specialist modes

| Mode | Actual observation | Not established |
|---|---|---|
| stems | FFmpeg stereo PCM, 1–8 s bounded, per-stem sample peak, RMS, stereo correlation, mono-compatibility proxy, and unity-sum clipping risk | Native REAPER mixing, stems separation, subjective mastering |
| motion | OpenCV Farnebäck flow on at most 48 downscaled 160×90 frames, median global-translation proxy and residual motion | True camera solving, 3D reconstruction or aesthetic quality |
| alignment | External PT-BR timed-word metadata checked against matching locally authorized audio SHA-256 and probed duration; token timing and lexicon agreement | Phonemes, actual pronunciation, voice identity, WhisperX inference or speaker authenticity |
| timeline | Original bounded storyboard compiled into real OpenTimelineIO Timeline, rational FPS and frame ranges; native JSON serialized then round-tripped | Imported editor project, playable video, source assets or export |

WhisperX is researched but not installed in the voice runtime by V6. Full model execution would require Portuguese model benchmarking, approved weights/cache, workload admission, and a separate private BR_OWNER_V1 security review. The word "vaicy siti" is a lexicon requirement, not acoustically proven by a matching text manifest.

OpenTimelineIO 0.18.1 is pinned in isolated CI, with its native JSON adapter only. Other export adapters and REAPER/Resolve editor import remain outside demonstrated coverage. No installation on the A15 Telegram/Termux control gateway.

## Harness permission contract

Capability: reverse-engineering.studio.forensics
Domain: studio-forensics
Action: RESEARCH
Executor: app.services.reverse_engineering_harness_service.execute_authorized_studio_observation

A persisted Harness authorization with lineage allowed_media_roots is mandatory. Paths are absolute and approved under those roots. Symlinks, revoked/fabricated authorization, private owner_voice paths, unknown mode/fields, excessive windows, unapproved rights and cross-scope inputs fail closed. Alignment requires TWO scoped paths: external JSON manifest and real source WAV/FLAC/etc. No private biometric reference, image frame, script dialogue, or audio sample is emitted in receipts.

Example:

    python scripts/br_studio_forensics_v6.py --mode stems \
      --authorization-id EXISTING_HARNESS_AUTH_ID --rights owned \
      --input /private/approved/stem-a.wav --input /private/approved/stem-b.wav \
      --window-seconds 2 --output /private/new-stems-receipt.json

The CLI does not create authority. Receipt output uses O_EXCL and permissions 0600.

## Technical foundations

- WhisperX PT support and limitations: https://github.com/m-bain/whisperX
- OpenTimelineIO 0.18.1, native format and separate adapters: https://github.com/AcademySoftwareFoundation/OpenTimelineIO/releases
- FFmpeg source filter reference: https://ffmpeg.org/ffmpeg-filters.html
- OpenCV Farnebäck flow: https://docs.opencv.org/4.x/d4/dee/tutorial_optical_flow.html

## Controlled learning

An authorized source is measured in V6; V5 can compare technical reconstruction fidelity for matching owned/licensed reference/candidate pairs; V4 can assess preregistered paired experiments. Neither V4, V5 nor V6 changes routing or canonical memory. An independently approved Harness Learning Plane action is required to persist learning and promote techniques.

BR_OWNER_V1 remains under its own Qwen 1.7B, immutable identity/pronunciation boundary and Telegram human approval. This research subsystem neither reads that private reference nor sends audition messages.

## Acceptance

V6 requires an exact-head green CI with focused adversarial tests and actual FFmpeg-generated audio/motion, native OTIO roundtrip, matching audio-backed external alignment manifest and all four Harness-authorized entrypoints. A representative owned/licensed 20–25 minute episode, offline PT-BR acoustic test, real REAPER session and independent security/human review remain separately required.

Synthetic CI proves bounded research functions work; it does NOT certify professional creative equivalence, any precise speaker identity or perfect cloning.
