from __future__ import annotations

import json
from pathlib import Path
import re

from app.services.channel_spoken_branding_service import (
    OFFICIAL_VOICE_IDENTITY_ID,
    build_spoken_branding_contract,
)

ROOT = Path(__file__).resolve().parents[1]
OWNER_IDENTITY = "BR_OWNER_V1"

LEGACY_TERMS = (
    "Voice B",
    "Voice C",
    "pt-BR-ThalitaMultilingualNeural",
    "Thalita",
    "G-brand-mixed",
)

FORBIDDEN_EXACT_ACTIVE_PATHS = (
    "assets/branding/audio/closing-from-g-approved-20260919.flac",
    "assets/branding/audio/g-brand-mixed-approved-20260919.mp3",
    "assets/branding/audio/human-approval-manifest.json",
)

RETIRED_WORKFLOWS = {
    ".github/workflows/run001-longform-video-a.yml",
}


def _workflow_script_edges() -> list[tuple[str, str]]:
    edges=[]
    for workflow in sorted((ROOT / ".github" / "workflows").glob("*.y*ml")):
        rel=workflow.relative_to(ROOT).as_posix()
        text=workflow.read_text(encoding="utf-8")
        if rel in RETIRED_WORKFLOWS or "— RETIRED" in text:
            continue
        for match in re.finditer(r"(scripts/[A-Za-z0-9_./-]+\.py)", text):
            script=match.group(1)
            if (ROOT / script).is_file():
                edges.append((rel,script))
    return sorted(set(edges))


def _active_legacy_bindings() -> list[dict[str,str]]:
    findings=[]
    for workflow,script in _workflow_script_edges():
        text=(ROOT / script).read_text(encoding="utf-8",errors="replace")
        for term in LEGACY_TERMS:
            if re.search(rf"(?<![A-Za-z0-9_]){re.escape(term)}(?![A-Za-z0-9_])", text, flags=re.IGNORECASE):
                findings.append({"workflow":workflow,"script":script,"term":term})
    return findings


def test_only_owner_voice_exists_in_current_contract():
    enrollment=json.loads((ROOT/"config"/"voice_owner_enrollment_v1.json").read_text(encoding="utf-8"))
    contract=build_spoken_branding_contract(theme="fatos, tecnologia e novidades de GTA 6")
    assert OFFICIAL_VOICE_IDENTITY_ID == OWNER_IDENTITY
    assert enrollment["official_voice"] == OWNER_IDENTITY
    assert enrollment["official_voice_identity"] == OWNER_IDENTITY
    assert enrollment["active_voice_identities"] == [OWNER_IDENTITY]
    assert enrollment["provider_preset_voice_allowed"] is False
    assert enrollment["provider_default_voice_allowed"] is False
    assert enrollment["generic_voice_fallback"] is False
    assert contract["official_voice_profile"] == OWNER_IDENTITY
    assert contract["voice_short_name"] == OWNER_IDENTITY


def test_active_runtime_has_no_legacy_voice_bindings():
    existing=[path for path in FORBIDDEN_EXACT_ACTIVE_PATHS if (ROOT/path).exists()]
    findings=_active_legacy_bindings()
    assert existing == [], f"active legacy voice assets remain: {existing}"
    assert findings == [], f"active workflow legacy voice bindings remain: {findings}"


def test_retired_longform_voice_path_is_unreachable_from_active_runtime():
    text=(ROOT/".github/workflows/run001-longform-video-a.yml").read_text(encoding="utf-8")
    assert "— RETIRED" in text
    assert "LEGACY_VOICE_WORKFLOW=RETIRED" in text
    assert "OFFICIAL_VOICE=BR_OWNER_V1" in text
    assert "GENERIC_VOICE_FALLBACK=0" in text
    assert "scripts/run001_longform_editorial_controller.py" not in text
    assert "actions/workflows/render-worker.yml/dispatches" not in text


def test_history_documentation_and_tests_are_not_runtime_bindings():
    edges=_workflow_script_edges()
    assert edges
    assert all(not script.startswith(("tests/","docs/",".checkpoints/history/")) for _,script in edges)


def test_new_production_has_no_old_provider_binding_or_fallback():
    branding=(ROOT/"app/services/channel_spoken_branding_service.py").read_text(encoding="utf-8")
    narration=(ROOT/"app/services/narration_pipeline.py").read_text(encoding="utf-8")
    assert "EdgeTTSProvider" not in narration
    assert 'PROVIDER_ID = "edge-tts"' not in narration
    assert "provider or EdgeTTSProvider()" not in narration
    assert OWNER_IDENTITY in branding
    assert OWNER_IDENTITY in narration
