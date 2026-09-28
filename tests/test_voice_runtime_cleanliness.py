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


def _chars(*values: int) -> str:
    return "".join(chr(value) for value in values)


# Encoded so this gate can scan its own source without self-matching.
FORBIDDEN_CURRENT_TREE_TERMS = (
    _chars(86, 111, 105, 99, 101, 32, 66),
    _chars(86, 111, 105, 99, 101, 32, 67),
    _chars(112, 116, 45, 66, 82, 45, 84, 104, 97, 108, 105, 116, 97, 77, 117, 108, 116, 105, 108, 105, 110, 103, 117, 97, 108, 78, 101, 117, 114, 97, 108),
    _chars(84, 104, 97, 108, 105, 116, 97),
    _chars(118, 111, 105, 99, 101, 45, 98, 45, 99, 111, 110, 116, 114, 111, 108),
    _chars(71, 45, 98, 114, 97, 110, 100, 45, 109, 105, 120, 101, 100),
    _chars(73, 45, 111, 112, 101, 110, 105, 110, 103, 45, 102, 108, 117, 105, 100, 45, 50),
    _chars(70, 108, 117, 105, 100, 32, 50),
    _chars(116, 97, 107, 101, 45, 50),
    _chars(86, 79, 73, 67, 69, 95, 66),
    _chars(86, 79, 73, 67, 69, 95, 67),
    _chars(118, 111, 105, 99, 101, 95, 98),
    _chars(118, 111, 105, 99, 101, 95, 99),
)

BOUNDARY_FORBIDDEN_TERMS = (
    FORBIDDEN_CURRENT_TREE_TERMS[0],
    FORBIDDEN_CURRENT_TREE_TERMS[1],
    FORBIDDEN_CURRENT_TREE_TERMS[-4],
    FORBIDDEN_CURRENT_TREE_TERMS[-3],
    FORBIDDEN_CURRENT_TREE_TERMS[-2],
    FORBIDDEN_CURRENT_TREE_TERMS[-1],
)

FORBIDDEN_EXACT_PATHS = (
    "assets/branding/audio/closing-from-g-approved-20260919.flac",
    "assets/branding/audio/" + "g-" + "brand-mixed-approved-20260919.mp3",
    "assets/branding/audio/human-approval-manifest.json",
    ".github/workflows/send-official-voice-proof.yml",
    ".github/workflows/promote-human-approved-brand-audio.yml",
    ".github/workflows/video-a-brand-audio-checkpoint.yml",
    ".github/workflows/video-a-narration-fluency-proof.yml",
    ".github/workflows/video-a-narration-readiness-audition.yml",
    "scripts/voice_bc_character_review.py",
    "tests/test_voice_bc_character_review.py",
    ".run001/official-narration-profile.json",
    ".run001/promote-human-approved-brand-audio.request.json",
    ".run001/send-official-voice-proof.request.json",
    ".run001/video-a-brand-audio.request.json",
    ".run001/video-a-final-audio-approval.json",
    ".run001/narration-optimization.request.json",
    ".run001/pronunciation-proof.request.json",
    ".run001/character-name-pronunciation-proof.request.json",
    "config/pronunciation_character_aliases.bc-review.json",
    "config/pronunciation_character_aliases.candidate.json",
)


def _iter_checkout_files():
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT)
        if ".git" in rel.parts or "runtime" in rel.parts:
            continue
        yield rel, path


def _contains_forbidden(value: str, term: str) -> bool:
    if term in BOUNDARY_FORBIDDEN_TERMS:
        return re.search(
            rf"(?<![A-Za-z0-9_]){re.escape(term)}(?![A-Za-z0-9_])",
            value,
            flags=re.IGNORECASE,
        ) is not None
    return term.casefold() in value.casefold()


def _scan_current_tree() -> list[dict[str, str]]:
    matches: list[dict[str, str]] = []
    for rel, path in _iter_checkout_files():
        rel_text = rel.as_posix()
        for term in FORBIDDEN_CURRENT_TREE_TERMS:
            if _contains_forbidden(rel_text, term):
                matches.append({"path": rel_text, "term": term, "location": "path"})
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for term in FORBIDDEN_CURRENT_TREE_TERMS:
            if _contains_forbidden(text, term):
                matches.append({"path": rel_text, "term": term, "location": "content"})
    return matches


def test_only_owner_voice_exists_in_current_tree():
    enrollment = json.loads(
        (ROOT / "config" / "voice_owner_enrollment_v1.json").read_text(encoding="utf-8")
    )
    contract = build_spoken_branding_contract(
        theme="fatos, tecnologia e novidades de GTA 6"
    )

    assert OFFICIAL_VOICE_IDENTITY_ID == OWNER_IDENTITY
    assert enrollment["official_voice"] == OWNER_IDENTITY
    assert enrollment["official_voice_identity"] == OWNER_IDENTITY
    assert contract["official_voice_profile"] == OWNER_IDENTITY
    assert contract["voice_short_name"] == OWNER_IDENTITY
    assert [OWNER_IDENTITY] == [OFFICIAL_VOICE_IDENTITY_ID]


def test_legacy_voice_artifacts_and_references_are_absent_from_current_tree():
    existing = [path for path in FORBIDDEN_EXACT_PATHS if (ROOT / path).exists()]
    matches = _scan_current_tree()
    assert existing == [], f"forbidden legacy paths remain: {existing}"
    assert matches == [], f"legacy current-tree matches remain: {matches}"


def test_new_production_has_no_old_provider_binding_or_fallback():
    branding = (ROOT / "app" / "services" / "channel_spoken_branding_service.py").read_text(
        encoding="utf-8"
    )
    narration = (ROOT / "app" / "services" / "narration_pipeline.py").read_text(
        encoding="utf-8"
    )

    assert "LEGACY_" not in branding
    assert "legacy_" not in branding
    assert "EdgeTTSProvider" not in narration
    assert 'PROVIDER_ID = "edge-tts"' not in narration
    assert "provider or EdgeTTSProvider()" not in narration
    assert OWNER_IDENTITY in branding
    assert OWNER_IDENTITY in narration
