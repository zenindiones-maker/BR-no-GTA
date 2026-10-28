# BR_OWNER_V1 reference ASR survey v1 (ASR only)

Status: PREPARED, not run. Running requires an owner-approved commit adding
`.run/br-owner-v1-reference-asr-survey.request.json` on
`work/br-owner-voice-mission-state-failclosed-v1`.

## Goal
Transcribe every identity-inlier owner clip (54 in the last calibrated run) once,
to find more *distinct* clean reference clips for later human-reviewed selection.
The survey has no selection authority (`NONE_HUMAN_OWNER_REVIEW_REQUIRED`).

## Pipeline (scripts/owner_voice_reference_asr_survey.py)
1. Index from the existing secrets (names: `BR_OWNER_TELEGRAM_REFERENCE_ENVELOPE_B64`
   or `BR_OWNER_TELEGRAM_REFERENCE_INDEX`, `TELEGRAM_BOT_TOKEN`); download with
   Telegram `getFile` only. A wrapper rejects every other Bot API method.
2. ffmpeg → mono 16 kHz PCM; `pcm16_quality_metrics` (SNR, clipping, duration).
3. Pinned ECAPA (`speechbrain/spkrec-ecapa-voxceleb`, sha-checked) → existing
   `calibrate_owner_identity_profile` → inliers; window consistency as today.
4. faster-whisper `large-v3-turbo`, CPU int8, `vad_filter=True`, beam 5,
   language auto-detect (pt probability recorded).
5. Dedupe: exact sha256; near-duplicate = speaker cosine ≥ 0.97 AND transcript
   token Jaccard ≥ 0.80 (same-speaker clips are naturally similar, so cosine
   alone never marks a duplicate).
6. Quality filters (survey only, gates untouched): duration 3–30 s, SNR ≥ 15 dB,
   clipping ≤ 1 %, VAD speech ratio ≥ 0.60, pt probability ≥ 0.80, ≥ 4 words,
   0.5–6 words/s, window identity consistent.
7. Ranking: greedy MMR 0.7 × centroid similarity + 0.3 × (1 − max transcript
   overlap with already ranked clips).

## Privacy
Public artifact = one JSON: ids, Telegram message ids, file sha256, scalar
metrics, transcript sha256, word count, canonical-term hits, rank, reasons.
Never: audio, embeddings, transcripts, private paths. Private workspace
(`$RUNNER_TEMP`, chmod 700) is deleted in an `always()` step. Retention 7 days.

## Out of scope
No Qwen/TTS install or load, no synthesis, no Telegram send, no ledger write,
no threshold or policy change, no automatic reference promotion.

## Cost and time
GitHub-hosted `ubuntu-24.04` standard runner (free minutes only; public repos
are free, private repos use the monthly free quota). Estimate: install 3–5 min
(CPU torch wheel), model download ~1–2 min (turbo ~1.6 GB, ECAPA small),
Telegram download + embeddings 2–4 min, ASR of ~54 clips × ~8–20 s audio
≈ 8–18 min on 4 vCPU int8 beam 5. Total ≈ 15–30 min; job timeout 45 min.
