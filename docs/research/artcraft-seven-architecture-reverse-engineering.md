# BR-no-GTA / ArtCraft — Architecture Reverse-Engineering Inventory (all seven)

**Evidence level:** static architecture **inspection at exact SHA**, *not* behavioral parity, installation success, Adobe binary disassembly, or integration approval. Runtime receipts are produced by the separate seven-matrix workflow.

Original owner-directed seven-source manifest: [pinned-source study](artcraft-seven-pinned-sources.json). Snapshot GitHub Actions run [38009669454](https://github.com/zenindiones-maker/BR-no-GTA/actions/runs/38009669454) proved 7 verified public archives (7,200 versioned files, 94.7 MB packaged).

## What these projects actually are

The seven public `storytold/*craft` repositories advertise **clean-room reimplementations** in Rust, released with **MIT OR Apache-2.0** licensing at their exact pinned commits. This does **not** establish that proprietary Adobe executables were decompiled or that workflows are functionally equivalent. Feature statements in READMEs are *upstream claims* until independently exercised.

| System (exact pinned commit) | Inspected root Rust workspace modules | Evidence-aligned BR use | Integration priority |
|---|---|---|---|
| [FilmCraft](https://github.com/storytold/filmcraft/tree/7b6c134472287db4367fca80bcb498240ba36567) | `time`, `media`, `frame`, `codecs`, `project`, `edit`, `interchange`, `render`, `audio-dsp`, `speech`, `gpu`, `export`, `automation` | Timeline and interchange, deterministic frame assembly, title/caption policy, codec QA, export receipts | P0 |
| [EffectCraft](https://github.com/storytold/effectcraft/tree/30aaddf7c23329dcdfc72a5bf65b55747bbd6be1) | `keyframe`, `project`, `effects`, `expr`, `render`, `gpu`, `lottie`, `export`, `plugin`, `automation` | Compositor and keyframe deterministic QA, layered motion graphics, synthetic render fixtures | P0 |
| [PhotoCraft](https://github.com/storytold/photocraft/tree/69b1379781a4d7e12774b9768cab44b35db6231b) | `psd`, `raster`, `compose`, `cms`, `color`, `paint`, `io`, `plugins`, `automation` | Thumbnail image processing, text/layer composition, color/gamma fidelity, PSD ingestion | P1 |
| [VectorCraft](https://github.com/storytold/vectorcraft/tree/866ea5878a7f6db7dd3d6b1287f9a9bb3a241c33) | `geom`, `doc`, `pathops`, `render`, `text`, `svg`, `pdf`, `mcp`, `plugins` | Render-independent logos, diagrams, dynamic overlays, vector title shapes | P1 |
| [LightCraft](https://github.com/storytold/lightcraft/tree/88ea1a804b35709e1fe436e3792adf0428b97daa) | `raw`, `develop`, `pipeline`, `color`, `denoise`, `catalog`, `preview`, `gpu`, `segment`, `mcp` | Camera image ingest, stable tone/color corrections, RAW handling and metadata provenance | P2 |
| [PdfCraft](https://github.com/storytold/pdfcraft/tree/c110c579a24800bb841b5d643e2e34e161e81f13) | `cos`, `filters`, `crypt`, `redact`, `js`, `annot`, `ocr`, `render`, `preflight`, `export` | Source-document safety, PDF raster frames and quotation/highlight workflows, provenance | P2 |
| [DesignCraft](https://github.com/storytold/designcraft/tree/66c7ce7e96ec286a091878cc2541ee8369aa79d6) | `fonts`, `compose`, `images`, `render`, `pdf`, `idml`, `epub`, `mcp`, `engine` | Multi-page research briefs and video production dossiers, typographic layout | P2 |

The module names above are **observed workspace dependencies declared by Cargo.toml**. Their presence is not proof of a complete working implementation.

## Cross-project dependency and supply-chain considerations

1. **EffectCraft's FilmCraft dependency is not the study's FilmCraft HEAD.** It pins many codec/media/interchange crates to `storytold/filmcraft@2c5ba7a72619935f0481f99d59409e0d1844b234`. The examined FilmCraft snapshot is `7b6c134472287db4367fca80bcb498240ba36567`. Never silently patch or replace this revision. Record the exact resolved Cargo.lock graph and probe compatibility independently before attempting integration.
2. Workspaces declare Rust **edition 2024**. Minimum Rust is **1.95** for FilmCraft, EffectCraft, PhotoCraft, VectorCraft and **1.90** for LightCraft, PdfCraft, DesignCraft.
3. PdfCraft includes local patched crates under `vendor/`; provenance and security advisory scope includes those forked sources, not just crates.io advisories.
4. Some projects expose `mcp`, script/expression, or plugin modules. Never connect third-party MCP servers or interpreters directly to the single-authority DeepSeek Harness. Protocol boundaries require exact capabilities, sandboxed files, provenance receipts, and owner approval.
5. Dynamic GUI/GPU/WebAssembly performance and any third-party AI model downloads are **not** covered by headless cargo checks. LightCraft's optional segmentation dependencies and PDF embedded scripts require additional sandbox reviews.
6. `cargo fetch --locked` is dependency resolution, not test/build; `cargo check` is not equivalent to a runnable binary; a bounded `--help` smoke is not evidence of production throughput.

## Reverse-engineering study plan (non-proprietary, testable)

**FilmCraft:** reconstruct project graph, sequence-time semantics, cut/trim/speed-change determinism, transition graph, audio sample-sync, export muxing, caption flag suppression, and frame-by-frame parity against **synthetic user-authored fixtures**. Avoid introducing subtitles or overlays into production masters.

**EffectCraft:** investigate graph representation, timing/keyframe interpolation, text rasterization, script/plugin sandbox, alpha compositing, color and cache keys; render fixed golden-frame synthetic compositions. Test deterministic CPU baseline before optional GPU.

**PhotoCraft:** compare raster operators, layer/mask compositing and ICC/CMYK pipeline on small synthetic images. Fuzz/bound PSD import before any owner artwork.

**VectorCraft:** compare SVG import-export on synthetic path/shape sets and deterministic rasterization; keep MCP disabled.

**LightCraft:** test RAW metadata/EXIF handling with public test RAW files, limit resource use, and measure CPU color transforms; no camera private files or model installs.

**PdfCraft:** fuzz parser/object graph and isolate potentially active JavaScript, embedded resources and links; prioritize secure read/rasterization, NOT blindly executing untrusted documents.

**DesignCraft:** inspect IDML import and text/pagination graph using test fonts with explicit licensing, validate reproducible PDF/EPUB export.

## Isolation and acceptance requirements

The current [seven-matrix Docker workflow](../../.github/workflows/br-artcraft-seven-build-validation.yml) collects per-app source hash, license, Cargo.lock, dependency-resolution outcome, no-network workspace check, one core-crate test, optional CLI build and bounded `--help` smoke; **all seven statuses are independent and fail closed**. Results/artifacts expire after 30 days and must be reconciled into a durable report. Remote runner resources are ephemeral and no app is installed on BR production.

**Do not automatically merge, select a new canonical executor, copy third-party code into the V24 branch, install apps on A15, expose services, pay for GPU, or publish anything.** Any candidate integration requires distinct architecture evidence, license and security review, golden fixtures, repeatability, performance budget, and owner approval.
