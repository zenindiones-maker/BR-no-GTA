# BR-no-GTA — V16 Visual Timeline With Real Evidence

Status: isolated research candidate, based on passing V15 SHA b0ec8c4fc293109859fd09270430f93eb1a82380. No canonical merge, no LLaMA-Factory training, no owner voice exposure, no paid compute, no Telegram send or publication.

## Why another measurement

V12 extracted four actual MP4 frames and measured differences but could not find intermediate cuts. The next target is temporal coverage: pass an authorized original video through the decoder and locate content-change candidates near actual timestamps. Do not claim that this determines the people, artists, images, subtitling or quality of an entire episode.

The V16 detector uses FFmpeg select gt(scene,0.18) and showinfo on bounded windows (up to three eight-second windows near the start, middle and end of up to 30-minute owned videos). It parses only numeric timestamp observations and retains a SHA-256 link to the same source media previously captured by the V12 pixel probe. The 0.18 cutoff is a *benchmark setting* and not a universal optimal cutoff. Timestamps from independently sought windows are approximate; do not use this as frame-exact subtitle alignment.

Every frame is decoded inside a bounded process. A real 6s original synthetic red-to-blue two-shot clip must yield a cut around 3 seconds. A 6s constant-color clip must yield zero cuts. Input alteration, expired Harness authorization, file scope escape, private biometric paths or attempt to use scan mode on PNG must be blocked. No shell interpolation, no raw frames in output, no OCR, no external model, no claim of semantic perception, no embedded promotion/publication instruction accepted.

Research: FFmpeg frame select and showinfo https://ffmpeg.org/ffmpeg-filters.html ; PySceneDetect calibration of scene thresholds https://www.scenedetect.com/docs/latest/ ; GitHub non-fast-forward conflicts https://docs.github.com/en/get-started/using-git/dealing-with-non-fast-forward-errors.

## Current actual launch blockers after V15

1. Qwen3-TTS BR_OWNER_V1 last measured 7/7 identity failures, 3/7 pronunciation failures; no new human-approved voice. Do not reduce ECAPA/ASR thresholds or reuse rejected clones.
2. The 2026-10-08 ledger push failure was fast-forward/commit_refs. V13 implemented one retry and V14 verified local bare-Git CAS; authentic remote ledger transaction and Telegram readback remain unproven. Never force push or resend media blindly.
3. V10–V12 video QC tests decoded synthetic samples, not an original 20–25-minute production master approved by a person.
4. LlamaFactory 0.9.5 exists only as pinned source/installed distribution in ephemeral CI. No native Qwen3-TTS 1.7B Base training authorization; official TTS single-speaker training is a different supported workflow.
5. Interactive charts/controls belong to ChatGPT conversation UI; there is no on/off toggle in the BR-no-GTA repository that activates ChatGPT client feature. A real Harness operator cockpit requires its own authenticated and reviewed dashboard, not a fake feature flag.

Next after V16 real cut proof: a credential-separated vision reasoning model consuming only approved private frames, timestamped speech-to-script alignment, scene/storyboard map, and calibrated evaluations against owner-reviewed footage. Never claim full eyes based on scene cut scores.
