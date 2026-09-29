# PersonaPlex Integration

PersonaPlex is integrated as an isolated experimental full-duplex speech-to-speech runtime. It is **not** part of the canonical PT-BR owner-voice route.

## Pinned upstream

- Code: `NVIDIA/personaplex@3428dfd95309a7f3c84fd93259ded0f810d1ff91`
- Model: `nvidia/personaplex-7b-v1@fdaf4090a61cb315c138a1faee287ffd6c716309`
- Code license: MIT
- Model license: NVIDIA Open Model License
- Model access: gated on Hugging Face
- Documented model language: English
- Audio: 24 kHz, mono, full-duplex WebSocket streaming

The runtime lock is `runtime.lock.json`.

## Architecture

The main BR-no-GTA application does not import PersonaPlex/Moshi or load its weights. The integration is split into:

1. **Harness boundary** — `app/services/personaplex_realtime_service.py`
   - exposes only `harness.voice.turn`;
   - blocks privileged tools;
   - rejects PT-BR routing;
   - validates transport and the upstream binary WebSocket framing.

2. **GPU sidecar runtime**
   - installed outside the repository;
   - code is checked out at the immutable upstream revision;
   - model weights remain outside Git and require the user's accepted Hugging Face model terms;
   - voice prompts remain in private runtime storage.

3. **Routing policy**
   - `production_eligible=false`;
   - `ptbr_eligible=false`;
   - `official_owner_voice_eligible=false`;
   - there is no silent fallback from `BR_OWNER_V1` to PersonaPlex.

## Install the runtime code

On the GPU host:

```bash
sudo apt-get update
sudo apt-get install -y git pkg-config libopus-dev python3.12 python3.12-venv
bash integrations/personaplex/install_runtime.sh
```

This installs only the pinned code. It intentionally does **not** download the gated model and does not persist an HF token.

## Model access

The human owner must accept the PersonaPlex model terms on Hugging Face. Pass `HF_TOKEN` to the private runtime process at runtime only. Do not commit it, write it to an install receipt, or expose it through logs.

The current official model is English-only. It must not be used to satisfy PT-BR narration or `BR_OWNER_V1`.

## GPU policy

NVIDIA documents A100 80 GB as test hardware. The live server requires a CUDA-capable GPU. CPU offload exists upstream, but low-VRAM live execution is not considered certified here because upstream issue reports show instability/OOM on several lower-memory configurations.

The GitHub-hosted CI runner therefore validates only contracts and protocol behavior. It must not download the 17+ GB gated weights or attempt live PersonaPlex inference.

## WebSocket contract

The upstream endpoint is `/api/chat`.

Client-to-server audio frames:
- first byte `0x01`;
- remaining bytes are Opus payload.

Server-to-client frames:
- `0x00`: handshake;
- `0x01`: Opus audio;
- `0x02`: UTF-8 text token stream.

Session query parameters include the private voice-prompt basename, the text role prompt, and a deterministic seed.

Remote plaintext WebSocket transport is rejected. Use loopback `ws://127.0.0.1` for a local sidecar or authenticated/TLS `wss://` for a remote private runtime.

## Voice prompts

PersonaPlex supports audio voice conditioning. Raw owner voice must remain in the private runtime mount and never enter Git, Actions artifacts, or Actions cache.

This integration does not promote a PersonaPlex voice prompt into the canonical owner identity. Any future promotion would require a separate human-reviewed policy change and a model with demonstrated PT-BR support.
