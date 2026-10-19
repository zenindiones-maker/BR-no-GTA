# BR_OWNER_V1 reference segment survey v1 (ASR only)

Status: PREPARED. Runs once only on an owner-approved commit that adds
`.run/br-owner-v1-reference-segment-survey.request.json` on
`work/br-owner-voice-mission-state-failclosed-v1` (it must be the last commit:
the workflow checks `HEAD^..HEAD`).

## Owner decision (19/10 07:33 BRT)
Luiz: his sent audios already contain correct pronunciations of the GTA names
(survey run 39200354064 found them in clips 47, 49, 120, 122, which were rejected
only for being longer than 30 s; 47 and 49 also failed window identity). Segment the long clips; no new
recordings for now.

## Pipeline (scripts/owner_voice_reference_segment_survey.py)
1. Same materialization as the ASR survey: Telegram `getFile` only (wrapper
   rejects every other method), ffmpeg to 16 kHz mono, pinned ECAPA, the
   existing `calibrate_owner_identity_profile` and window calibration (unchanged).
2. Exact sha256 dedupe of inliers, then select unique clips longer than 30 s (9 in run 39200354064).
3. faster-whisper `large-v3-turbo`, CPU int8, `vad_filter=True`,
   `word_timestamps=True`, beam 5, on each long clip.
4. Cut candidates = inter-word gaps of at least 0.20 s that also contain at least 0.10 s of
   energy-VAD silence (`speech_mask`); cut at the centre of that silent run.
   Clip head/tail plus cuts are the only boundaries, so no word is cut.
5. Dynamic programming picks non-overlapping 6–25 s segments that maximise
   covered speech; edges trimmed to 0.15 s around the first and last word.
   Regions that cannot form a valid segment are dropped, never forced through a word.
6. Per segment: same survey quality filters (`evaluate_reference_quality`),
   own ECAPA embedding, same per-window identity consistency, centroid
   similarity, re-transcription (pt probability, VAD ratio, words/s).
7. Dedupe (sha256; embedding ≥ 0.97 AND transcript Jaccard ≥ 0.80), MMR ranking.
8. Term index: canonical GTA term -> Luiz's occurrences (segment id + word
   time span, segment-relative) in quality-passed segments.
   `COVERED_MIN2` (≥2), `COVERED_MIN1_WEAKER` (1; flagged `weaker_single_occurrence`),
   `NOT_COVERED_BY_QUALIFIED_SEGMENT`. `min_occurrences_decision` is
   `PENDING_OWNER_DECISION`; nothing is applied to the PT-BR pro gate.

## Privacy
Public JSON only: segment ids, source ids, sha256, time spans, scalar metrics,
transcript sha256, word counts, term names with time spans, reasons. Never
audio, embeddings, transcripts or private paths. Private workspace (chmod 700) is
deleted in an `always()` step; artifact retention is 7 days. No synthesis model, no Telegram send.

## Cost and time
GitHub-hosted runner, free minutes only. Install about 1 min, models about 2–4 min,
download + ECAPA (57 clips + windows) about 3–4 min, ASR of about 380 s of long-clip audio with
word timestamps plus about 380 s of segment re-transcription at about 1.4× realtime is about 9–10 min.
Total about 16–22 min; timeout 45 min.

## Assessment (no change applied): 40/54 calibration inliers are exact duplicates
Run 39200354064: 54 inliers -> 14 unique sha256. Clips 45–53 are each present
5×; 101 is 3×; 120 and 121 are 2×.
- `clone_centroid_min_similarity` (p10 of inlier-to-centroid similarities; the
  current 0.868594) is computed over the duplicated set and against a centroid
  weighted 5× toward clips 45–53. Using the reported per-clip similarities with
  multiplicities reproduces 0.8686. The same values counted once give about 0.8679. The
  true deduplicated centroid would also move, which cannot be computed outside CI.
- `clone_reference_min_similarity` (pairwise p10): 95 of 1431 pairs (6.6 %) are
  copies with cosine 1.0, inflating the p10 (stricter, not weaker).
- Leave-one-out outlier detection: a duplicated clip's copies remain in its own
  leave-one-out centroid, inflating its score and shrinking MAD. Clips from other sessions look
  relatively worse.
- Window-consistency calibration: p10 over per-clip p10s, weighted the same way.
Net effect: thresholds are not weakened, but they are biased toward one
recording session ("Luiz in clips 45–53" rather than "Luiz"), and the effective
sample size is 14, not 54.

Proposed remediation (owner decides; not applied):
A. Fail-closed dedupe now: dedupe by sha256 before `calibrate_owner_identity_profile`,
   recompute, and use `max(recorded, recomputed)` for every floor until Luiz approves.
B. After a contract-only calibration audit run reports both values, Luiz approves
   (or not) the honest deduplicated thresholds, which may be lower or higher.
C. Reject duplicate sha256 at index sanitisation, require ≥ 12 unique clips, and
   never add segments of one clip as independent calibration samples (they are
   correlated). Segments serve as references and pronunciation index only.
