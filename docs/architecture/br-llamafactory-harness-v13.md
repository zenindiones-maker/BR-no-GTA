# BR-no-GTA — LLaMA-Factory admission plane V13

**Implementation:** isolated branch only; no merge, no production runtime modification, no Qwen3-TTS voice retraining, no GPU billing, and no downloaded model weights.

## Confirmed provider and provenance

- Official upstream: https://github.com/hiyouga/LlamaFactory, Apache-2.0.
- Pinned official commit: `ce9dc9e072f80fa3abe0989d4ab90da25f083438`.
- Python >=3.11 and the documented CLI entrypoint `llamafactory-cli` are defined in the upstream `pyproject.toml`.
- The original LLaMA-Factory project fine-tunes supported language and vision-language models, including Qwen3; it is **not** the Qwen3-TTS 12Hz owner-voice training pipeline.
- Dedicated official TTS flow: https://github.com/QwenLM/Qwen3-TTS/blob/main/finetuning/README.md . The same authorized reference recording for every SFT sample is recommended to improve stability; any voice training still requires separate consent, security review and owner hearing.

## V13 installed vs active: status truth table

| Capability level | Status |
| --- | --- |
| Official source retrieved, exact Git SHA verified | CI evidence required |
| Package installed in ephemeral Python venv without heavy dependencies | CI evidence required |
| Private textual dataset JSONL schema and model allowlist checked | V13 Harness RESEARCH adapter with real authorization |
| Full LLaMA-Factory dependencies installed on persistent dedicated GPU worker | **NOT DONE** |
| Runtime/GPU/VRAM cost and model license audited for a real train | **NOT DONE** |
| Model successfully fine-tuned and independently evaluated | **NOT DONE** |
| Qwen3-TTS clone identity improved | **NOT DONE** |
| Harness/PR #17 promoted into production | **NOT DONE** |

## Implemented contracts

1. `integrations/install_llamafactory_v13_isolated.sh` clones the official upstream into a new temporary private directory, checks out a fixed commit and verifies actual Git readback, Apache package metadata and Python >=3.11. It installs the source package with `pip --no-deps -e` into an isolated venv and checks installed metadata. It deliberately does not load an LLM or claim the CLI training stack can run.
2. `app/services/br_llamafactory_training_admission_v13.py` accepts only owned, absolute, scoped Alpaca JSONL text (`instruction`, `input`, `output`), limits file size and number of examples, checks a Qwen3-0.6B model allowlist, refuses biometrics and credential-like markers, and issues a deterministic hash receipt. This is **schema validation**, not a proof of data correctness, lack of PII, licensing or semantic quality.
3. `app/services/br_llamafactory_harness_gate_v13.py` requires real persisted DeepSeek Harness RESEARCH authorization, exact executor binding, and no mutation flags. Registry capabilities are distinct from an actual trained model; they cannot access BR_OWNER_V1, promote learning or publish.
4. CI installs package metadata from the pinned official commit and exercises both positive and negative synthetic owner-dataset controls. No private voice content is passed to CI, provider or artifacts.

## Suggested future operational pathway, not yet activated

First build an owner-reviewed clean dataset of grounded editorial and code/reverse-engineering research examples; separate train/validation/test by source and video episode, with citation and rights provenance. Perform leak prevention and human quality labels. Then secure a zero-cost authorized workstation with hardware attestation, full package installation and an isolated reproducible baseline inference. Compare baseline versus LoRA with a blinded hold-out set and negative examples, measuring factuality, source attribution, hallucination, instruction resistance, cost, speed and failure rates. Publish only an approved evaluated adapter with exact SHA and rollback.

Maintain Qwen3-TTS 1.7B Base for `BR_OWNER_V1` in its own owner-authorized pipeline. Voice candidate 666 and later reported candidate from run 37808729277 failed identity and pronunciation thresholds; the latter also lacked confirmed Telegram delivery because the audition ledger push was rejected. Installing LLaMA-Factory does not repair either voice identity or delivery.

## User interface

ChatGPT GPT-6 supports conversational charts, diagrams and interactive controls in responses. Those ChatGPT features are not a model-management API and do not install a UI into the BR-no-GTA repository. For a Harness dashboard, render signed/grounded server-side evidence models with clear states (registered / installed / tested / authorized / ready / blocked), never user-supplied PASS strings, and no actions that bypass release gates.

References: https://llamafactory.readthedocs.io/en/latest/getting_started/sft.html ; https://github.com/hiyouga/LlamaFactory ; https://github.com/QwenLM/Qwen3-TTS/blob/main/finetuning/README.md
