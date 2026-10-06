# BR-no-GTA Professional Zero-Cost Workstation v2

## Objective

Provide a professional browser-accessible media workstation for BR-no-GTA
without replacing the DeepSeek Harness authority or introducing a paid compute
fallback.

## Runtime architecture

A15/Termux is the control plane. The Codespace remains a 2-core / 8 GB / 32 GB
interactive workstation. Xpra HTML5 on port 14501 is the primary remote
transport and noVNC on port 6081 remains an emergency fallback. Both bind to
loopback inside the Codespace. The A15 controller requires the GitHub forwarded
port to be `private`.

The workstation supplies FFmpeg/ffprobe, mpv, MediaInfo, SoX and Rubber Band
for inspection, preview and bounded media operations. The repository Harness
and its capability/authorization surfaces remain authoritative.

Microphone forwarding, webcam access, file transfer, printing, mDNS, session
sharing and client-triggered command execution are disabled.

## Heavy media policy

Long encodes and structural QC should run on the public repository's standard
GitHub-hosted `ubuntu-24.04` runner rather than consuming interactive
Codespaces core-hours. The batch workflow has bounded timeouts, concurrency
cancellation and no large-media artifact upload.

The MASTER_FINAL gate remains fail-closed for structural requirements. Visual
claims such as overlay or burned-caption absence are never inferred from
container metadata alone.

## Storage policy

Transient media scratch/cache lives under `/tmp`. Do not accumulate masters
or source media inside the Codespace. The workstation is a disposable runtime;
durable code and configuration belong in Git.

## Required proof

A professional runtime is not READY until all of these are true:

- `BR_PRO_WORKSTATION=PASS`
- `XPRA_HTML5=PASS`
- `XPRA_X11=PASS`
- `XPRA_AUDIO_SERVER=PASS`
- `XPRA_BIND=LOOPBACK_ONLY`
- `FFMPEG=PASS`
- `MPV=PASS`
- `MEDIAINFO=PASS`
- `HARNESS_AUTHORITY_SURFACE=PASS`
- GitHub forwarded desktop port is `private`
- `PAID_FALLBACK=FALSE`
- `UNKNOWN_COST_FALLBACK=FALSE`
- `REAPER_REQUIRED=FALSE`
