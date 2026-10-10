# BR-no-GTA — ARTEX inert-source admission / first code audit

**Scope:** BR-no-GTA only. **Authority:** DeepSeek Harness. **Branch:** `work/br-artex-source-isolated-v1`. **Status:** source staged and verified by owner in the existing Codespace; ARTEX runtime and Harness binding **NOT INSTALLED**.

## Source pin and evidence

- Quarantine upstream mirror: `https://github.com/Hinln/ARTEX.git`; original `Autumn-27/ARTEX` repository was removed from GitHub. The mirror claims version 0.3.15 and preserved original history, but original-author authenticity is **UNVERIFIED**.
- Pinned source commit: `f3e3f54b6c93916388a0a3dc6a439893a9abe37a`.
- Pinned source Git tree: `1c1776fea9e1f43810cb40873932a5f42c202482`.
- Owner's Codespace staging + verify reported `ARTEX_SOURCE_STAGING=PASS` on the initial installer commit `52fc71ac02b823f838fcaa7f92960243a82d13af`; runtime and Harness binding remained absent.
- **Hardening:** prior receipt-only verification could be forged by replacing both the file and its local receipt. On development commit `54346feaf00a9989721bd9f7c00c5f12a83072d4`, verification recomputes a Git tree object ID from file bytes, with upstream executable mode reconstruction, and compares it to the immutable tree constant. Old quarantines are preserved. New tests cover forged receipts, extra files, executable files, synthetic `git write-tree` equivalence, and unauthorized environments.
- CI run [38075177116](https://github.com/zenindiones-maker/BR-no-GTA/actions/runs/38075177116): 10 tests PASS + unauthorized-runner denial PASS. This is NOT an ARTEX runtime E2E or a complete third-party security audit.

## Archive-equivalence correction (10 October 2026)

The existing source snapshot passed the initial receipt-only verifier in the owner's Codespace but the upgraded verifier at `30827beae3c8029a28d373c2cba8eca744ffb121` returned `source tree differs from pinned upstream Git tree`. This was an **archive-normalization false positive**, not proof of modified source:

- The upstream `.gitattributes` at pinned commit specifies `*.bat text eol=crlf`. Git's `archive` writes CRLF in `start.bat` whereas its Git blob is LF-normalized.
- The original upgraded verifier attempted to hash archived bytes as raw Git blobs without reversing this declared transformation.
- The corrected `_git_tree_oid` reverses only the pinned `*.bat` end-of-line conversion before computing the Git blob/tree IDs. It retains byte-for-byte manifest verification and refuses unrelated modifications.
- The synthetic regression test proves `git archive` conversion, tree equivalence and detection of modified batch-file content.
- **Independent live check:** [GitHub Actions 38077293643](https://github.com/zenindiones-maker/BR-no-GTA/actions/runs/38077293643) fetched the **actual pinned upstream commit**, extracted the real Git archive without running any ARTEX code, and independently reported `ARTEX_PINNED_ARCHIVE_REAL_TREE=PASS`; 11 synthetic/adversarial tests PASS and unauthorized-runner admission DENIED.
- **Not yet proved:** the owner's previously staged Codespace directory has not been rechecked with the corrected verifier. Preserve it; never delete or restage on mismatch.

This fixes the false positive in research source verification, **not** ARTEX's supply-chain authenticity, operational safety, runtime functionality or Harness integration.

## Codespace verification — 10 October 2026

The operator verified the **existing**, previously staged ARTEX directory with the corrected verifier at BR-no-GTA research revision `c3f65e9ce69d5f523bb0e1a4f05444b0661acd78` in Codespace `br-v23-recovery-gxp67g5g7wphwxjw`, without rerunning upstream installers:

```text
ARTEX_SOURCE_STAGING=PASS
ARTEX_SOURCE_COMMIT=f3e3f54b6c93916388a0a3dc6a439893a9abe37a
ARTEX_RUNTIME=NOT_INSTALLED
ARTEX_HARNESS_BINDING=NONE
ARTEX_HARDENED_SOURCE_VERIFY=PASS
```

The source directory is verified against the immutable upstream Git tree. The isolated research worktree was fast-forwarded/detached to the audited BR verifier revision; the Chrome DevTools working branch was not modified. This is **inert source integrity only**: upstream authorship, dependency integrity, ARTEX execution, security isolation, Harness authorization/binding, and real E2E are **not** established. No additional staging, installation or remote command is necessary to re-prove this milestone.

## Source-level findings / gap map

| ID | Severity | Finding and code evidence | Status |
| --- | --- | --- | --- |
| ARTEX-001 | HIGH | Original repository no longer accessible; `Hinln/ARTEX` is a third-party mirror. Commit hash does not establish original-author authenticity. | BLOCKED pending provenance review |
| ARTEX-002 | HIGH | `agent/toolcatalog.go` identifies the default Norma SDK tools `Bash`, `Read`, `Write`, and `Edit` as generally available to agents. Tool resolution may pass tools that have no DB row, so ARTEX's DB catalog is **not** an adequate Harness authority boundary. | OPEN; never mount inside BR Harness |
| ARTEX-003 | HIGH | `install.sh` offers `curl -fsSL https://get.docker.com | sh`, Docker Compose `up -d`, PostgreSQL, and LLM credential prompts. Executing it would violate resource/credential/external-runtime boundaries in the current Codespace. | BLOCKED; do not execute |
| ARTEX-004 | HIGH | `cmd/artex/main.go` defaults HTTP listener to `:8787` and starts a traffic proxy on `127.0.0.1:8788`. `server/server.go` exposes the HTTP API and JWT logic. An unreviewed server must not be started or forwarded to internet. | BLOCKED |
| ARTEX-005 | HIGH | `agent/planner.go` creates an independent intent producer, and `agent/worker.go` executes work with real tools. BR-no-GTA requires its own DeepSeek Harness to remain the single authority. | OPEN; only read-only research patterns may transfer |
| ARTEX-006 | MEDIUM | `README.md` and `LICENSE` specify AGPL-3.0; README also states restrictions for non-offensive local research. License compatibility/other author statements require review before copying or linking source. | OPEN |
| ARTEX-007 | MEDIUM | `go.mod` uses `github.com/Autumn-27/norma v0.4.3` and multiple network/proxy dependencies; no independent dependency review, Go build, or package SBOM performed. | OPEN |
| ARTEX-008 | MEDIUM | Source integrity and CRLF-export mismatch corrected; Git tree verification passed in live upstream-archive CI and in the owner's existing Codespace snapshot. | FIXED for SOURCE INTEGRITY; runtime remains NOT INSTALLED |

## Admission decision

**Source study only.** Do not run `install.sh`, `start.sh`, `update.sh`, `docker compose`, `go run`, any exposed service, agent loop, MITM proxy, shell executor, self-updater, or LLM credential setup. Do not forward ports or grant ARTEX the Codespace's inherited credentials. Do not copy ARTEX files into the BR runtime, registry or existing REA without a separate review.

A possible future BR-native adaptation is a read-only, typed **evidence-graph research sensor** that computes asset/provenance relationships from authorized local artifacts and returns proposed observations (not instructions). It must consume a fresh Harness authorization, remain network-disabled and write-disabled, and produce independently checkable read-only receipts. This does not mean ARTEX itself is authorized or installed as a BR executor.

## Next acceptance gate (on the EXISTING remote Codespace, not the A15)

1. Confirm the primary worktree has no WIP and the ARTEX worktree remains clean.
2. Fast-forward/detach the ARTEX research worktree at the **reviewed** current branch commit; never reset the primary Chrome MCP worktree.
3. Run `python3 scripts/br_artex_source_quarantine.py verify` against the existing staged source. This recomputes the pinned Git tree, without executing ARTEX or downloading the mirror again.
4. Record the exact stdout, source tree, checkout SHA and any failure, then begin the dependency and licensing review. If source differs, report `BLOCKED` and preserve files as evidence; do not delete or overwrite.
5. Source PASS is not a GO for runtime. Runtime integration would require independently reviewed permissions, network-denied test isolation, cost policy, negative tests and real Harness E2E before promotion.

**Invariants:** no modification of main, Chrome DevTools, Owner Voice, Hazewave, A15 processing, and no new Codespace/paid service.
