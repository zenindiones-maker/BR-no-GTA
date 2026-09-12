# Codex runner recovery — operational handoff for PR #4

Confirmed run 34647185837 attempt 2 / job 103469589466 failed at
2026-09-12 01:04:25 UTC with SDK RuntimeError: usage limit; retry message 5:45 AM.
Authentication passed. Commit and PR reporting were skipped.
Only device-auth artifacts exist; logs contain file names and diff statistics,
not patch contents. The ephemeral changes cannot be recovered from these records.
PR #4 remains 029da588f090490036fa98398275c97baa04155d.

The cloud-side exporter `.github/scripts/codex_recovery.py` prepares an explicitly
unvalidated patch relative to a supplied starting commit. It includes changed and
untracked Python under app/services and tests only. It excludes authentication
directories, symlinks and detected credential literals. This conservative filter
is not a universal secret scanner: omitted paths require manual review, and no
whole-home, session, environment or raw-log artifact is acceptable.

Required integration in PR #4 before another long run:

1. Provision the reviewed exporter from a pinned cloud commit before starting Codex.
2. Record the checkout HEAD as the recovery base before the task.
3. Give the Codex task a step timeout shorter than the job timeout, leaving time
   for recovery (for example 90 minutes inside the existing 120-minute job).
4. With `if: always()` after the task, invoke the exporter with that base and an
   output under RUNNER_TEMP. Upload ONLY partial.patch and recovery.json using
   a run-ID/attempt-specific artifact name. Never automatically apply or commit it.
5. Remove the existing device-code artifact persistence. Authorization must use
   an approved transient delivery mechanism; never publish device codes, tokens
   or sessions in code artifacts, logs, issues or commits.
6. Restore patches only on their recorded base, review them, run tests, then commit.

Ordinary quota/error and step timeout can reach recovery steps. Hard runner loss
or force cancellation may prevent any post-step execution; this does not promise
recovery from an already destroyed runner. This handoff is not wired into the
app workflow yet and does not justify another run of its unchanged revision.
