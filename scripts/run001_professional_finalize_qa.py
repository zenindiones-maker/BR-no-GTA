from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"{path.name} must contain an object")
    return value


def single_folder(root: Path) -> Path:
    matches = [path.parent for path in root.rglob("*.mp4") if path.is_file()]
    unique = sorted(set(matches))
    if len(unique) != 1:
        raise RuntimeError(f"expected one professional render folder, found {len(unique)}")
    return unique[0]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-root", required=True)
    args = parser.parse_args()
    folder = single_folder(Path(args.artifact_root))
    job = load(folder / "render-job.json")
    if job.get("product_profile") != "professional_ptbr_v1":
        print("PROFESSIONAL_FINAL_QA=SKIPPED")
        return 0
    gates = {
        "EDITORIAL_QA": load(folder / "editorial-qa.json").get("status"),
        "VOICE_QA": load(folder / "voice-qa.json").get("status"),
        "EDIT_QA": load(folder / "edit-qa.json").get("status"),
    }
    semantic = load(folder / "semantic-ptbr-audio-qa.json")
    semantic_required = (
        "NARRATION_PRESENT",
        "SPOKEN_AUDIO_PT_BR",
        "NARRATION_NONEMPTY",
        "NARRATION_DURATION_VALID",
        "AUDIO_TIMELINE_ALIGNMENT",
        "FINAL_MIX_CONTAINS_PT_BR_NARRATION",
    )
    semantic_ok = (
        semantic.get("status") == "PASS"
        and semantic.get("TARGET_LANGUAGE") == "pt-BR"
        and semantic.get("FINAL_AUDIO_LANGUAGE_METADATA") == "pt-BR"
        and all(semantic.get(key) == "PASS" for key in semantic_required)
    )
    gates["SEMANTIC_PTBR_QA"] = "PASS" if semantic_ok else "FAIL"

    render_qa = load(folder / "render-qa.json")
    if render_qa.get("status") != "PASS":
        raise RuntimeError("final branded render QA is not PASS")
    branding = render_qa.get("branding")
    if not isinstance(branding, dict):
        raise RuntimeError("final branded render lacks branding evidence")
    gates["AUDIOVISUAL_QA"] = "PASS"
    gates["INTRO_QA"] = "PASS" if branding.get("intro_duration_seconds", 0) > 0 else "FAIL"
    gates["WATERMARK_QA"] = (
        "PASS"
        if branding.get("watermark_start_seconds") == branding.get("intro_duration_seconds")
        and branding.get("watermark_position") == "BOTTOM_RIGHT"
        and branding.get("watermark_applied_to") == "CONTENT_ONLY"
        else "FAIL"
    )
    if any(value != "PASS" for value in gates.values()):
        raise RuntimeError(f"professional final QA failed: {gates}")
    final = dict(render_qa)
    final.update(
        status="PASS",
        stage="professional_final_branded",
        product_label=job.get("product_label"),
        product_version=job.get("product_version"),
        gates=gates,
        spoken_audio_language="pt-BR",
        spoken_audio_semantic_qa=semantic,
        human_editorial_approval="PENDING",
        youtube_publication_authority="BLOCKED_PENDING_HUMAN_APPROVAL",
    )
    (folder / "audiovisual-qa.json").write_text(
        json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("PROFESSIONAL_FINAL_QA=PASS")
    for key in (
        "EDITORIAL_QA", "VOICE_QA", "EDIT_QA", "SEMANTIC_PTBR_QA",
        "AUDIOVISUAL_QA", "INTRO_QA", "WATERMARK_QA",
    ):
        print(f"VIDEO_{job.get('product_label')}_{key}=PASS")
    print("TARGET_LANGUAGE=pt-BR")
    print("SPOKEN_AUDIO_PT_BR=PASS")
    print("FINAL_MIX_CONTAINS_PT_BR_NARRATION=PASS")
    print("HUMAN_EDITORIAL_APPROVAL=PENDING")
    print("YOUTUBE_PUBLICATION=BLOCKED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
