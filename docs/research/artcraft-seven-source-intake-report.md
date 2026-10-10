# ArtCraft — seven source snapshots, read-only study intake

## Verified completion (2026-10-09 / GitHub UTC 2026-10-10)

- Source owner: [storytold](https://github.com/storytold)
- GitHub Actions execution: https://github.com/zenindiones-maker/BR-no-GTA/actions/runs/38009669454
- Artifact: https://github.com/zenindiones-maker/BR-no-GTA/actions/runs/38009669454/artifacts/11652097921
- Artifact: `br-artcraft-seven-source-study`, 94,655,027 bytes, SHA-256 of GitHub artifact `9437fb46ba6ba25d16443aeac4185e26c46ee86ee76a58be9d97a7d7bac7e3e0`
- Artifact expires: **2026-11-09 00:35:19 UTC** (download or copy to approved persistent storage before then).
- Source archives: 7, audited via `sha256sum -c` after creation; 7,200 pinned upstream tracked entries, 94,653,579 total package bytes including manifest and notes.
- No third-party binaries built/executed. No LFS fetch, submodule checkout, upstream hooks, privileged tokens, deployment, A15 computation, main/V24/canonical changes.
- License metadata and upstream `LICENSE`/equivalent validated as **Apache-2.0** on all seven pinned commits.
- These are **clean-room reimplementations** as advertised by upstream; this report does *not* claim verified decompilation of Adobe executables or production feature parity.

## Source inventory

| Application | Exact source commit | Tracked entries | Source tar.gz bytes |
|---|---|---:|---:|
| [PhotoCraft](https://github.com/storytold/photocraft) | `69b1379781a4d7e12774b9768cab44b35db6231b` | 1355 | 15774653 |
| [VectorCraft](https://github.com/storytold/vectorcraft) | `866ea5878a7f6db7dd3d6b1287f9a9bb3a241c33` | 1482 | 14261131 |
| [FilmCraft](https://github.com/storytold/filmcraft) | `7b6c134472287db4367fca80bcb498240ba36567` | 1132 | 18894093 |
| [LightCraft](https://github.com/storytold/lightcraft) | `88ea1a804b35709e1fe436e3792adf0428b97daa` | 655 | 14821273 |
| [PdfCraft](https://github.com/storytold/pdfcraft) | `c110c579a24800bb841b5d643e2e34e161e81f13` | 1210 | 12854635 |
| [EffectCraft](https://github.com/storytold/effectcraft) | `30aaddf7c23329dcdfc72a5bf65b55747bbd6be1` | 971 | 10766900 |
| [DesignCraft](https://github.com/storytold/designcraft) | `66c7ce7e96ec286a091878cc2541ee8369aa79d6` | 395 | 7276222 |

`docs/research/artcraft-seven-pinned-sources.json` is the permanent manifest for reproducing this exact snapshot set. The artifact contains seven `.tar.gz` files, source manifest, instructions and `SHA256SUMS.txt`. GitHub Actions artifacts expire; Git upstream refs may change.

## Proposed reverse-engineering study sequence — no execution authorization

1. **FilmCraft**: audit timeline model, media import, project serialization, FFmpeg bindings, transport, render graph, cache and export boundaries. Compare under synthetic open-media fixtures rather than asserting Premiere parity.
2. **EffectCraft**: reconstruct composition / scene graph, keyframe evaluator, GPU / CPU effect pipeline, caching, graph determinism and bridge to FilmCraft.
3. **PhotoCraft**: identify layer graph, masks, raster/color pipeline, PSD parsing and export; inspect codec/format security, decoding limits and fidelity.
4. **VectorCraft**: path operations, bezier evaluation, text/shaping, scene transforms, serialization and SVG import/export.
5. **LightCraft**: RAW decoding and non-destructive edit history, metadata integrity and color-management checks.
6. **PdfCraft**: document object graph, parser sandbox boundaries, page rendering, annotations and external resource access.
7. **DesignCraft**: document layouts, text flow, font licensing, rendering/pagination and interoperable exports.

Keep sources under an isolated, read-only investigation plane; capture provenance per source file and exact commit. Prefer black-box experiments with self-authored fixtures only **after** review. Do not copy license or code into the production BR pipeline without attribution, legal/security review and boundary tests. Never assume readiness based on README marketing claims. The Harness remains sole decision authority. Any production integration must be a distinct approved candidate with technical and human quality gates.
