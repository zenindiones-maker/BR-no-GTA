# Owner Voice Telegram Integration v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Telegram owner-voice enrollment secure, idempotent, and capable of producing a real Qwen owner-voice audition from a deterministic pinned model snapshot.

**Architecture:** A15 handles authenticated metadata intake and content-addressed handoff; one trusted Actions job materializes audio in ephemeral private storage and loads a complete pinned Qwen snapshot locally. Generic voice fallback remains impossible and promotion remains human-gated.

**Tech Stack:** Python 3.12, Telegram Bot API, GitHub Actions/Secrets, FFmpeg, Hugging Face Hub, qwen-tts 0.1.1.

**Spec:** `docs/superpowers/specs/2026-09-29-owner-voice-telegram-v2-design.md`

## Global Constraints

- `BR_OWNER_V1` is the only active voice identity.
- Raw audio/transcripts/embeddings/clone prompts never enter Git, Actions cache, or artifacts.
- Qwen 0.6B revision is `5d83992436eae1d760afd27aff78a71d676296fc`.
- Generic/default/preset speaker fallback count is zero.
- Telegram owner authorization and authorized-chat checks remain fail-closed.
- DeepSeek Harness remains the sole authority.

## Review Focus

- Partial Hugging Face snapshots must fail before model initialization.
- Unchanged reference indexes must not redispatch merely because HEAD changed.
- Secret/log output must not reveal Telegram file IDs.
- Multiple references must remain deduplicated and deterministic.
- Failed materialization must not mark owner voice READY.

---

### Task 1: Deterministic Qwen snapshot loader

**Files:** `scripts/owner_voice_qwen_ephemeral_audition.py`, `tests/test_owner_voice_qwen_audition.py`

- [ ] Add a failing test requiring the embedded speech tokenizer manifest.
- [ ] Run focused test and observe `QWEN_SNAPSHOT_INCOMPLETE`/missing API failure.
- [ ] Implement pinned `snapshot_download`, manifest verification, and local-only model load.
- [ ] Run focused tests GREEN.

### Task 2: Opaque and content-addressed Telegram handoff

**Files:** `app/services/owner_voice_telegram_handoff_service.py`, `scripts/owner_voice_reference_handoff.py`, `tests/test_owner_voice_reference_handoff.py`

- [ ] Add failing tests for opaque base64 secret and HEAD-independent dispatch key.
- [ ] Run focused tests RED.
- [ ] Implement envelope encoding/decoding and content-only dispatch identity.
- [ ] Run focused tests GREEN.

### Task 3: Secure workflow surface

**Files:** `.github/workflows/owner-voice-private-materialization.yml`

- [ ] Replace structured secret with opaque envelope secret.
- [ ] Pin GitHub Actions by full SHA.
- [ ] Remove artifact upload and split-cache environment.
- [ ] Use one ephemeral model directory and emit no sensitive identifiers.

### Task 4: Integration verification

**Files:** relevant voice/Telegram test suites.

- [ ] Run owner handoff, materialization, Qwen audition and Telegram voice tests.
- [ ] Run BR-no-GTA CI.
- [ ] Trigger one Owner Voice Private Materialization run.
- [ ] Verify real reference download > 0, snapshot manifest PASS, generic fallback 0.
- [ ] Deliver audition to Telegram and leave `HUMAN_REVIEW=PENDING`; do not mark READY before human approval.
