# BR_OWNER_V1 identity calibration dedup guard v1 (A+C)

Status: IMPLEMENTED fail-closed; recalculated values are
`RECALCULATED_DEDUP_PENDING_OWNER_APPROVAL` (not owner-approved). No policy
threshold was lowered or changed; see `docs/policy/owner_authorizations.md`.

## Problem
Survey run 39200354064: 54 identity inliers, but only 14 unique sha256 (clips 45–53 appear
5× each, 101 3×, 120 and 121 2× each). Every calibration (centroid, centroid p10 = 0.868594,
pairwise p10 = 0.793141, leave-one-out outliers, window p10 = 0.593494) was weighted toward one
recording session, with an effective sample size of 14.

## C: rejection at index load (`materialize_telegram_owner_references`)
- Processed in (message id, input id) order; the earliest copy is kept.
- Same `telegram_file_unique_id`: rejected before any `getFile` (never downloaded).
- Same content sha256: the downloaded copy is deleted and rejected.
- Private result `duplicate_references_rejected` (input ids only); public evidence
  carries only `duplicate_rejected_count`.
- Calibration requires at least 12 unique clips (`OWNER_IDENTITY_CALIBRATION_REQUIRES_12_UNIQUE_CLIPS`).
- Segments of one source clip are one calibration sample: mean embedding, pooled
  windows, and one unit of weight per source clip in the window p10.

## A: guarded calibration (`app/services/owner_voice_identity_calibration_guard.py`)
- Identity profile: calibrate on one sample per unique clip. The legacy
  duplicate-weighted multiset is reproduced exactly from the load-time
  multiplicities. Effective floor = max(recorded, recalculated with duplicates,
  recalculated dedup) for both `clone_centroid_min_similarity` and
  `clone_reference_min_similarity`.
- Recorded values come from clone runs 38094520428 and 38158052098: 0.8685941796030944,
  0.7931407403048752, and window 0.593494.
- Inliers = dedup inliers that were also legacy inliers, so no clip is ever newly admitted.
- Whole-audio gate: the clone must pass the dedup centroid at the effective floor
  AND the legacy centroid at max(recorded, legacy). The legacy centroid never
  leaves the private runtime (`sanitized_profile` strips it).
- Window consistency: one entry per unique clip; min = max(0.593494, dedup p10).
- Segment duration-matched p10 (OWNER_AUTHORIZED_20261011_*): max(p10 over all
  windows, p10 with each source clip weighted once). The authorized method is
  kept and can only get stricter.
- Every report prints `OWNER_IDENTITY_CALIBRATION_GUARD=` and the manifest has
  `identity_calibration_guard` (scalars only: status, owner_approved=false,
  recorded, with duplicates, dedup, effective, counts).
- Wired in: single human clone, ASR survey, segment survey, Qwen3 fine-tune dataset.

## Pending owner decision (B)
After one contract-only calibration audit report of the honest dedup values,
Luiz may approve them (they may be lower than recorded). Until then the
effective floors are max(...). Flipping `OWNER_APPROVED_RECALCULATED_FLOORS`
requires a verbatim owner record in `docs/policy/owner_authorizations.md`.

## Term coverage rule (PT-BR pro gate), PROPOSED, pending owner confirmation
`PROPOSED_TERM_RULE_20261019_MIN2_OR_1_WITH_OWNER_EAR_GE4`:
- 2 or more owner occurrences = covered, and the existing phoneme bound still applies.
- 1 occurrence = covered only with Luiz's ear rating ≥ 4 on `pronuncia_nomes_gta`.
- 0 occurrences = `OWNER_TERM_UNCOVERED`.

While `TERM_RULE_OWNER_CONFIRMED = False`, a single occurrence fails closed
(`TERM_RULE_SINGLE_OCCURRENCE_PENDING_OWNER_CONFIRMATION`). Rows without
`owner_occurrences` keep the previous behaviour.
