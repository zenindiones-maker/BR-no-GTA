# BR-no-GTA — repository agent map

DeepSeek Harness is sole authority and reducer. Workers, GTA6 Brain, Hermes,
Agent Office, providers, tools and Skills are subordinate executors. A worker
may act only through a fresh Harness authorization and the bound task contract.

## Stable execution map

Human goal → DeepSeek Harness → typed atomic task → capability eligibility →
TaskExecutionBlueprint → bounded worker/environment → TaskResultEnvelope →
independent review when required → Harness reducer → durable mission state.

Multi-agent execution is not the default. Use task topology evidence. Sequential
or conflicting work uses no fanout. Mutating work requires an isolated Sprite or
git worktree; independent review is read-only and cannot mutate the candidate.

Skills have authority=NONE. They may refine procedure but cannot expand read,
write, tool or side-effect scope, publish, change mission state, write canonical
memory, or promote themselves.

Never expose secrets, login/device material, raw credentials, or private prompt
contents in repository artifacts, GitHub logs, Telegram review groups or traces.
OpenAI Platform API spend is forbidden unless the owner explicitly changes that
policy; Codex ChatGPT-subscription execution must not fall back to paid API.

## Canonical references

Required: `docs/operations/system-operational-readiness.html`
Required: `app/services/global_capability_registry.py`
Required: `app/services/harness_authorization_service.py`
Required: `app/services/task_execution_foundation_service.py`
See: `docs/architecture/br-no-gta-professionalization-master-plan-v1.md`
Required for long-running development: `docs/architecture/development-continuity-recovery-plane-v1.md`
See: `docs/agent-execution/gta6-agent-domain-guidance.md`
See: `docs/superpowers/specs/2026-09-28-agent-skills-pack-design.md`

The detailed GTA6 research/editorial/production guidance is versioned in the
referenced domain document rather than duplicated here. Repository contracts
and versioned policy override stale prose. Fail closed on conflicting authority
instructions or broken mandatory references.

## Required versioned safety boundaries

Required: `docs/governance/agents-versioned-safety-boundaries-v1.md`
Required: `docs/architecture/br-v24-existing-swarm-slm-transfer.md`
Required: `docs/governance/source-of-truth.md`
Required: `docs/governance/v24-required-status-checks.md`
All V11/V13/V17 voice/production restrictions, A15 remote-control-only policy,
BR-native REA continuity and V24 existing-swarm gates remain mandatory through
this versioned document. No promotion, auto-training or release by implication.
