# BR-no-GTA — Reverse Engineering Specialist / Operational Playbook V2

**Status: CANDIDATE_ONLY. DeepSeek Harness remains the sole authority.**

REA, FFmpeg, ffprobe and narrative timing measurements are subordinate tools. They cannot become a second scheduler, editor-in-chief, publisher, owner-voice identity or source of canonical memory.

## Registered specialist capabilities

1. **reverse-engineering.media.observe** — domain audiovisual-analysis; action RESEARCH; read-only deterministic FFmpeg/ffprobe measurement, SRT/TXT structure and optional original-candidate comparison.
2. **reverse-engineering.software.rea-static** — domain software-investigation; action RESEARCH; pinned REA 6.0.0, static JavaScript only. Returns bounded digest/schema metadata; no decompiled raw code to agents.

Each invocation requires an existing persisted Harness authorization, exact capability subject, scoped absolute paths from authorization lineage.allowed_media_roots, matching HarnessRoutingDecision, canonical TaskEnvelope, explicit rights declaration and local runtime. No agent may create or self-sign that authorization.

The CapabilityAdapter remains the integration point. Fail-closed rules reject revoked/fake authorizations, wrong action, mismatched routing, symlinked/out-of-scope targets, protected owner voice paths, undeclared rights, unknown payload fields or missing providers.

## Measurement contracts

**Audio:** source LUFS, input dBTP and loudness range measured by FFmpeg loudnorm input-side analysis; silence intervals below -40 dB lasting >=250 ms; codec, channels, sample rate and duration.

**Video:** stream dimensions, codecs and framerate fields; black intervals >=200 ms, frame freezes >=500 ms; optionally candidate scene cuts. Deliberate black screens and static animation count as technical events, not errors.

**Script:** TXT words/paragraphs and punctuation; SRT subtitle density, overlap, gap durations and 12-bin narrative timing distribution. Subtitles do not prove spoken words per minute, emotions or plot quality.

**Software:** bounded static REA JavaScript analysis of an approved local directory. Hopper, Ghidra, dynamic browser inspection, debugging, process launch, app execution and DRM bypass are not authorized by this capability.

Evidence includes source/proposal SHA-256 and exact method. Source dialogue is never copied into the receipt. Any unavailable measurement is NOT_RUN, NOT_APPLICABLE or fails closed; never fabricate numerical zeros.

## Closed-loop improvement protocol

1. Acquire permission and original or observation-only reference. Mark the source provenance and ownership scope.
2. Measure and create an evidence envelope. Separate MEASURED, HYPOTHESIS and UNKNOWN.
3. Identify a reproducible difference and create a BRReverseEngineeringLearningProposal/v1 with a user-defined original creative objective.
4. Build an **original** script/render/voice/mix under a separate Harness task. No unauthorized cloning of content or voices.
5. Run identical metrics on the candidate and compare candidate-minus-reference deltas, with method- and source-bound receipts.
6. Perform blinded human listening and visual/editorial review. Automated metrics are supporting evidence, not an aesthetic PASS.
7. Send the reviewed outcome to the existing Harness learning reducer via an authorized operation. The reverse-engineering module itself never writes memory, promotes commits or publishes.

Example (requires an **already issued** Harness authorization; not a way to create one):

    python scripts/br_reverse_engineering_harness.py \
      --authorization-id EXISTING_HARNESS_AUTH_ID \
      --mode media --input /authorized/reference.mp4 --rights owned \
      --goal "Create an original 20-25 minute BR no GTA episode" \
      --candidate /authorized/original.mp4 --candidate-rights owned \
      --output /private/new-evidence.json

For REA static JavaScript, use mode rea-js, an authorized directory and the private pinned REA installation prefix BR_REA_INSTALL_PREFIX. Never use unpinned latest.

## Professional gaps not represented as passed

- BR_OWNER_V1 speech: forced alignment, F0/prosody/tempo, perceptual naturalness, matched authorized-voice similarity and human MOS; only inside the private clone boundary. The correction Vice City = “vaicy siti” is immutable while studying general techniques.
- Audio production: DAW/Reaper stem routing, objective intelligibility, spectral/phase measurement, human mix/master approval and target-platform compliance. EBU R128 broadcast -23 LUFS is not automatically a YouTube master target.
- Video/animation: optical flow, motion/camera tracking, semantic shot segmentation, original animation continuity and visual quality. VMAF needs a *matched* source; it does not score originality.
- Editorial: grounded claim verification, narrative causal coherence, novelty scoring and human expert critique. Subtitle metrics cannot assert these.
- Operational: private-source workflow with explicit retention and rights policy, workload-bound CPU budgets, security review, professional reference benchmarking, real complete episode and independent approval.

Sources: REA https://github.com/morluto/rea ; FFmpeg https://ffmpeg.org/ffmpeg-filters.html ; EBU R128 https://tech.ebu.ch/publications/r128 ; Netflix VMAF https://github.com/Netflix/vmaf .

## Validation

The focused GitHub Actions job installs pinned REA 6.0.0 and FFmpeg on a clean runner, generates actual owned source/candidate media, creates a sample original JavaScript app, gets persisted Harness test authorization, runs both live CapabilityAdapter routes, and checks evidence without publication or self-approval.

This branch is not the canonical product. It must pass test/CI/security/owner promotion gates. Nothing here touches the active Telegram gateway, Owner Voice audition or production.
