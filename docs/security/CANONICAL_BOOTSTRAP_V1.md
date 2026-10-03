# One-time canonical control-plane bootstrap v1

Status: design only. No bootstrap execution or promotion evidence is supplied by
this patch. Security Guardian authority remains NONE. DeepSeek Harness is the
sole promotion authorization authority.

The permanent `.github/workflows/canonical-promotion.yml` is **post-bootstrap
only**. Its canonical-ref guard and trusted canonical validator cannot install
themselves when the old canonical tree lacks them. Dispatching the candidate
workflow is not a bootstrap path.

## Typed contract and evidence

`app/services/canonical_bootstrap_contract.py` defines the structural contracts
`CanonicalBootstrapContract/v1` and `CanonicalBootstrapEvidence/v1`. It is a
specification and local test oracle, not a bootstrap executor. It MUST NOT be
imported or executed from candidate code during bootstrap. Structural equality
alone does not authenticate an authorization, review, check, or remote readback.

Every contract field is mandatory, with no wildcard, default, or abbreviated ID:

| Field | Binding |
| --- | --- |
| `target_ref` | Exactly `refs/heads/work/gate6f-analytics-learning` |
| `expected_old_oid` | Exact 40 lowercase hex canonical commit observed and authorized before installation |
| `candidate_sha` | Exact 40 hex reviewed candidate commit |
| `candidate_tree_sha` | Exact 40 hex tree of that commit |
| `reviewed_diff_sha256` | SHA256 of `git diff --no-ext-diff --no-textconv --binary --full-index OLD CANDIDATE` bytes |
| `security_review_receipt_sha256` | Verified `SecurityReviewReceipt/v1.content_sha256`, recomputed using that schema's canonical serialization |
| `harness_authorization_id` | Fresh persisted Harness DEVELOPMENT authorization for `development.canonical.promote`, bound to this entire contract |
| `required_check_identity` | Repository, workflow path, exact check name, trusted GitHub App ID, run ID, check-run ID and candidate head SHA |
| `bootstrap_executor_sha256` | SHA256 of the separately reviewed, immutable external capsule bytes |
| `promotion_identity` | Existing `BR_CANONICAL_PROMOTION_DEPLOY_KEY_V1`; never Guardian |

Required check repository is `zenindiones-maker/BR-no-GTA`, workflow is
`.github/workflows/security-guardian-baseline.yml`, and name is `Deterministic
policy contracts`. The App ID must be independently authenticated, not accepted
from a candidate assertion. The run and check-run must refer to that workflow
and exact candidate with conclusion `success`. Existing CodeQL and all other
required checks/rulesets remain enforced; this contract adds no bypass.

The contract digest is SHA256 of UTF-8 JSON with sorted keys, compact separators,
`ensure_ascii=False`, and no trailing newline. The completed evidence contains
exactly `schema_version`, `contract_sha256`, `binding` (the entire contract),
`observed_remote_before`, `observed_remote_after`, `observed_tree_after`,
`required_check_conclusion`, `executor_retired` and `authorization_consumed`.
The before OID MUST equal the expected old OID; after MUST equal the candidate;
tree after MUST equal the candidate tree. Missing, extra, altered or wrongly
typed evidence is rejected. A completion receipt requires success and both
retirement/consumption flags true; partial attempts cannot claim completion.

## External one-shot procedure (future, separately reviewed execution)

1. After this patch receives independent review, materialize a one-shot capsule
   **outside the repository in Termux**, from independently reviewed trusted
   bytes. Pin its SHA256 in the Harness contract before execution. Do not source
   candidate scripts, Python, hooks, configuration, actions or dependencies.
   Use a clean environment and empty Git object repository with hooks disabled;
   candidate commits are Git data only, never a checkout or executable input.
2. Authenticate the fresh persisted Harness grant and independent review through
   their trusted sources. Validate reviewer independence, receipt digest,
   PASS/PASS_WITH_ACCEPTED_RISK disposition and exact commit/tree/diff binding.
   The blocked candidate's BLOCK receipt cannot authorize this installation.
   Read the GitHub check identity and success from GitHub, with no candidate
   substitution. Verify the existing gates without editing them.
3. Verify the old canonical tree lacks the permanent control plane. If already
   installed, reject bootstrap and use the permanent workflow. Recompute the
   external capsule digest and all contract bindings before credential exposure.
   Serialize attempts with a durable single-use claim keyed to the contract
   digest and authorization ID, managed outside the candidate repository.
4. Only after these checks, expose the existing promotion identity to the
   external capsule. Independently require old OID ancestry of candidate, then
   perform an immediate authenticated remote-before equality check. Update only
   the target ref using exact `--force-with-lease="${TARGET_REF}:${EXPECTED_OLD_OID}"`
   and the explicit candidate refspec. Never use plain force. This is a single
   attempt; a moved ref fails closed even if the move remains an ancestor.
5. Read the remote ref back and verify its commit and tree. Preserve the raw
   nonsecret observations and their provenance outside candidate control, then
   produce the exact-bound completion evidence. Harness consumes the grant;
   immediately retire the single-use capsule and its credential access after
   the first installation. Keep the capsule digest, review and audit evidence;
   retirement does not delete prior evidence or disable the permanent identity.
6. On rejection, timeout or uncertain write outcome, disable further capsule
   use and reconcile remotely read-only. Do not retry blindly or reuse the
   grant. A failed attempt is retained as failure evidence, never a fabricated
   completed receipt. Once installed, all subsequent promotions use the
   permanent canonical workflow; bootstrap cannot be invoked again.

No credential moves into permanent preflight. No candidate-controlled execution
is allowed in either privileged path. This patch neither materializes the
external executable nor grants permission to run it.
