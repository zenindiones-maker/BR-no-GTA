# BR-no-GTA — Three production gates (V11)

Status: isolated test candidate, NOT promoted. DeepSeek Harness remains sole authority.

## 1. BR_OWNER_V1: confirmed blocker and actual correction

The inspected run 37774437402 emitted Qwen inference heartbeats through 540 seconds, then the GitHub runner sent a shutdown signal and the job exited 143. This does not prove a model deadlock, OOM, failed voice identity, or the six-hour GitHub Actions limit. The run did not prove a new CLONE_TELEGRAM_MESSAGE_ID.

At the previous voice head 451462b26f18f6cc74bb32fede1c03f5cfcad628, a single Qwen 1.7B Base call received all multilingual segments as a batch. Qwen officially supports a single-item invocation and a reusable voice-clone prompt. V11 changes only the invocation schedule: run one language/prompt segment at a time, retain the same owner Telegram reference, voice identity ECAPA checks, targeted PT-BR pronunciation, and one final human-reviewed candidate. Source: https://huggingface.co/spaces/Qwen/Qwen3-TTS/blob/main/qwen_tts/inference/qwen3_tts_model.py

Each segment has bounded finite audio validation, stable sample rate, real generation time and RTF, a 0600 local WAV checkpoint and 0600 SHA-256 metadata record. Logs contain only ordinal progress and numeric metrics. No plaintext owner voice, prompt embedding, or rejected candidate is uploaded or reused.

Important: these local checkpoints DO NOT survive deletion of the hosted runner. They are not yet a cross-run durable recovery solution. Such a solution needs separately reviewed private encrypted storage and strict lineage and human-approval gates. Heartbeat does not prevent shutdown. V11 unit CI uses only synthetic audio; actual Qwen inference and Telegram send have not been proven by that test.

## 2. Real 20–25 minute audiovisual episode

The independent research candidate work/br-production-forensics-readiness-v10 (head 7f220bb4b40a6f408cadbea4d9b2954ddc7c326c, run 37799365269) proved FFmpeg technical canary, missing/silent audio rejection, fake-duration rejection and diagnostic followups.

For real production, still require an approved BR_OWNER_V1 private clone, owner-reviewed long-form original script, licensed source media, 1920x1080/30fps H.264 yuv420p, AAC 48kHz, true 20–25min with no padding, complete decoding, lips/narration sync, absence of unintended overlays and independent artistic QA. Do not equate a 3s technical canary with a finished episode.

## 3. Telegram and YouTube private owner approval

Existing owner_voice_single_clone_delivery.py is responsible for Telegram reference, clone and control messages plus its private ledger. Require a genuinely confirmed new CLONE_TELEGRAM_MESSAGE_ID greater than 663 and the owner's explicit approved review. Existing older rejected A/B/C must not be reused. A queued or attempted Telegram send does not count as delivered.

Only after identity, pronouncing Vice City as vaicy siti, full render and independent review: upload YouTube PRIVATE HD, send the owner review link, and await explicit final human approval. No public auto-release.

## Measurement hierarchy

Installed -> provider ready -> executed -> original measured artifact -> independent identity/content evaluation -> owner approved -> release separately authorized.

No return value or digest from V11 may grant production, model promotion, other voices, paid provider, or publish authority. This does not create a second agent authority.

Official guidance: https://github.com/QwenLM/Qwen3-TTS ; https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#jobsjob_idtimeout-minutes ; https://ffmpeg.org/ffmpeg-filters.html
