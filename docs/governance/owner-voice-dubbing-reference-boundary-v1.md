# BR_OWNER_V1 — dubbing reference boundary (mandatory)

## Voice identity
Only the owner's authorized **BR_OWNER_V1** reference audio may be used as a speaker embedding, reference audio, cloning prompt, voice adaptation target, or synthesis voice. Human dubbing references **must never** supply speaker identity, embedding, voice conversion input, or fallback voice. Do not train on, clone, or imitate the identifiable voice of either narrator or actor.

## Permitted learning
The two selected YouTube videos (YouDubbing `f8IZhKcuEts` and MANGÁ K `K6rVM6gn6k4`) are **pronunciation and prosody research only**. Short, legally accessible excerpts may be inspected for phonemes, syllable stress, pause locations, phrasing and cadence. Transcripts alone do not establish acoustic pronunciation. Keep timestamps and evidence hashes. Preserve owner-locked `Vice City -> vaicy siti`.

## Promotion and runtime
Any candidate must pass the fail-closed `app/services/owner_voice_dubbing_reference_policy.py` admission contract. This contract **does not activate** candidates in synthesis. Runtime activation requires separate explicit human approval after an audition rendered with the original owner voice. Keep all existing voice identity, pronunciation, audio-quality, delivery-ledger and Telegram gates unchanged. Never lower thresholds, use another speaker, or silently fall back. Do not start long-form production before approval.

## Scope
Repository `zenindiones-maker/BR-no-GTA` only. No Hazewave changes. A15 remains control-only.

## Supersession and delivery boundary (2026-10-10)

Owner instruction: replace the prior audition candidate with a **new** BR_OWNER_V1 audition informed by the two approved dubbing videos. Historical run `38025936216` is preserved as completed history, **not** accepted as the new audition or human approval. Its delivery must be reconciled with the private ledger and Telegram before any new send; successful GitHub delivery steps are not proof of human receipt.

Required execution order:

1. Read the exact active HEAD and preserve all current owner voice WIP and immutable ledger entries.
2. Obtain lawful short acoustic observations from both approved videos. Record exact video ID, term, start/end timestamps, evidence digest, verified spoken reading, syllable timing and reviewer; never infer audio from subtitles. If audio is inaccessible, **block** acoustic promotion rather than invent evidence.
3. Keep the speaker conditioning/reference audio **exclusively** from authorized `BR_OWNER_V1` material. Never pass video audio, actor audio or actor embeddings to Qwen3-TTS speaker conditioning, cloning, training or voice conversion.
4. Propose pronunciation/prosody adjustments only from verified acoustic observations. Keep owner-locked `Vice City -> vaicy siti`; no auto-approval, no unverified runtime overrides.
5. Generate one short audition using the owner's voice; validate identity, lexical accuracy, timing, fluency, audio quality and existing thresholds. Fail closed on any gate; no fallback voice.
6. Reconcile previous send/ledger state and deliver the **new** candidate once through the authorized Telegram transport. Require an idempotent send receipt and await explicit human approval.
7. Do not start a 20–25-minute YouTube production until the new candidate is approved.

The reference-policy service is an admission guard, not an acoustic extractor or a synthesis integration. Its presence does not prove the new audition exists.
