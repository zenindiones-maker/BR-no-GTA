# DeepSeek Harness capability boundary

Checkpoint base: `bfa43170aa9c10eae424cf2b09edf566406d96ae` on
`codex/run-001-app`.

Fresh GitHub Actions evidence at that exact HEAD:

- Agent Tooling Bootstrap `34720715741`: `completed/success`.
- Codex Agent Skills Validation `34720715772`: `completed/success`.
- Higgsfield Tooling Validation `34720715778`: `completed/success`.

The DeepSeek Harness remains the sole authority/control plane. Capability flow is:

`Harness Authority -> Routing/Policy -> Agent/Skill Selection -> Capability Execution -> Evidence/Result -> Harness`

`harness_capability_service.py` is a passive catalogue and policy gate. It does
not own a scheduler, database, publisher, brain, master agent, or autonomous
router. It cannot authorize itself. Every execution request must carry the
Harness-authorized action plus `harness_decision_id` and `execution_id` lineage.

## Progressive discovery

The catalogue registers 28 AVAILABLE capabilities:

- 24 compatible Addy Agent Skills, exposed as `addy:<skill-name>`.
- 4 Higgsfield capabilities: `higgsfield-generate`,
  `higgsfield-youtube-thumbnail`, `higgsfield-brandkit`, and
  `higgsfield-video-explainer`.

`browser-testing-with-devtools` remains excluded until Chrome DevTools MCP is
configured. Discovery requires a non-empty intent, may be constrained by the
Harness-authorized action, returns at most five metadata candidates by default,
and never injects all skill bodies into a prompt. AVAILABLE does not mean ACTIVE.

## Authorization and evidence

The policy gate requires `authority == deepseek_harness`, a non-empty
`harness_decision_id`, a non-empty `execution_id`, an AVAILABLE capability, and
an action allowed by that capability. A capability adapter is invoked only after
those checks pass.

Evidence returned to the Harness contains:

- `capability_id`
- `provider`
- `status` (`READY`, `BLOCKED`, or `EXECUTED`)
- `active`
- `authority`
- `authorized_action`
- `harness_decision_id`
- `execution_id`
- `result` when execution occurred
- `boundary` when execution did not occur

The MCP boundary exposes progressive discovery and the policy/evidence path. It
does not bind external executors itself; composition of an executor remains a
Harness-owned decision.

## Higgsfield authentication boundary

No paid Higgsfield generation is enabled. The versioned tooling review confirms
the official interactive browser flow (`higgsfield auth login`) and does not
establish an officially supported unattended credential mechanism suitable for
an ephemeral runner. No undocumented token/environment variable is assumed.
Consequently all four Higgsfield capabilities are AVAILABLE but
`execution_enabled=False`; policy returns `BLOCKED` before any adapter is called.
Credentials, cookies, device codes, tokens, and account session artifacts must
never be versioned or emitted as CI artifacts.

## RUN-001 freeze

This capability integration does not modify RenderJob, audiovisual workers,
YouTube publication, or Job16. The preserved run `34717863409` remains diagnosed
at the existing `vedit_graphic:title` engine boundary. No Job17 is created and
Job16 is not redispatched by this work.
