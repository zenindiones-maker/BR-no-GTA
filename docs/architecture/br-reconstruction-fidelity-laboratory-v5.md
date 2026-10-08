# BR-no-GTA Reconstruction Fidelity Laboratory V5

Status: DEVELOPMENT CANDIDATE ONLY. DeepSeek Harness remains the sole authority. No Owner Voice, Telegram, YouTube, learning memory, canonical promotion or production modification is authorized by these modules.

## What "perfect" means

Technical equivalence is a bounded, measurable property: aligned decoded pixels, source/candidate FPS and resolution, signal waveform equality, delay or spectral energy within a specified measured interval. Creative equivalence (narrative, performance, aesthetics), intellectual property rights, and human voice identity **cannot** be concluded from these numbers.

Same-content copying and reconstruction comparison is restricted to user-owned or explicitly licensed assets. The declared right is checked by the Harness but is NOT an independently validated license. Observation-only sources are allowed for studying abstract techniques elsewhere but not for same-content reconstruction in this subsystem.

## Research references

- FFmpeg SSIM and PSNR frame-aligned filters: https://ffmpeg.org/ffmpeg-filters.html#ssim and https://ffmpeg.org/ffmpeg-filters.html#psnr .
- Netflix VMAF reference/distorted frame synchronization and 2026 model family: https://github.com/Netflix/vmaf and https://github.com/Netflix/vmaf/blob/master/resource/doc/ffmpeg.md .
- librosa time alignment / DTW: https://librosa.org/doc/0.11.0/generated/librosa.sequence.dtw.html .
- OpenTimelineIO clip/source ranges: https://github.com/AcademySoftwareFoundation/OpenTimelineIO/blob/main/docs/tutorials/time-ranges.md .
- WhisperX word alignment limitations: https://github.com/m-bain/whisperX .
- OpenCV phaseCorrelate image registration: https://docs.opencv.org/4.13.0/d7/df3/group__imgproc__motion.html .

Do not claim VMAF, WhisperX, libvmaf, Ghidra, REAPER automation or cross-voice alignment is installed merely because it was researched. The concrete V5 has FFmpeg and NumPy on CI, and pinned REA 6.0.0 for existing software observation.

## Implemented capability

Capability ID: reverse-engineering.reconstruction.fidelity.
Domain: reconstruction-fidelity.
Action: RESEARCH only, no billing fallback, no memory writes or publication, no identity authority.
Executor: app.services.reverse_engineering_harness_service.execute_authorized_fidelity_assessment.
Underlying service: app.services.reverse_engineering_fidelity_v5_service.compare_reconstruction.

All operations demand an existing persisted Harness authorization with scoped allowed_media_roots, the matching Harness routing decision, exact payload field whitelist, source+candidate distinct paths, licensed/owned rights on both media files and a 12-second maximum window. Fails closed on nonmatching resolution, FPS, nominal VFR or duration; no deceptive image scaling, interpolation or forced temporal synchronization.

Video: two independent FFmpeg passes measure per-frame PSNR MSE and SSIM, count compared frames, confirm complete selected-window coverage and whether all measured YUV420p pixels match. Frame-level equivalence of an authorized source is not perceptual quality of independently created content.

Audio: 16 kHz mono f32 decode; difference RMSE without alignment/gain correction, normalized correlation, gain ratio, decoded PCM equality, bounded FFT lag peak estimate and coarse frequency-band energy differences. Periodic audio makes delay estimates ambiguous; stereo downmix masks spatial effects. High correlation with a changed volume correctly fails waveform equality. No phoneme/voice identity, intelligibility or subjective mastering quality is inferred.

Output is provenance-focused, source+candidate hashes and SHA evidence; always quality_approved=false, identity_verified=false, publication_authorized=false and harness_learning_write=NOT_ATTEMPTED.

CLI invocation (only on an approved workstation with the persisted authorization already issued):
  python scripts/br_reverse_engineering_harness.py --mode fidelity --authorization-id EXISTING_AUTH --input /authorized/reference.mp4 --rights owned --candidate /authorized/rebuild.mp4 --candidate-rights owned --window-seconds 2.0 --output /private/new.json

The V5 trial bridge validates two same-reference V5 receipts, identical observation window, declared rights, hashes, zero declared spend and referenced external safety-review evidence. It emits a paired V4 observation, not a decision to train or route differently. The independent review is not authenticated by hash consistency alone, and real-world validation remains mandatory.

## Practical test

CI creates a synthetic media reference, a video-identical but audio-gain-adjusted variant, and a distinct-path exact copy. It executes both evaluations via persisted Harness authorization. The video tracks should match, and the gain change should be measurable even when audio correlation remains high. Adversarial tests reject unauthorized rights, private voice directories, revoked tokens, forged control fields, incompatible formats and tampered receipts. A paired V4 trial of one real example must output INSUFFICIENT_EVIDENCE, not REVIEW_CANDIDATE.

## Next real studios and production gates

1. Learn exact soundtrack mixing with REAPER stems: phase correlation by channel, EQ/bands, loudness, separation and intelligibility, followed by human hearing tests.
2. Native PT-BR private voice phonetic alignment, prosody and single BR_OWNER_V1 identity QA. "Vice City" remains pronounced "vaicy siti". Do not run owner-biometric samples through generic agents.
3. Original visual animation and shot grammar: Blender/OpenCV tracking, camera/object separation, motion continuity, OCIO color pipeline and independently annotated full episodes.
4. Original source-licensed timeline reconstruction through OpenTimelineIO, frame accurate segments and actual renderer imports.
5. Studio measured cut precision/recall, cross-platform audio mastering review, blinded artistic evaluation, factual research and licensed-provenance audit.
6. A 20–25-minute representative original BR-no-GTA production benchmark, signed external review of sources and safety evidence, and explicit owner promotion authorization.

A clean CI on a 2-second synthetic clip is evidence of functioning tools, not a guarantee of a perfect reconstructed professional episode.
