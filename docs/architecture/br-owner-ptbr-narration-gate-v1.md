# BR_OWNER_V1 — PT-BR professional narration gate v1 (additive, fail-closed)

Owner rule: `OWNER_RULE_20261019_PTBR_ULTRA_PROFESSIONAL_NARRATION`
(verbatim in `docs/policy/owner_authorizations.md`). Status: implemented
locally, NOT run. It only blocks: `final = existing_gates AND ptbr_gate`.
Identity gates (0.868594, the 11/10/2026 p10 bindings) are untouched.

## What the existing QA measured (before)
Speaker identity (ECAPA centroid/reference, per-segment p10); ASR per segment
(PT: CER ≤ 0.20 and coverage ≥ 0.70; WER not used for PT); language ID
(whisper pt ≥ 0.90); clipping ≤ 1 %; VAD speech ratio ≥ 0.55; adjacent word
repetition ≤ 3; reference SNR ≥ 15 dB. Human buttons only (approve/reject).

## Gaps closed by this gate
| Gap | New measurement | Threshold source |
|---|---|---|
| No naturalness/quality score | DNSMOS P.835 SIG/OVRL, UTMOSv2 | ≥ p10 of Luiz's own clips |
| No BR-vs-PT accent check | lgris/portuguese-accent-classifier (pt_br prob) | ≥ max(0.80 documented, owner p10) |
| ASR too lax (CER 0.20, no WER) | global WER/CER + worst segment CER | WER ≤ 0.08, CER ≤ 0.03, segment CER ≤ 0.06 |
| No prosody | F0 variation (semitones), syllable rate, pause ratio, pause p90 | owner p05–p95 band (p95 for pause p90) |
| No delivery loudness | EBU R128 integrated/true peak on a private -16 LUFS master copy | -16 ±1 LUFS, TP ≤ -1 dBTP |
| Clipping/repetition loose | clipping ≤ 0.05 %; 0 adjacent repetitions | documented |
| GTA names only by ASR text | ASR recognition + phoneme PER vs Luiz's own occurrences | p90 of Luiz self-distance; no owner reference ⇒ FAIL |
| No structured human scoring | 6-criterion sheet (1–5), all ≥ 4 + APPROVE | owner is final authority |

Missing metric, extractor error, < 8 owner clips, or candidate inside the
calibration set ⇒ FAIL. Calibration is fingerprinted (sha256 of owner clip
hashes + thresholds) and published in the report; no audio/embeddings/text.

## Tools (zero cost, open source, CPU)
- DNSMOS P.835 ONNX — microsoft/DNS-Challenge (code MIT), pinned sha256
  269fbebd…f6edd. https://github.com/microsoft/DNS-Challenge
- UTMOSv2 — MIT, CPU supported, pinned commit cc2700db.
  https://github.com/sarulab-speech/UTMOSv2
- Accent pt-BR vs pt-PT — Apache-2.0, ~95 % reported accuracy, rev 4f287aba.
  https://huggingface.co/lgris/portuguese-accent-classifier
- Phonemes — facebook/wav2vec2-xlsr-53-espeak-cv-ft, Apache-2.0, rev 2c733782
  (arXiv:2109.11680). https://huggingface.co/facebook/wav2vec2-xlsr-53-espeak-cv-ft
- ASR — faster-whisper large-v3-turbo (already pinned). Whisper large-v3
  FLEURS Portuguese ≈ 3.5–3.8 % WER (sota2 / sprag benchmarks); TTS WER via
  Whisper follows Seed-TTS-eval. https://github.com/BytedanceSpeech/seed-tts-eval
- Loudness — FFmpeg ebur128 (ITU-R BS.1770). YouTube normalizes to ≈ -14 LUFS
  and does not boost quieter uploads; -1 dBTP ceiling for streaming
  (Auphonic / platform tables); ACX peaks ≤ -3 dB for audiobooks.
- Prosody — YIN (de Cheveigné & Kawahara 2002); syllable nuclei (de Jong &
  Wempe 2009, Behav. Res. Methods 41:385). 150–160 wpm narration norms are
  English; for PT-BR the band is calibrated on Luiz instead.
- Rejected: NISQA (weights CC BY-NC-SA, non-commercial — channel is monetized).

## Local evidence (box, CPU)
LibriSpeech sample: DNSMOS OVRL 3.29 → 1.21 with added noise; UTMOSv2 2.76 →
1.82. Public PT-BR Wikimedia clips: accent pt_br = 1.00 (EN sample = 0.00),
syllable rate 4.57/s on read PT-BR. UTMOSv2 first load ~30 s; ~2–15 s/clip.

## CI cost
Extra in the clone job (free GitHub-hosted minutes only): UTMOSv2 install +
800 MB weights (~2–3 min), DNSMOS/accent download (<1 min), ~54 owner clips +
candidate × (UTMOSv2 + accent + DNSMOS + prosody) ≈ 6–12 min on 4 vCPU.

## Open items
Owner term references (Luiz saying each GTA name, ≥ 2 occurrences) are
required for the phoneme check; until they exist every audition that contains
GTA names fails `OWNER_TERM_REFERENCE_MISSING` by design.

## GTA term coverage rule (PROPOSED 19/10/2026, pending owner confirmation)
`PROPOSED_TERM_RULE_20261019_MIN2_OR_1_WITH_OWNER_EAR_GE4` (constants in the gate
service; occurrences come from the segment survey `term_reference_index`):
- ≥ 2 owner occurrences: covered, and the phoneme bound (p90 owner distance) applies.
- 1 occurrence: covered only with Luiz's ear rating ≥ 4 on `pronuncia_nomes_gta`
  (the term goes to `pending_owner_ear_terms`, and `evaluate_owner_scoring`
  enforces the rating).
- 0 occurrences: `OWNER_TERM_UNCOVERED`.

Until `TERM_RULE_OWNER_CONFIRMED` is set from a verbatim owner record, a single
occurrence fails closed. Nothing becomes looser than before.
