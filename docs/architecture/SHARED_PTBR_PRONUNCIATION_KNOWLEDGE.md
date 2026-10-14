# Shared PT-BR pronunciation knowledge

## Canonical source

`config/shared_knowledge/pronunciation_sources.json` is the versioned source registry for the BR-no-GTA project. Research, script generation, pronunciation resolution, owner-voice synthesis, audio QA, human review, and release gates must reference this registry rather than maintaining private copies of source URLs or independently asserting that a source was validated.

This registry is project-scoped. It does not share BR_OWNER_V1 private voice samples or project state with Hazewave or other projects.

## Evidence states

- `REMOTE_FILE_PRESENT_METADATA_VERIFIED`: a file exists at the recorded Codespace path and ffprobe confirmed its media metadata. This does not establish that its title/channel matches the intended reference.
- `HISTORICAL_CANDIDATE_UNVERIFIED`: source identity/title/channel still needs confirmation.
- `PENDING`: no acoustic analysis or current human approval has been proven yet.

Never promote a term to acoustically validated or human-approved merely because a source is present, a transcript exists, an ASR model agrees, or research coverage is 100%.

## Required new audition flow

The two source files in the registry must be processed as fresh inputs. The earlier run and its rejected audition may be used for diagnostics only; they do not count as the new run or its evidence. Extract and timestamp source-audio windows, attach provenance to each pronunciation finding, update the shared evidence registry conservatively, generate a fresh BR_OWNER_V1 voice audition, execute the pronunciation and identity gates, and deliver that voice audition to Telegram for human review. Never send the video to Telegram. The final video remains YouTube-private HD and blocked until the project's required approvals pass.

## Integration contract

Every workflow that uses pronunciation knowledge must read the canonical pronunciation lexicon and evidence registry, and may use the source registry to locate and attribute source audio. Do not copy source-specific pronunciations into workflow-local constants. A workflow that cannot load the shared files must fail closed when a target term requires pronunciation evidence.

## Current verified facts

- `f8IZhKcuEts.mp4`: 176.294 s, Opus stereo, 48 kHz, remote SHA-256 recorded in the registry.
- `K6rVM6gn6k4.mp4`: 167.354 s, Opus stereo, 48 kHz, remote SHA-256 recorded in the registry.
- Both remote files exist. Their local-origin hashes have not been compared because the expected Termux source path was absent.
- Exact title/channel identity and fresh acoustic analysis are still pending.
