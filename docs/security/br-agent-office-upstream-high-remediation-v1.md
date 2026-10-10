# BR-no-GTA — Agent Office Munder HIGH remediation candidate (review required)

**Date:** 2026-10-10. **Scope:** BR-no-GTA only. **Branch:** `work/br-agent-office-upstream-high-triage-v1`. **Status:** reproducible **research candidate** with clean npm audit and Node typecheck; **Agent Office runtime admission remains BLOCKED** pending independent review.

## Provenance and root cause

The preserved upstream is `https://github.com/chaitanyagiri/munder-difflin` at commit `6248293a7cd9dfdbf9633d12bbe857831ccfee88`, tree `7c531d662beac46af3a6c9f1c2176135b5628b3c`, original package-lock SHA-256 `18ed0753b21d742a03d79161c2b0b3c9f8ccd7d47d663d30e8cd3eacbabe580b`. The current GitHub upstream may redirect ownership; the source identity is proved by exact commit, tree and lock hashes, **not** by the repository display name alone.

The first observed [Agent Office failure](https://github.com/zenindiones-maker/BR-no-GTA/actions/runs/38079584846) was caused by new HIGH audit drift. The original pinned `package-lock.json` contains the following dependency chain:

- `@openai/agents-core` (optional) -> `@modelcontextprotocol/sdk@1.29.0`.
- **`tunnelmole@2.4.0` -> `@types/jest@29.5.14` -> `expect@29.7.0` -> `jest-message-util@29.7.0` -> `micromatch@4.0.8` -> `braces@3.0.3`.**
- `localtunnel@2.0.2` -> `axios@0.21.4`; `tunnelmole` also imports `toml` and other packages.

The BR-specific source policy in `integrations/munder_difflin/config/policy.json` explicitly sets `slack_trigger=false`, `webhook_trigger=false`, `autonomous_scheduling=false`, `secret_persistence=false` and `authority=DELEGATED_ONLY`. The **upstream** `src/main/webhook.ts` and `src/main/slack.ts` dynamically import `tunnelmole` for external ingress. These external tunnel features have no authorized function in the BR coordinator. Upstream's raw lock also carried a **current CRITICAL** issue involving `proxy-addr@2.0.7`; the preexisting BR ephemeral patch already attempted to pin `proxy-addr@2.0.8`. Do not confuse the raw pinned baseline with the separately patched Agent Office runtime.

## Exact research correction — temporary files only

1. Fetch original pinned commit in `$RUNNER_TEMP`, verify git commit, tree and original package-lock hash; never modify the original source checkout or the BR repository.
2. On a **separate disposable copy**, verify the existing BR policy still prohibits Slack and webhook triggers. Replace exactly the two dynamic tunnel methods with unconditional explicit `BR_AGENT_OFFICE_TUNNEL_DISABLED_BY_POLICY` errors (not mocks, not substitute transports).
3. Remove **only** direct npm dependencies `tunnelmole` and `localtunnel`; regenerate the ephemeral lock with `--ignore-scripts`, retain existing exact `proxy-addr@2.0.8` override, run non-force npm audit lock repair for remaining compatible dependencies.
4. Independently run `npm audit --omit=dev --json`, require `high=0` and `critical=0` with no missing/malformed audit result, then run real `npm ci --ignore-scripts` and `npm run typecheck:node`. **No Agent Office service, webhook listener, tunnelling daemon, external LLM, shell agent or paid API is started.**

Changes:
- `scripts/br_agent_office_upstream_high_triage.py`
- `scripts/br_agent_office_tunnel_removal_candidate.py`
- `integrations/munder_difflin/agent_office_ephemeral_no_tunnel_candidate_v1.sh`
- `.github/workflows/br-agent-office-upstream-high-triage.yml`

## Real CI evidence

- [Run 38086530895](https://github.com/zenindiones-maker/BR-no-GTA/actions/runs/38086530895) compared raw pin to ordinary non-force npm lock repair. The simple repair left nine HIGH packages. First baseline audit reported one CRITICAL on the raw pin; this is **not** proof the old BR patched runtime had that same CRITICAL.
- [Run 38086718968](https://github.com/zenindiones-maker/BR-no-GTA/actions/runs/38086718968) confirmed a **disposable** no-tunnel variant: `CANDIDATE_HIGH_PACKAGES=` (empty), `CANDIDATE_CRITICAL_COUNT=0`, `BR_AGENT_OFFICE_NO_TUNNEL_NODE_TYPECHECK=PASS`.
- **[Run 38086829285](https://github.com/zenindiones-maker/BR-no-GTA/actions/runs/38086829285) SUCCESS**, script at candidate commit `156d123e8896619afb6c2aef141c1f9f2077c6f9`: `BR_AGENT_OFFICE_CANDIDATE_HIGH=0`, `BR_AGENT_OFFICE_CANDIDATE_CRITICAL=0`, `BR_AGENT_OFFICE_PINNED_NO_TUNNEL_TYPECHECK=PASS`, `BR_AGENT_OFFICE_CANONICAL_SOURCE_UNCHANGED=TRUE`, and `BR_AGENT_OFFICE_RUNTIME_ADMISSION=BLOCKED_INDEPENDENT_REVIEW`.
- The SHA-256 evidence receipt for the no-tunnel candidate's source-integrity/audit comparison is `23c61c74b0c7124adac947d7c9d363a61c280b0ba46834d83fc9603f05aff8be`. Workflow artifact includes the non-approved candidate lockfile; do not copy it into production without review.

## Independent reviewer requirements before using in operational Agent Office

- Check the **actual** advisory IDs, all transitive dependency changes and the exact candidate lockfile. Confirm npm registry integrity and no new risky packages.
- Confirm no surviving dynamically imported tunnel, webhook or Slack external ingress path and no permit expansion in the DeepSeek Harness authority/capability registry.
- Review all side effects and third-party code changed by the two tunnel-denial methods; verify focused Agent Office integration tests and production build after pin reconciliation.
- Independently authorize a versioned **ephemeral BR-only** security patch based on this candidate; do not replace upstream pinned sources in Git or edit the historic allowlist to silence failing security CI.
- Check with the existing integration against real Harness, agent contracts, secure runtime sandbox, network egress policy and durable persistence. Real Agent Office activation remains **not proven and not authorized**.

## Primary security references

- [npm audit documentation](https://docs.npmjs.com/cli/npm-audit/) explains `npm audit fix` remediation and the need for manual review.
- [npm package overrides](https://docs.npmjs.com/cli/v11/configuring-npm/package-json#overrides) explains root-level transitive overrides.
- [GitHub Actions security](https://docs.github.com/en/actions/reference/security/secure-use) supports full-SHA Actions, least-privilege permissions and non-persisted credentials.
- [GitHub Advisory GHSA-345p-7cg4-v4c7](https://github.com/advisories/GHSA-345p-7cg4-v4c7) illustrates that MCP SDK advisory exposure depends on version and transport behavior. Do not infer applicability without matching the candidate npm audit and code path.

**No promotion attempted, no canary loop, no patch applied to existing running Codespace, no Hazewave modification and no processing on A15.**
