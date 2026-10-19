# Owner authorizations and voice/release gates (verbatim from AGENTS.md)

Moved verbatim from AGENTS.md (lines 42-85 at 3009be57) to keep the root map
short. AGENTS.md pins this file by sha256; any edit requires updating that hash
in the same reviewed commit. Content below is unchanged.

## Single-human voice/release gates V11 (isolated candidate)

Follow docs/architecture/br-owner-voice-and-production-gates-v11.md. Single
BR_OWNER_V1 human reference from Telegram only; Qwen 1.7B Base serial calls,
private per-segment metrics and no reuse of rejected audio. Scratch
checkpoints are NOT cross-run durable. Real owner-certified voice then complete
20–25 minute professional render then private Telegram/YouTube owner approval.
No fallback voice, unattended delivery, canonical promotion, or invented PASS.

## BR-no-GTA V13 release boundaries (isolated candidate)

Read docs/architecture/br-production-gates-v13.md. Pinned LlamaFactory
v0.9.5 is admitted for source/package metadata validation ONLY: never assume
a GPU, model weights, training, WebUI or TTS support. ModelScope/ms-swift
remains the separate, private, explicitly authorized owner Qwen3-TTS trainer.
Neither Agent Office nor LlamaFactory has authority over DeepSeek Harness.

The audited Munder upstream must use ephemeral proxy-addr 2.0.8 and must not
run as an authorized runtime while newly discovered high-severity advisories
remain unresolved. Never add vulnerabilities to an allowlist to silence CI.

OWNER_AUTHORIZED_20261011_SEGMENT_GATE_P10_BINDING: on 11/10/2026 the owner
(Luiz) explicitly authorized, in chat, one policy change: the BR_OWNER_V1
per-segment identity gate's centroid floor is the p10 of his real
duration-matched (5-7 s) voice windows vs the owner centroid, recomputed per
run from consented Telegram references, and is BINDING (no longer shadow).
Unchanged: the per-segment reference floor (clone_reference_min_similarity)
and the whole-audio centroid gate 0.868594, which is also binding. Any other
threshold change still requires new explicit owner authorization.

OWNER_AUTHORIZED_20261011_SEGMENT_REFERENCE_P10_BINDING: on 11/10/2026 the
owner (Luiz) explicitly authorized, in chat: (1) per-segment speaker
similarity "to reference" is measured against the embedding of the exact
ref_audio given to Qwen (the trimmed owner window), not the full canonical
clip; (2) the per-segment reference floor is the p10 of his real
duration-matched (5-7 s) voice windows vs that same embedding (windows from
the canonical clip itself excluded), and is BINDING. The whole-audio centroid
gate 0.868594 stays binding and unchanged.

Keep BR_OWNER_V1 single-human voice thresholds untouched; canonical script
names remain unchanged with controlled spoken "vaicy siti". No recovery push
may trigger owner fine-tuning. Production begins only after a new, delivered
human-approved audition, actual 20–25min fully decoded original render,
rights/factual review and explicit PRIVATE HD owner approval. No auto-publish.
