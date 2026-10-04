# BR-1 Pilot Finding Set

**Schema:** PilotFindingSet/v1  
**Repository:** `zenindiones-maker/BR-no-GTA`  
**Audited branch:** `work/gate6f-analytics-learning`  
**Audited HEAD:** `c8b9f2275e5288e5c4cefe9474075d21ca1023f0`  
**Status:** IN PROGRESS  
**Finding budget:** 10 total / 6 remaining

This document is a durable audit ledger. A finding marked **LOCKED** is accepted into BR-1 but is not considered remediated or closed.

## Locked findings

### BR-1-F001 — HIGH
**Category:** Architecture / Coupling / Deployment Isolation  
**Title:** Telegram runtime deployment is coupled to the mutable development worktree

The Telegram runtime deployment path depends on the mutable development checkout, allowing legitimate development state to block canonical convergence and automatic recovery.

**Boundary violated:** deployment/runtime convergence and availability isolation.

### BR-1-F002 — MEDIUM
**Category:** Authority / Plane Isolation / Noncanonical Execution  
**Title:** Restored non-canonical Development Recovery content can cross into the credential-bearing Telegram runtime through the shared development ROOT

Development Recovery correctly prevents `recovery/dev/**` from directly triggering deployment, but `restore()` can materialize non-canonical source into the same mutable ROOT from which Telegram `start`, `restart`, and `foreground` execute.

**Boundary violated:** non-canonical recovery material can cross into a credential-bearing runtime.

### BR-1-F003 — HIGH
**Category:** Integrity / TOCTOU / Secret Boundary  
**Evidence class:** OBSERVED  
**Confidence:** HIGH

**Title:** Development Recovery scans and digests live worktree bytes before staging potentially different bytes, allowing a DURABLE recovery tree to diverge from `content_digest` and bypass the recovery secret-scan boundary

`persist()` performs path/secret scanning and `content_digest` computation through separate reads of the mutable worktree, then later stages those paths into a temporary Git index without freezing the byte set or revalidating the staged blobs. A mutation between those phases can therefore cause the recovery tree to contain bytes different from those represented by the recorded `content_digest`.

Because recovery-path secret scanning occurs only during the earlier read and is not repeated against the exact staged blobs or resulting tree, secret-like content introduced during that window can bypass that barrier and be included in the recovery commit while remote tree readback still succeeds and the checkpoint reaches `DURABLE`.

**Required remediation invariant:**

`SCANNED_BYTES == DIGESTED_BYTES == COMMITTED_TREE_BYTES == REMOTE_READBACK_BYTES`

**Impact:** integrity impact is HIGH. Potential confidentiality impact is HIGH if secret-like bytes are introduced during the TOCTOU window; that confidentiality consequence remains explicitly qualified until reproduced by a dedicated mutation test.

### BR-1-F004 — MEDIUM
**Category:** Durability / RPO Monitoring / Enforcement  
**Evidence class:** OBSERVED  
**Confidence:** HIGH

**Title:** Development Continuity defines a 300 s RPO target and 600 s hard maximum but has no observed closed-loop monitor enforcing elapsed time since the last verified remote checkpoint

The continuity policy contains correct decision logic for `WATCHDOG` events, including mandatory checkpointing at the 600-second hard maximum, but no runtime component observed in the audited HEAD calculates elapsed time from the last independently verified remote checkpoint, periodically invokes that policy, or alerts/blocks when the hard maximum is exceeded.

The 90-second heartbeat is intentionally liveness-only, so dirty development state can remain beyond the declared RPO hard maximum without automatic detection or enforcement when no qualifying semantic checkpoint event occurs.

**Impact:** loss of recent development progress and violation of the declared durability/RPO guarantee. This finding does not imply unauthorized execution or direct secret exposure.

## Candidate explicitly not opened

**Git-ref interference between Development Continuity and Telegram runtime:** NOT OPENED.

Remote recovery-ref writer fencing remains robust at the audited HEAD: `EXPECTED_PREVIOUS_REMOTE_OID`, non-force push, explicit recovery-ref targeting, and independent remote readback are not shown to be bypassed by the Telegram supervisor.

## Project-isolation note

BR-no-GTA and Hazewave Telegram systems are separate projects. Bot tokens, config roots, state roots, supervisors, deployment roots, recovery state, and authority must remain project-local and must not be treated as shared evidence or infrastructure.

---

This ledger records BR-1 findings only. Presence here does not mean remediation or closure.
