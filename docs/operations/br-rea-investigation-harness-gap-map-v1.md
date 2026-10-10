# BR-no-GTA — real Harness investigator + first-pass system reverse engineering

**Scope:** only `zenindiones-maker/BR-no-GTA`. **Branch:** `work/br-rea-investigation-harness-gate-v1`. **Authority:** DeepSeek Harness (sole). No auto-merge, no publication, no ARTEX runtime, no owner-voice inference, no new Codespace or paid model.

## 1. Ground truth and source provenance

- Base branch: `work/br-artex-source-isolated-v1` at `f6a79759ff3b59745b7ed7b0ebd0b28389b2a89c`. Its ARTEX source quarantine had already passed exact pinned upstream Git-tree verification **on the owner's existing Codespace**, without running ARTEX. This is not an ARTEX operational installation.
- Existing Chrome DevTools branch `work/br-devtools-four-isolated-v1` at observed `a4f3ed02eaa15292b30a8163c2cae1abd2c618fc` remains untouched.
- Historical first-party REA V4 at `ad00c215ecd33ee74703cfeb0d72694220b666f0` includes software/audio/scene/media/HAR research; those services are **not present** in the current recovery branch. Do not copy them blindly.
- **Web research basis:** [GitHub Actions secure use](https://docs.github.com/en/actions/reference/security/secure-use), [OWASP Actions Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/GitHub_Actions_Security_Cheat_Sheet.html), [OASIS STIX 2.1 relationships](https://docs.oasis-open.org/cti/stix/v2.1/stix-v2.1.html), [Python path/descriptor documentation](https://docs.python.org/3/library/os.html#os.open).
- The new route is a **first-party, read-only source evidence sensor** using Python AST (not the foreign ARTEX runtime). Only under persisted DEVELOPMENT authorization from Harness: `reverse-engineering.evidence.inspect`.

## 2. Corrective implementation

1. Added exact capability `reverse-engineering.evidence.inspect` to the sole Global Capability Registry and explicit Harness capability catalog; bound `execute_br_rea_investigation` to the MCP internal dispatcher, with no fallback.
2. Enforced exact persisted outer authorization ID, Harness decision ID, execution ID, and approved Registry callable binding. The executor atomically consumes one active authorization before any file read; second use fails.
3. Implemented read-only first-party Python file inspection with `O_NOFOLLOW` directory-descriptor traversal, AST import relationships and SHA-256 source evidence. Strict file/directory/type/byte-count budgets; no commands, network, source contents, file writes, voice, LLM, GitHub token, or ARTEX runtime. Evidence is canonically hashed.
4. Explicitly denied public `br_capability_execute` requests for this internal capability **before public MCP can mint a grant**. The server implementation guard is committed; direct live public MCP transport denial is not yet demonstrated in the remote Codespace.
5. Added real GitHub Actions execution through the existing Harness router, persisted SQLite, internal MCP capability dispatcher, actual BR source files and canonical result. Adversarial tests cover forged/replayed/revoked/mismatched authorization, wrong executor, path traversal, symlinks, invalid payload, source budgets and content leakage.

## 3. GAP MAP inicial → pós-correção

| ID | Severity | Component and directly observed evidence | Corrective status |
| --- | --- | --- | --- |
| REA-001 | HIGH | Historical native REA V4 services exist at exact SHA but are absent from V23 recovery worktree. Real V23 runtime/compatibility evidence insufficient. | **OPEN** — do not auto-resurrect |
| REA-002 | HIGH | No first-party bound, persisted, one-shot, source-inspection route had been proven in current Harness. | **FIXED FOR CI** — real internal Harness E2E `BR_REA_HARNESS_REAL_E2E=PASS`, existing Codespace host not yet exercised |
| REA-003 | HIGH | ARTEX `planner`/`worker` and shell/MITM runtimes would create a competing authority if imported. | **BLOCKED BY DESIGN** — external ARTEX remains inert; no runtime started |
| REA-004 | HIGH | Public MCP previously self-issued authorizations for generic bounded capabilities; REA inspector requires an independently authenticated internal boundary. | **MITIGATED** by early public block and single-use internal route. Direct public MCP transport test **UNVERIFIED**; issuer credential authenticity for arbitrary internal Python callers remains **OPEN** |
| REA-005 | HIGH | Two actual AST parsing failures: `app/services/owner_voice_dubbing_reference_policy.py`, `tests/test_owner_voice_dubbing_reference_policy.py` had literal `\\n` tokens at syntax boundaries. | **FIXED ON ISOLATED BRANCH**; source compilation and behavioral regressions PASS |
| REA-006 | MEDIUM | Owner-voice candidate admitted boolean timestamps and non-SHA256 digests. | **FIXED** strict integer and digest checks; `BR_OWNER_V1` owner approval and `runtime_activation=False` unchanged |
| REA-007 | MEDIUM | No bounded, repeatable tracked-repository source/workflow inventory. | **FIXED FOR STATIC SCOPE** — enumerates tracked source/workflows and candidate gaps; **NOT** a full application runtime audit |
| REA-008 | HIGH | Native REA V4, real remote Chrome DevTools bridge, BR_OWNER_V1 acoustic approval, Telegram and private YouTube end-to-end not proved by this change. | **OPEN/UNVERIFIED** — separate dedicated acceptance gates |
| REA-009 | HIGH | Third-party ARTEX repository origin is an independently pinned *mirror*, not cryptographically verified original author's source. | **OPEN** provenance/supply-chain review required before any code adoption |

**Do not infer CRITICAL=0/HIGH=0 for the whole system.** The status applies only to a checked slice. Some HIGH findings remain OPEN or UNVERIFIED.

## 4. Evidence and repeatability

- [Real Harness E2E 38078091923](https://github.com/zenindiones-maker/BR-no-GTA/actions/runs/38078091923): 14/14 adversarial tests PASS and `BR_REA_HARNESS_REAL_E2E=PASS`.
- [Real whole tracked-source inventory 38078224574](https://github.com/zenindiones-maker/BR-no-GTA/actions/runs/38078224574): initially 1,941 tracked files, 1,390 parsed Python modules, 4,033 observed internal import references and 193 workflows, with **two actual Python AST parse errors**. This is a static scan, not operational equivalence testing.
- [Post-fix regression 38078344725](https://github.com/zenindiones-maker/BR-no-GTA/actions/runs/38078344725): 14 adversarial, 17 owner voice and 3 inventory tests PASS; 1,392 parsed modules, 4,034 internal import references, 193 workflows; scanner candidate list empty **within its limited checks**; Harness E2E PASS.
- Output includes source evidence SHA-256 and a stable evidence receipt hash; no protected audio or credentials placed in logs.
- The Python `mcp==1.29.1` and `python-dotenv==1.2.3` dependencies were installed on an **ephemeral GitHub Actions runner**, not the user's Codespace or A15. No new paid services or machines created.

**One canonical acceptance command**, executed only inside existing approved BR Codespace with existing dependencies, or inside the bounded CI workflow:

```bash
bash scripts/br_rea_investigation_acceptance.sh
```

The command checks environment/repo and runs actual read-only source tests, Owner Voice reference policy regressions, full tracked-source static inventory, and the real internal Harness E2E. A failed prerequisite must block without fallback. Do not execute it on A15 or in unrelated projects.

## 5. Not a publication or promotion authorization

This does not authorize merging `main`, restoring old REA architecture, ARTEX execution, Owner Voice audio synthesis or approval, Telegram changes, public or private YouTube uploads, paid inference, or creating/deleting Codespaces. Human/independent review requirements remain intact.
