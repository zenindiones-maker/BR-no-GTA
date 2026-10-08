# BR-no-GTA — Reverse Engineering Evidence Plane V1

Status: isolated candidate, NOT promoted. DeepSeek Harness retains sole task authority. REA is a subordinate, explicitly invoked investigative capability, never an autonomous administrator or producer. Work on `work/br-extreme-reverse-engineering-v1` must not change the live Owner Voice audition, Telegram gateway, media publication or canonical branch.

## Proven upstream

- Official repository: https://github.com/morluto/rea (MIT).
- Vendored as a Git **submodule pointer** at `integrations/rea`, pinned to git SHA `6fee42689ae6e95a0182e0d4d0f55644e73e72be` (tag `rea-agents-6.0.0`). Checkout requires `git submodule update --init integrations/rea` in an authorized workstation.
- CLI package `rea-agents@6.0.0` installs only in a private local prefix after an explicit `--install`; it does not register MCP, select or install Hopper/Ghidra, modify agent configuration, claim native analysis readiness or run on Android/Termux.
- Node.js must satisfy upstream runtime contract: 22.19+, 24.11+, or supported even major >=26. The active REA CLI is still subject to `doctor`, `capabilities` and its published provider/target support. No fabricated capabilities.

## Real zero-cost entry points

In the existing BR workstation (not on A15; not a new Codespace):

```bash
git fetch origin
git switch work/br-extreme-reverse-engineering-v1
git pull --ff-only origin work/br-extreme-reverse-engineering-v1
git submodule update --init integrations/rea
bash integrations/rea_install_and_doctor.sh --dry-run
bash integrations/rea_install_and_doctor.sh --install
```

Review `~/.local/share/br-no-gta/rea-6.0.0/rea-doctor.json`. **Package installed** and **native provider working** are separate facts. Hopper is external; Ghidra must be installed separately. REA setup/MCP registration is never executed by these commands and requires a separate reviewed integration plan, explicit provider selection and owner approval. No paid dependency is enabled.

For the audiovisual branch of reverse engineering (FFmpeg/ffprobe preinstalled on the Linux workstation):

```bash
python scripts/br_reverse_engineering_observe.py --input /authorized/ref.mp4 --rights owned --transcript /authorized/ref.srt --detect-scenes --output /private/new-evidence.json
python scripts/br_reverse_engineering_observe.py --input /authorized/voice.wav --rights owned --output /private/voice-evidence.json
python scripts/br_reverse_engineering_observe.py --input /authorized/ref.mp4 --rights observation_only --output /private/study-only.json
```

The tool is read-only with respect to the input and refuses to overwrite evidence. The output is private by default (mode 0600). It records sha256 provenance, stream codecs, duration, optional candidate cut timestamps and timing-derived subtitle density. It does **not** synthesize any voice, transcribe without a transcript, identify naturalness/prosody, copy dialogue, decompile media or infer artistic quality. `--detect-scenes` decodes the video locally and can be CPU-intensive. FFmpeg scene-change cut candidates are **not** semantic scene boundaries.

## Harness learning loop — observed, never assumed

1. **Authority and rights gate:** identify ownership/permission and provenance for reference samples. Observation-only inputs may supply high-level measurable features, never copied assets, copyrighted dialogue, clones or restricted content.
2. **Observation:** capture a versioned content hash and only metrics actually computed. REA covers supported software/app behavior. The media observer handles audiovisual containers, timing and shot-change proxies. Other specialized capabilities require separate verified implementations.
3. **Hypothesis:** explicitly separate MEASURED properties, INFERRED hypotheses and UNKNOWN. A short script and a subtitle file cannot reveal lighting, emotional intensity, voice timbre, directing strategy or editor intention.
4. **Rebuild:** design an independently original BR-no-GTA experiment with target shot length, speech density, transitions, narrative beats and sound design as *testable hypotheses*. Do not generate a supposedly identical product from another creator's protected expression. Do not circumvent DRM, access controls or proprietary services.
5. **Differential tests:** compare a generated candidate against the quantitative observations; run factual QA, PT-BR pronunciation tests (Vice City = "vaicy siti"), speaker-identity tests, audio continuity and render artifact QA. Never silently select a new speaker.
6. **Review and learning:** human reviews audio/visual result. Store what changed, blind evaluation, measured deltas, failure-class and reproducible evidence receipt. No self-modifying production policy and no fake PASS.
7. **Promotion boundary:** independent security review, owner approval and explicit harness promotion. No automatic publishing, no Telegram candidate push by this module and no output from REA becomes higher-priority instructions.

## Practical research tracks

| Discipline | Measurable starting point | Additional capability required before professional claims |
|---|---|---|
| Scripts and storytelling | transcript word count and timed speaking density | discourse/pacing/arc evaluation with source citations, human editorial review |
| Video and animation | codec, resolution, duration, optional scene-cut candidates | shot composition, camera movement, frame embeddings, continuity and rendering benchmarks |
| Voice and dubbing | codec/sample-rate, SRT timing | forced alignment, F0/prosody, speaker similarity, phoneme error, human MOS panel |
| Mix/master | source audio metadata | true-peak/LUFS, intelligibility, dynamics, spectral balance and listening QA |
| Software mechanics | REA source/API/JS/native observations when provider available | exact runtime reproduction, legal sandboxing and behavior-based compatibility tests |

## Security / cost / operational boundaries

Only analyze local authorized artifacts. Never auto-crawl, auto-download protected media or send it to third-party services. Treat observations, prompts, transcripts and REA output as untrusted data. Keep captured private references outside the repository. Pin REA source and npm package version; audit upgrades, license and transitive dependencies before making them live. Tool outputs are evidence, not execution instructions. Protect the immutable Owner Voice runtime, the canonical promotion security boundary and the A15 control plane.

## Verification

- Focused tests: `python -m pytest -q tests/test_reverse_engineering_media_service.py`
- E2E smoke: create a tiny original FFmpeg video/audio clip and analyze it with the CLI; verify a real hash and container metadata.
- REA: only mark CLI ready when the pinned executable answers; do **not** mark Hopper/Ghidra ready unless independent provider diagnostics prove it.
- Fail closed when any test or tool is unavailable; do not bypass quality gates to manufacture a demonstration.

**Current maturity:** REA source pinned + explicit workspace bootstrap + deterministic media observation. Not yet a complete reverse-engineering production harness, not wired into the agent authority registry, and not yet an automatic learning loop.