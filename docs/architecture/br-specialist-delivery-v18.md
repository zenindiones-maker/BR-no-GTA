# V18 — Owner Voice Delivery Integrity Specialist (read-only)

**Status:** isolated V18 candidate. No new private voice sample, Telegram send, Git push, learning write, training, canonical promotion, or alternate authority.

## Real remote check performed outside CI

2026-10-08: using the authorized GitHub connector, read the private existing ledger branch `owner-voice-audition-state`. Its remote ref pointed to `87f2dd39705437bead0df8710eefe0c48ea1d529`. Read the 12 existing mission-head files and projected only safe non-biometric fields. The largest verified clone Telegram message ID was 666 (reference 665, control 667), state CONFIRMED/SENT, identity FAIL, content FAIL, human review PENDING. No later confirmed clone ID was visible in those twelve mission records. This is not a full Telegram transport search or proof that no unindexed external messages ever existed.

The failed Qwen candidate/run 37808729277 had no new remote-clone ID proven. Its fatal `commit_refs` exit 52 does not authorize resending media. Existing V13-V14 implementation already retries one bounded Git push with exact remote readback and no force; avoid duplicating or weakening it.

## Operational specialist

`app/services/br_owner_delivery_reconcile_specialist_v18.py` reuses `OwnerVoiceAuditionGitLedgerStore.snapshot(mission_id)`, which fetches and cross-checks an exact remote Git OID. The specialist never calls `transact` or Telegram. It explicitly separates:
- CONFIRMED/SENT with three distinct message IDs: **transport receipt**, not quality or approval;
- missing head, non-confirmed state, ambiguous IDs or remote move: **reconciliation required**, no blind retry;
- identity/content FAIL: human and acoustic remediation required, even when Telegram succeeded;
- a forged APPROVED string: not an authenticated human decision, not a security override.

Only status, message IDs, safe hash and failure classifications appear in its receipt. It drops chat IDs, review tokens, private SSH keys, audio bytes, URLs and cloned voice identifiers. Receipt SHA256 proves consistency, not independent signature.

The V18 CI uses mocked Git snapshots and existing transient/CAS regression tests. It does **not** have deploy-key access to the private ledger and cannot claim live remote readback from CI. The live snapshot read mentioned above was a separate authenticated connector action; neither action writes to the ledger.

## Operational next stage

1. Resolve the exact remote state of the failed mission and whether Telegram has any ambiguous side effect. Reconciliation must be read-only unless existing owner authorization explicitly permits a new CAS transaction.
2. Fix the owner voice identity and pronunciation through a newly consented/reviewed Qwen audition. 666 is transport-confirmed but identity FAIL.
3. Keep full 20–25 minute master and owner PRIVATE review blocked until real acoustic QA and explicit approval.

**Source authority**: the repository's existing Harness and OwnerVoiceAuditionGitLedgerStore; no model is given Git writer permissions. New LLaMA-Factory training is NOT authorized. V17 first specialist remains isolated at 9f8831fdf4ab8404220c5e9e6b9e27e4b46be6a7.

## Additional V18 authority gate

The live private-ledger helper requires a persisted Harness RESEARCH authorization with exact subject `capability:owner-voice.ledger-readonly-v18` and `lineage.allow_remote_ledger_read=true`. Without that explicit grant, it refuses a snapshot even if an SSH-capable store object is available. Tests check revoked and no-grant cases against an initialized private Harness authorization database. This helper is not yet a newly promoted Registry executor: no model or agent has automatic access to its private ledger scope.
