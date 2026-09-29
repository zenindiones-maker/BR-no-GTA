# Owner Voice Telegram Integration v2 — Design

## Goal

Materialize the authorized human owner's real Telegram voice as `BR_OWNER_V1` without committing biometric media, without generic-speaker fallback, without run storms, and without allowing a synthesis receipt to claim owner identity unless the real reference binding was used.

## Security boundary

- Telegram accepts voice/audio only from the already-authorized owner and authorized review group.
- A15 stores Telegram metadata only; media bytes remain off-device.
- Telegram `file_id` is used only inside the private handoff/materialization boundary. `file_unique_id` is for deduplication and cannot substitute for `getFile`.
- The GitHub handoff is one opaque base64 envelope stored in GitHub Secrets. Decoded identifiers are masked before any later command can log them.
- Raw audio, transcripts, speaker embeddings and Qwen clone prompts are never committed, cached with Actions cache, or uploaded as Actions artifacts.
- Workflow permissions remain `contents: read`; trusted push/workflow_dispatch only; no PR execution for biometric work.
- Third-party actions are pinned by full commit SHA.
- Default/preset/generic voices are forbidden when `voice_identity_id=BR_OWNER_V1`.

## Handoff and idempotency

- Reference index identity is content-addressed by `index_sha256`.
- Dispatch identity depends on the reference index, not Git HEAD, so code updates do not redispatch unchanged biometric references.
- Gateway coalesces multiple voice/audio ingests before invoking the handoff; the handoff itself remains idempotent.
- A failed dispatch does not mark the local state as delivered.

## Private materialization

The Actions runner downloads each real Telegram reference with `getFile` into runner-temporary storage outside the repository, verifies size and SHA-256, normalizes audio with FFmpeg, and deletes it when the runner ends. Logs contain only typed status and counts.

## Qwen runtime

- Interactive audition model: `Qwen/Qwen3-TTS-12Hz-0.6B-Base`.
- Revision: `5d83992436eae1d760afd27aff78a71d676296fc`.
- The complete pinned Hugging Face snapshot is downloaded to one explicit local directory before model loading.
- Required root and `speech_tokenizer/` files are verified before calling Qwen.
- Qwen loads from the verified local directory with `local_files_only=True`, avoiding split Transformers/Hugging Face caches.
- The first diagnostic audition may use x-vector mode only as `AUDITION_ONLY`; it cannot promote `BR_OWNER_V1` to READY.
- Production promotion requires a transcript-conditioned clone prompt (`ref_audio + ref_text`) and human review.

## Promotion

`BR_OWNER_V1` remains fail-closed until private reference QA and a human-approved owner-voice audition exist. Only then may private profile state move to READY. Every production synthesis must carry an `OwnerVoiceSynthesisReceipt/v1` matching the reference/prompt/profile hashes.
