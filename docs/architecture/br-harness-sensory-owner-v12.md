# BR-no-GTA: V12 sensory evidence and owner voice cohesion

Status: isolated candidate. No automatic merge, publication, voice approval, paid model or new workstation.

## Real diagnosis

- REA V9: owned ELF Ghidra static analysis and 3205 input differential checks passed; this did not prove automatic perfect reconstruction or native network sandboxing.
- Iris V8: Chrome screenshot and actual dark-mode pixel differences passed; visual semantics are not automatically proven.
- Video QA V10b: bounded FFmpeg samples, independent whole-video and whole-audio decode, negative controls passed on synthetic clips, not a 20–25 minute real show.
- Owner voice V11: new clone Telegram ID 666 (human reference 665, control 667), seven calls completed but identity failed in 7/7, pronunciation failed in 3/7. Human approval still pending.
- Old textual Vice City spelling was corrected to the user-required vaicy siti in the V11b voice/editorial/evidence branch; this is not an acoustic pass.

## V12 fixes

Qwen3-TTS Base normally produces ref_code, ref_spk_embedding and ref_text from the SAME reference audio when create_voice_clone_prompt is called. V11 manually fused speech tokens and reference embeddings from two different recordings. V12 eliminates that fusion: anchor, pronunciation and Vice City selections are now complete model-generated prompt objects from their respective owner Telegram recordings, never mixed tensors. This is a testable root-cause hypothesis, NOT confirmed causality; a fresh real owner-audition and calibrated identity checks are required.

The serial generation call count log is corrected to show number of per-segment invocations, instead of a hard-coded one. The Qwen model, owner-only reference, fresh pronunciation sample rule, ECAPA identity and human rejection policy stay unchanged. No false PASS from revised model code.

Official reference: https://github.com/QwenLM/Qwen3-TTS/blob/main/qwen_tts/inference/qwen3_tts_model.py

## V12 Eyes: measured observation versus interpretation

The Harness receives a registered, persisted-authorization-controlled RESEARCH capability that reads only scoped owned PNG or MP4 files. For video, FFprobe checks streams and FFmpeg extracts actual frame PNG images; Pillow decodes pixels, measures real RGB means and 64x64 frame-to-frame differences, with source and frame digests. Frame files remain in a private owner-approved 0700 scratch directory (0600 samples).

The evidence truth table is: catalog presence != pixels captured; pixels captured != semantically understood; 4 frames != entire 20–25 minute video; signal metrics != identity; published message != approved performance. Every V12 receipt explicitly reports semantic_scene_understood=false, voice_biometrics_read=false, no unauthorized export, no memory write, no publication authorization. A separate trusted vision interpreter will be required before any agent claims to understand the scene.

For browser state, Playwright guidance distinguishes screenshot inspection from accessibility snapshots for interaction: https://playwright.dev/mcp/tools/screenshots .

## Remaining priority gaps, do not conceal

1. Real BR_OWNER_V1 audition: coherent prompt design still needs measured voice identity, Brazilian pronunciation, fluency and explicit owner approval; candidate 666 was not approved.
2. Full 20–25 minute program: a synthetic MP4 test does not establish real editorial content, no overlays, asset rights or accurate scene timing. Integrate V10b into a reviewed common base before claiming production readiness.
3. Telegram and YouTube: need confirmed new audition message plus owner ACCEPT and actual private HD full-video upload before final publishing approval.
4. Worktree coherence: V12 now imports the V10 sampled media QA, V10b independent full-audio/full-video decode and remediation board into the same isolated branch as Voice V11b and the pixel observation adapter. Real end-to-end CI on that combined branch must pass before calling the integration tested. REA and Iris native/browser implementations remain on their own research branches, and NOTHING is promoted to canonical until exact-bound security review and deliberate consolidation.
5. Durable TTS inference across GitHub runner shutdown is not implemented; local per-segment temporary WAVs disappear after job loss. Private encrypted storage, authenticated lineage and recovery need a separately approved design.
6. Semantic 'eyes' need an authorized multimodal model that actually consumes decoded frames with grounded citations, controlled prompts and tests on failure cases. The present V12 observes pixels but does not interpret subject identity or visual meaning.

## Execution contract

Observe -> measure -> compare with original/negative controls -> explain confidence and failed boundary -> independently review -> authorize specific next step. No endless rerun, no trusting raw pseudocode or external visual text as an instruction, no auto-canonical promotion and no changes to BR_OWNER_V1 security boundaries.

Sources: https://ffmpeg.org/ffprobe.html ; https://ffmpeg.org/ffmpeg-filters.html ; https://github.com/QwenLM/Qwen3-TTS ; https://playwright.dev/docs/screenshots

## V12 production QA convergence

In the same development branch, the Harness now has two distinct persisted RESEARCH tools: reverse-engineering.multimodal.sensory-pixels-v12 (bounded private pixel observation) and production.technical-media-forensics (FFprobe/FFmpeg evidence from the V10/V10b suite). For the latter, sample-level QA is followed by optional independent full video and full audio decoding, then a deterministic board of next technical actions. Both explicitly return publication=FORBIDDEN, production_ready=false or semantic understanding=false, and neither may approve the owner voice. This is a research-plane integration, not a replacement for the original production controller.
