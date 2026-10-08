# BR-no-GTA — Harness Capacity Utilization V8

Status: isolated candidate, no promotion. DeepSeek Harness is the sole authority.

## Findings

REA 6.0.0 is installed in ephemeral CI, but the current Harness only uses a scoped static JavaScript analysis route. The REA upstream project supports wider investigation including native, managed and runtime tools where provider dependencies permit. A successful npm install is not proof that optional Ghidra/Hopper, call graphs, runtime debugger, managed inspection or browser tools are operational. A nonzero doctor exit must remain a blocker for any affected provider. Reference: https://github.com/morluto/rea .

Iris 0.4.1 was installed with SHA-256 verification and rendered genuine local HTML screenshots via Chrome in V7. The integration initially omitted full-page capture, dark mode, wait-for selector and selector padding. Upstream also offers batch and persistent MCP camera sessions; the latter are not allowed outside the Harness authority boundary. Reference: https://github.com/brijr/iris .

The global capability registry exposes capability records and executor bindings. These describe advertised intent; they are not a full runtime capability test.

## Changes

1. Enable Iris full-page, dark, wait-for and selector padding for owner-authored trusted static HTML only. Options have strict bounds, no arbitrary URLs, no auto-browser MCP, private images, and existing Harness persisted authorization. CI tests the real Chrome rendering of a 1800px tall fixture and selected element with 24px padding.
2. Add capability_utilization_report to enumerate every registry record, expose executor-declared flags and surface-specific REA/Iris tasks. Runtime proof is deliberately NOT inferred from registration.
3. Audit real pinned REA 6.0.0 discovery commands: capabilities --json, providers --json and doctor --json. Output includes validated structured catalog identifiers, JSON digest and exit status. Doctor failure cannot be promoted to provider readiness. Unknown catalog descriptions, code, machine paths and decompiled text are never written to the report.
4. Write an exclusive private JSON receipt with scripts/br_harness_capability_audit_v8.py. The auditor cannot schedule, reroute, install, spend, promote, write learning or grant permissions.

## Full-system utilization lifecycle

REGISTERED -> INSTALLED -> RUNTIME_AVAILABLE -> ACTUAL_BOUNDED_EXECUTION -> BENCHMARKED -> INDEPENDENTLY_REVIEWED -> PROMOTED.

A state is never proof of the next state. In particular a provider catalog is not an executed native decompiler, a screenshot is not a successful website recreation, and a matching TTS transcript is not BR_OWNER_V1 identity or acoustic correctness.

Each Harness planning pass should discover compatible tools, check authorization, confirm price and runtime availability, select one scoped operation, measure the artifact, classify its failure and request independent evidence before canonical learning. Unknown cost = deny. Only canonical Harness policy may choose and authorize tools.

## Gaps still pending

- REA native Ghidra/Hopper, LLDB, call graphs, managed assembly, Electron sessions and web observation require separately authorized fixture-level provider tests and clean doctor results.
- Iris live public sites, authenticated browsing, batch and MCP require verified network isolation, redirect and subresource restrictions, audit of shell/browser permissions, and explicit owner permission.
- Long-form artistic audiovisual production still needs true owned/licensed case-based quality benchmarks with REAPER/voice/animation/timeline renders and human review.

No modification to BR_OWNER_V1, voice approval, Telegram, YouTube, existing codespaces, billing or canonical branches. Do not mark 100% utilization from registry completeness or passing synthetic CI alone.
