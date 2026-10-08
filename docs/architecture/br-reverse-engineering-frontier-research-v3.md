# BR-no-GTA — Research and evidence-first reverse engineering V3 (2026-10-08)

**Status**: development candidate. NOT promoted to canonical, owner voice or production.
**Authority**: DeepSeek Harness only. REA, FFmpeg, PySceneDetect, Playwright, model runners and specialist agents have authority=NONE and no direct memory, publication or policy rights.
**Business requirements**: produce original PT-BR material for 20–25 minute episodes with human approval, no padding, no automatic publication, no paid provider fallback, no unapproved voice identity. Preserve BR_OWNER_V1 / "Vice City" spoken as "vaicy siti".
**Central distinction**: reverse engineering a *technique* from permitted reference evidence is not copying another creator's expressive materials. Never bypass DRM or controls, impersonate speakers, or retain protected private assets in GitHub.

## What is genuinely running in this development candidate

1. **REA 6.0.0**: pinned source submodule plus exact package, and Harness-routed static JavaScript inspection. It is not a native provider install and does not authorize dynamic target execution.
2. **Media forensic evidence**: FFmpeg stream metadata, timing/subtitle metrics, LUFS/true peak/LRA, silence, black/freeze frames, optional FFmpeg cut candidates and original-vs-candidate deltas. These are measurements, not aesthetic PASS scores.
3. **V3 audio**: opt-in FFmpeg astats measurements of source sample peak dBFS, RMS dBFS, DC offset and derived crest ratio/dB. Sample peak is **not** true peak, and derived crest is labelled with its formula. No normalization or actual mix is performed.
4. **V3 video**: optional PySceneDetect 0.7.1 adaptive or content detector with a max **90s window** per invocation, source hash and explicit coverage. A few windows are not claimed to cover an entire 20–25 minute episode.
5. **V3 web**: offline HAR 1.2 request/method/status/MIME/time aggregates, with secrets, hosts, URLs, paths, bodies and cookies removed from receipts. It opens no browser and issues no network calls.
6. **Harness**: persisted task authorization and read-path scope, exact registry binding and routing, zero write scope, no autonomous tool registration or cron; only original experiment proposals with human quality gate.

## Research-driven capability matrix

| Discipline | Best next OSS building block | Evidence / acceptance criteria | Readiness and concern |
|---|---|---|---|
| Script & factual reporting | primary-source claim graph, editorial novelty tests | Each factual claim mapped to primary timestamp/URL + human verification, false attribution rate | Current structure/timing only; **no semantic fact verifier** |
| Narrative style & pacing | subtitle alignment + meaningful sections | 12-bin dialogue timing, turn lengths, hook timing, human comprehension and coherence scores | Current timing evidence real; semantic intent not measured |
| PT-BR voice | WhisperX word alignment, open ASR and Portuguese pronunciation lexicon | timestamp error, intelligibility, human MOS, unique authorized voice identity | **private BR_OWNER_V1 only**, needs separate identity-bound sandbox; never allow generic agents to retrieve biometric references |
| Speaker diarization | pyannote Community-1 | diarization error rate on permitted multi-speaker test, verified access/license/model cache | Gated external model agreement and HF identity; do not silently enable telemetry or premium model |
| Mix/master | FFmpeg loudnorm + astats; later pyloudnorm/REAPER stem-specific metering | input LUFS/dBTP/LRA, RMS, clipping/phase, stems, human musical and speech clarity review | V3 covers measurements only; -23 LUFS broadcast target is **not** a YouTube default |
| Music and beats | librosa audio features; model-stem separation only with approved model weights | onset deviation, tempo confidence, spectral range and phase, reference-blind audio review | CPU/memory and license audit first; no false claim of generated song quality |
| Video/editing | PySceneDetect (adaptive/content) + FFmpeg | cut recall/precision against hand-annotated ground truth, camera-motion false cuts, duration coverage | V3 bounded proof only; no semantic scene recognition |
| Render technical fidelity | Netflix VMAF / FFmpeg libvmaf | aligned/reference-preserving frame fidelity under matching preprocessing | VMAF v1 models released June 2026; not artistic scoring, not for two unrelated shots |
| Camera/animation | OpenCV optical flow, Blender scene/rig inspection | camera-vs-object-motion separation, mesh/rig evidence, occlusion/error and frame continuity | separate GPU/CPU workstation proof required, not an invented PASS |
| Editorial timeline interchange | AcademySoftwareFoundation OpenTimelineIO | valid track/clip transitions, explicit fps rational times, imported timeline in actual target editor | mature interchange format; clips reference media, not embedded raw video |
| Websites and UX | Playwright trace, offline HAR, REA static JS/Electron | observable state transitions, layout shift, network timing distribution, accessibility keyboard QA | V3 HAR is safe offline metadata; browser recording requires separately authorized scoped session |
| Native applications | REA + Ghidra headless | binary format, xrefs/call graph, reproducible isolated behavior on owned target | Ghidra external Apache-2.0 runtime; do not enable native decompilers by default |
| Content marketing/YouTube | existing YouTube department and analytics | audience retention and legitimate source evidence, hook/retention A/B with uncertainty | first-party platform metrics alone cannot prove causality |
| Security/reliability | static scanners, exact-bound independent code review | scope-escape probes, prompt-injection resistance, SHA/provenance, zero leaking sensitive audio/HAR | independent security review mandatory before promotion |
| Harness operational learning | existing trusted reducer and memory plane, trace semantics | before/after real artifact, statistical uncertainty, human feedback receipt, stop-on-regression | reverse engineering proposes only; reducer decides and writes |

## Why these specific upstreams

- REA source/CLI: https://github.com/morluto/rea ; release 6.0.0, MIT. Supports JS/Electron, supported browser/native investigations with exact providers. Our V3 limits calls to pinned static/offline mode.
- PySceneDetect: https://www.scenedetect.com/docs/latest/api/detectors.html ; 0.7.1 AdaptiveDetector rolling relative frame differences to reduce camera-motion false positives. BSD-3-Clause. Algorithm disagreement is useful uncertainty evidence.
- Netflix VMAF: https://github.com/Netflix/vmaf ; June 2026 V1 models. Only use for aligned distorted-vs-source image fidelity, with documented preprocessing.
- WhisperX: https://github.com/m-bain/whisperX ; ASR plus forced alignment and context-aware batching (2026), not a guarantee of pronunciation or speaker identity.
- pyannote: https://github.com/pyannote/pyannote-audio ; Community-1 terms/token and heavier torch runtime; offline cached only after required agreements, no premium fallback.
- Playwright: https://playwright.dev/docs/trace-viewer ; traces include network requests, DOM and screenshots, **often sensitive**. HAR may contain authorization, cookies, page content and query tokens; never commit raw traces.
- EBU R128 and FFmpeg: https://tech.ebu.ch/publications/r128 ; https://ffmpeg.org/ffmpeg-filters.html .
- OTIO: https://github.com/AcademySoftwareFoundation/OpenTimelineIO ; time/track/clip/transition interchange, not a video container; Apache-2.0.
- Ghidra: https://github.com/NationalSecurityAgency/ghidra ; Apache-2.0 (component notices may differ); provider install/capacity must be audited.
- Librosa: https://github.com/librosa/librosa ; spectral and onset descriptors are evidence, not a music quality score.

## Operational sequence — implement before claims

**Stage A — completed by V2 and extended in V3 candidate**
1. Existing REA source and package pinned; workspace command with dry-run.
2. Harness governed specialist registry, persisted authorization and path restrictions.
3. Audio/video/script measurement, differential evidence, no secret exposure.
4. V3: bounded adaptive shots, source signal dynamics and offline HAR privacy aggregation; verify CI and real fixtures before asserting PASS.

**Stage B — next controlled implementation**
1. Add calibratable scene benchmark: manually annotate 30+ licensed transitions across slow/fast cuts, dissolve, black, static cartoon, camera whip. Report precision/recall per detector and failures.
2. Add audio benchmark: true silence, clipping, multi-channel phase, dynamics and noisy dialogue from owned synthetic fixtures. Track reference contamination risk.
3. Add runtime and OTel trace receipts keyed to task_id / artifact hash, costs, retries and failure class. No prompts, samples or secret payloads in traces.
4. Add OTIO conversion from *original production* plans only, preserving frame-accurate timing and render reconciliation.
5. Add local storyboard/animation test bench (OpenCV image sequences, Blender only if present) with objective continuity signals and a human creativity review.

**Stage C — models and production experiments**
1. Separate private voice worker: WhisperX alignment and a PT-BR phoneme benchmark on synthetic non-owner samples; only after privacy controls test on human owner voice.
2. Source-limited transcription and citation-binding; never infer facts from subtitles.
3. REAPER stem-level analysis with direct owned multitrack fixtures; benchmark mono/stereo mix, voice-over intelligibility and mastering without fake quality.
4. Use original 20–25 minute BR-no-GTA candidate; evidence must cover complete duration or clearly mark sampling, compare per-section and disclose unknowns.
5. Human approves one candidate on Telegram; only Harness-owned reducer may update learning/canonical release.

## Failure modes requiring STOP

- CI green despite skipped real provider, or a fake/no-op test; count measured operation separately from check count.
- Provider unavailable/doctor exit=1 represented as ready.
- A tiny demo labelled professionally ready for 25-minute production.
- Unversioned upstream dependency, paid fallback, unexpected network or cloud upload.
- Spoken brand pronounciation and owner identity altered through reference study.
- Prompt injection in observed apps/transcripts/HAR; raw content is data, not instructions.
- Weak media claims based on VMAF, shot count or loudness alone; artistic approval requires a human.
- Any git merge, branch promotion, publication or private source push without distinct owner approval.

## Conservative promotion acceptance

(A) All focused and affected tests pass at exact HEAD SHA.
(B) Real FFmpeg + PySceneDetect + REA + HAR fixtures pass, with correct hashes and scoped Harness authorizations.
(C) Gated paths fail on forged authorization, symlinks, alternate paths and secret HAR body injection.
(D) Independent reviewer checks upstream provenance/license, cost guards and no unauthorized authority in code.
(E) One full authorized production benchmark plus owner approval.
All five are necessary for canonical promotion. Branch success alone means development capability has been demonstrated, not deployment readiness.
