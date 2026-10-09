# BR V24 — protected integration ruleset installation and readback

Status: administrator action pending. This document is an installation
specification, **not evidence that a GitHub ruleset exists or is active**.

Repository: `zenindiones-maker/BR-no-GTA`
Target branch (exact): `refs/heads/work/br-slm-agent-reconstruction-v24`
Do not modify the pre-existing `main` or `work/gate6f-analytics-learning`
rulesets, canonical promotion workflow or protected environments.

## Required GitHub repository branch ruleset

Settings → Rules → Rulesets → New branch ruleset.

- Name: `BR V24 governed development acceptance`
- Enforcement: **Active**
- Target: Include exactly `work/br-slm-agent-reconstruction-v24`; exclude
  unrelated development, security staging and canonical refs.
- Bypass: **none**; do not allow admins or workflows to bypass by default.
- Require a pull request before merging; block force pushes and deletions.
- Require status checks before merging, bound to **GitHub Actions** as
  expected check source when selectable. Require these **exact job names**:
  `Fast Feedback`, `Final Gate`, `CodeQL exact SHA`.
- Prefer requiring up-to-date branch before merging (strict mode). Never
  require optional conditional `Frontend Build Check` directly; it is
  included fail-closed inside `Fast Feedback`.
- Preserve independent reviewer/human owner approval procedures outside
  GitHub if a required approving reviewer cannot be configured without
  deadlocking this single-owner repository. Do not claim code scanning alone
  is an independent human security review.

## Readback and acceptance

Fetch `GET /repos/zenindiones-maker/BR-no-GTA/rulesets` and GET the new
ruleset ID. Confirm `enforcement=active`, exact target ref in
`conditions.ref_name.include`, no bypass actors, `pull_request`,
`deletion`, `non_fast_forward` and the exact three required status contexts
with the expected GitHub Actions app identity.

Inspect PR #20 head SHA, its check runs and the latest GitHub Actions
conclusions. A successful prior SHA or a `skipped` job is not evidence
for the candidate head. Keep PR as DRAFT and do not merge until human
approval, full tests and CodeQL are verified. After ruleset creation,
retrigger checks through a legitimate new commit/reopen if GitHub requires.

GitHub Actions `contents:read` permissions must remain least privilege.
A current ChatGPT GitHub App session without repository administration
cannot create or activate a ruleset; a separate authorized admin action
and remote readback are required. Do not try to replace that with a
write-capable temporary personal access token or an unreviewed executor.
