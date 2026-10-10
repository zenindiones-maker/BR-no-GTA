# BR_OWNER_V1 — dubbing reference boundary (mandatory)

## Voice identity
Only the owner's authorized **BR_OWNER_V1** reference audio may be used as a speaker embedding, reference audio, cloning prompt, voice adaptation target, or synthesis voice. Human dubbing references **must never** supply speaker identity, embedding, voice conversion input, or fallback voice. Do not train on, clone, or imitate the identifiable voice of either narrator or actor.

## Permitted learning
The two selected YouTube videos (YouDubbing `f8IZhKcuEts` and MANGÁ K `K6rVM6gn6k4`) are **pronunciation and prosody research only**. Short, legally accessible excerpts may be inspected for phonemes, syllable stress, pause locations, phrasing and cadence. Transcripts alone do not establish acoustic pronunciation. Keep timestamps and evidence hashes. Preserve owner-locked `Vice City -> vaicy siti`.

## Promotion and runtime
Any candidate must pass the fail-closed `app/services/owner_voice_dubbing_reference_policy.py` admission contract. This contract **does not activate** candidates in synthesis. Runtime activation requires separate explicit human approval after an audition rendered with the original owner voice. Keep all existing voice identity, pronunciation, audio-quality, delivery-ledger and Telegram gates unchanged. Never lower thresholds, use another speaker, or silently fall back. Do not start long-form production before approval.

## Scope
Repository `zenindiones-maker/BR-no-GTA` only. No Hazewave changes. A15 remains control-only.
