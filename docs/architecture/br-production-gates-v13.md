# BR-no-GTA — V13 Production Recovery + LlamaFactory Admission

State: isolated candidate branch. No merge to draft PR #17 or canonical HEAD, no speech approval, no model training, no paid cloud, no new Codespace, no Telegram/YouTube publication.

## Exact observed blockers at start (2026-10-08)

- V12 SHA ce5343b864cc8583ec984ae76910f99634d18cf2; PR #17 draft, not merged.
- Agent Office Validation 37811523243 FAIL: pinned Munder Difflin upstream npm audit discovered a new critical in proxy-addr and six new unreviewed high-risk packages.
- Phone Control 37811523311 FAIL: 7 contract regressions / 4166 passing unit cases. Historical tests were not aligned with the newer governed single-owner code-switch, "vaicy siti", current capitalization and dispatch-only security policy.
- BR_OWNER_V1 most recent reported clone similarity 0.643708 vs centroid 0.868594; 7 of 7 speaker checks failed, 3/7 pronunciation checks failed; ledger delivery failed in run 37808729277. No approved voice. Never alter thresholds merely to pass.
- Proven sensory pixels, REA owned ELF and synthetic FFmpeg/whole-audio/whole-video QA remain bounded research, not a finished 20–25 minute episode.

## V13 corrected contracts

The latest owner-approved pronunciation strings are preserved in the canonical lexicon. Old tests are rewritten to protect current semantics: a single BR_OWNER_V1 voice, explicitly listed foreign-name spans only, no generic name autodetection, exact "vaicy siti", unchanged editorial source text, human approval of critical terms, and an explicit synthesis field in current_audio_contract. No automatic foreign speaker fallback.

Qwen fine-tuning's workflow now uses workflow_dispatch only. Never allow recovery-dev push to launch large model training or private biometric processing. This does not authorize new audition or report Telegram delivery.

## Third-party upstream Agent Office

Pin upstream Munder DiffLin source to 6248293a7cd9dfdbf9633d12bbe857831ccfee88. An ephemeral checkout is modified by an exact npm override for proxy-addr 2.0.8 (GitHub advisory CVE-2026-90711); immutable source HEAD is checked first, and the resulting npm lock and installed package are independently verified. The patch is NOT merged into the pinned vendor repository and the addon remains non-authoritative.

Observed post-patch CI 37821620005: CRITICAL_COUNT=0, but six new high packages remain outside prior reviewed list: @modelcontextprotocol/sdk, @types/jest, braces, expect, jest-message-util, micromatch. This is not a PASS. In particular braces CVE-2026-93687 has no patched release listed in the GitHub-reviewed advisory as of current research. Never hide vulnerability findings by blanket allowlisting. Agent Office remains security-blocked for promotion until independent risk mitigation and full audited lock. Sources:
- https://github.com/jshttp/proxy-addr/security/advisories/GHSA-jqcg-44mw-7w3h
- https://github.com/advisories/GHSA-vfj7-8cjw-p6xm

## LlamaFactory optional installation

Upstream renamed LLaMA-Factory to LlamaFactory. Exact release: v0.9.5, source SHA 7af909522a951e3ad9f022ea6f88b6755257eaa5, Apache-2.0. V13 uses only a separate ephemeral Python 3.12 virtual environment and pinned source packaging without model dependencies. A metadata receipt verifies Git SHA, 0.9.5 version, pyproject hash and source cleanliness. This is a TRUE source/package installation test, NOT GPU/model-loaded inference or LLM training.

LlamaFactory may later be admitted for owner-authorized text/multimodal agent fine-tuning once dataset provenance, private training isolation, model support, exact GPU cost and quality baseline are independently proven. It is not a substitute for the official Qwen3-TTS voice fine-tuning route (BR_OWNER_V1 uses model-specific ModelScope/ms-swift plan). No model weights, reference voices, prompts or license-protected data are downloaded by this gate.
- https://github.com/hiyouga/LlamaFactory/releases/tag/v0.9.5
- https://github.com/QwenLM/Qwen3-TTS/blob/main/finetuning/README.md

## Next proof order

1. Full ~4200 test root suite on exact V13 head; check new failure types, especially workflow security boundaries.
2. Agent Office high-severity audit: no admission while upstream unpatched packages can run with unrestricted I/O.
3. Certified BR_OWNER_V1: analyze reference/candidate per-segment identity and prosodic mismatch, create a new coherent Qwen/reference candidate only if necessary, fail closed on ECAPA/ASR/owner human gate; durable ledger persistence must be fixed before a new send.
4. Full 1080p 30fps H.264/AAC original and legally sourced 20–25min episode; independently decode entire video/audio and inspect actual scene/narration mapping.
5. Private YouTube HD, confirmed Telegram delivery and final owner approval. Never publish publicly without approval.

## Regarding GPT-6 rich responses

Charts, diagrams, buttons and inline rich controls in ChatGPT are a client capability, not an open-source GitHub package to install. The assistant can use supported rich response controls when appropriate; ChatGPT does not expose an API to grant this UI behavior to unrelated external systems or accounts by changing the BR-no-GTA repository. For the Harness, an independent safe approval interface would need to be implemented and reviewed (authenticated status, explicit opt-in actions, no UI button triggers publication alone).

## Delivery-ledger fail-closed repair

The 2026-10-08 voice run 37808729277 reported `LEDGER_FAST_FORWARD_PUSH_REJECTED` with GitHub `fatal error in commit_refs` code 52. V13 adds one bounded *ledger Git push* retry only when (1) the error is exactly the known transient commit_refs 52, (2) remote readback still equals the expected old SHA, and (3) the same content-addressed candidate commit is replayed. A changed remote SHA raises CAS_CONFLICT. A second failure, different return code, or ambiguous readback fails closed. No `--force`, no regenerated commit, no Telegram post or media resend, no synthetic message ID. SSH key paths are shell-quoted. New tests reproduce success, persistent error, unrelated rejection and remote SHA drift. This fix requires a real private-run readback before the delivery system can be declared operational.

This change does NOT resolve BR_OWNER_V1 identity quality (last seven checks failed); never send/approve a new audition until the voice artifact and ledger state pass independent checks.
