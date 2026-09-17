# Munder Difflin upstream boundary

MUNDER_UPSTREAM_REPOSITORY=https://github.com/chaitanyagiri/munder-difflin

MUNDER_UPSTREAM_COMMIT=6248293a7cd9dfdbf9633d12bbe857831ccfee88

MUNDER_UPSTREAM_VERSION=0.4.6 (the pinned commit describes itself as `v0.5.2-52-g6248293a`; `package.json` remains authoritative for the package version)

MUNDER_LICENSE=MIT for source code. Bundled pixel-art assets have a separate license and are not copied into BR-no-GTA.

## Integration decision

The upstream `src/main/hive.ts` says its Hive runtime runs inside the Electron main process. BR-no-GTA therefore does not install Electron/Pixi/xterm in production and does not vendor upstream assets. The cloud adapter implements the smallest stable headless boundary needed for bounded tasks while preserving the pinned upstream concepts:

- coordinator plus workers;
- per-agent inbox/outbox mission mail;
- isolated git worktrees;
- bounded parallel execution;
- aggregated evidence returned to the caller.

The upstream source is checked out only at the exact lock commit during validation. `npm ci --ignore-scripts` is used because the Electron/native `postinstall` is unnecessary for this headless integration.

## Authority boundary

The upstream GOD/Michael role is renamed at the BR boundary to `AGENT_OFFICE_COORDINATOR` with `AUTHORITY=DELEGATED_ONLY`. It cannot authorize itself, create global Goals, schedule work, publish, mutate secrets, or replace the Knowledge Brain. Mission memory is disposable working state; only sanitized result/evidence may return to the DeepSeek Harness.

Primary sources:

- https://github.com/chaitanyagiri/munder-difflin/tree/6248293a7cd9dfdbf9633d12bbe857831ccfee88
- https://github.com/chaitanyagiri/munder-difflin/blob/6248293a7cd9dfdbf9633d12bbe857831ccfee88/src/main/hive.ts
- https://github.com/chaitanyagiri/munder-difflin/blob/6248293a7cd9dfdbf9633d12bbe857831ccfee88/src/main/git.ts
- https://github.com/chaitanyagiri/munder-difflin/blob/6248293a7cd9dfdbf9633d12bbe857831ccfee88/LICENSE

## Supply-chain review

`npm audit --omit=dev --audit-level=high` on 2026-09-16 reported high findings in upstream `axios`/`localtunnel` and `toml`/`tunnelmole`, plus moderate `hono` findings. They are not reachable from BR-no-GTA: no upstream package or Electron runtime is shipped or imported, install scripts are disabled, and CI performs typechecking only. Forced remediation would introduce breaking upstream changes and was not applied. Re-review by 2026-10-16 or before enabling any upstream JavaScript at runtime, whichever comes first.
