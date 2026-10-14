# PS5 Reverse-Engineering Research: AnyPS5

**Status:** research record only — not integrated into BR-no-GTA runtime.  
**Research branch:** `work/ps5-anyps5-research-v1`

## Primary project

- Repository: https://github.com/boykopovar/AnyPS5
- License shown by the upstream repository: GPL-2.0
- Stated goal: port PS5 executables to native Linux/Windows formats using a relinker and implementations of system libraries, without a separate emulation runtime.
- Reported technical areas: executable relinking, system-library coverage, and GPU shader translation/coverage.

## What the reported percentages do and do not establish

The upstream status page has reported separate coverage figures for system libraries and shader instructions. These are project-specific implementation metrics; they do **not** establish that the same percentage of commercial games works, nor do they prove full PS5 compatibility. A shader instruction being recognized is not equivalent to proving correct translation and execution in every game.

Treat performance and compatibility claims as unverified until a reproducible test records:
- exact upstream commit and build instructions;
- host OS, CPU, GPU, driver, and Vulkan support;
- game name/version and lawful source of test assets;
- launch result, logs, rendering correctness, and frame-time evidence.

## Distinguish this from a console jailbreak

AnyPS5 is primarily a PC-side executable portability effort. It is not itself the same thing as a PS5 jailbreak.

Separate project to track, only if needed: https://github.com/soniciso1/relapse  
Relapse is associated with console-side exploit/jailbreak research. Do not treat its firmware compatibility or payload support as a capability of AnyPS5; verify those claims directly against upstream release notes and code before acting.

## Integration boundary

This repository is primarily the BR-no-GTA project. Keep this PS5 research isolated from GTA production pipelines:
- no AnyPS5 or Relapse code copied into production modules;
- no changes to BR-no-GTA runtime, dependencies, CI, or release workflows;
- no firmware flashing, console modification, or game execution implied by this documentation;
- upstream source remains authoritative; this file is a research index, not a fork or vendored copy.

Before vendoring or modifying upstream code, review the exact upstream license text, notices, dependencies, and redistribution obligations. GPL-2.0 should not be assumed to mean that arbitrary copying into this repository is obligation-free.

## Research checklist

- [ ] Record the upstream commit SHA and release/tag reviewed.
- [ ] Read upstream README, build instructions, architecture, and known limitations.
- [ ] Confirm the precise meaning and date of any reported coverage percentages.
- [ ] Reproduce at least one upstream-documented test on compatible hardware.
- [ ] Store logs and environment details as evidence; label untested claims as unverified.
- [ ] Reassess whether this belongs in a separate dedicated repository before adding executable code.

## Current assessment

**Classification:** experimental PS5-to-PC portability research.  
**Maturity:** not demonstrated here as a general-purpose PS5 emulator or broad commercial-game compatibility layer.  
**Next safe step:** inspect upstream code and record a pinned commit plus reproducible build/test evidence.