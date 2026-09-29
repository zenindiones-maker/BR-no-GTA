import json
from pathlib import Path

from app.services.pronunciation_service import (
    DEFAULT_LOCALE,
    DEFAULT_VOICE,
    resolve_synthesis_plan,
)

ROOT = Path(__file__).resolve().parents[1]
PRODUCTION = ROOT / "config" / "pronunciation_lexicon.json"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_production_pronunciation_policy_is_owner_only_ptbr():
    data = load(PRODUCTION)
    assert data["default_locale"] == "pt-BR"
    assert data["policy"]["foreign_language_chunks_forbidden"] is True
    assert data["policy"]["character_name_en_us_chunks_forbidden"] is True
    assert data["policy"]["all_pronunciation_synthesis_locale"] == "pt-BR"
    assert DEFAULT_VOICE == "BR_OWNER_V1"
    assert DEFAULT_LOCALE == "pt-BR"
    assert all(entry["locale"] == "pt-BR" for entry in data["entries"])


def test_synthesis_aliases_preserve_canonical_text_and_owner_lane():
    text = "Lucia atravessa Vice City em Leonida."
    plan = resolve_synthesis_plan(text)
    assert plan.canonical_text == text
    assert plan.canonical_text_preserved is True
    assert plan.voice == "BR_OWNER_V1"
    assert plan.default_locale == "pt-BR"
    assert plan.foreign_span_count == 0
    assert all(span.locale == "pt-BR" for span in plan.spans)
    assert "Lucía" in plan.rendered_text
    assert "Váis Síti" in plan.rendered_text
    assert "Leônida" in plan.rendered_text


def test_vice_city_target_sound_does_not_create_foreign_language_chunk():
    plan = resolve_synthesis_plan("A ação continua em Vice City.")
    vice = [
        span for span in plan.spans
        if span.pronunciation_identity == "vice-city"
    ]
    assert len(vice) == 1
    assert vice[0].locale == "pt-BR"
    assert vice[0].synthesis_text == "Váis Síti"
    assert plan.foreign_span_count == 0


def test_only_current_human_governed_aliases_are_in_production_lexicon():
    data = load(PRODUCTION)
    entries = {entry["identity"]: entry for entry in data["entries"]}
    assert "character-jason" not in entries
    assert entries["character-lucia"]["locale"] == "pt-BR"
    assert entries["character-lucia"]["strategy"] == "alias"
    assert entries["character-lucia"]["synthesis_text"] == "Lucía"
    assert "human-approved synthesis-only alias" in entries["character-lucia"]["source"]
