from __future__ import annotations

import builtins
from pathlib import Path

from app.services.telegram_obsidian_attachment_bridge_service import (
    DEFAULT_LOCAL_NORMALIZATION_MAX_BYTES,
    DEFAULT_NORMALIZED_OUTPUT_MAX_BYTES,
    _normalize_local_text,
)

ROOT = Path(__file__).resolve().parents[1]


def _normalize(path: Path):
    return _normalize_local_text(
        path,
        max_input_bytes=DEFAULT_LOCAL_NORMALIZATION_MAX_BYTES,
        max_output_bytes=DEFAULT_NORMALIZED_OUTPUT_MAX_BYTES,
    )


def test_a15_dependency_profile_excludes_markitdown_and_psutil():
    content = (ROOT / "requirements" / "a15-telegram.txt").read_text(
        encoding="utf-8"
    ).casefold()
    assert "markitdown" not in content
    assert "psutil" not in content


def test_local_text_formats_work_when_markitdown_is_absent(monkeypatch, tmp_path):
    real_import = builtins.__import__
    def blocked_import(name, *args, **kwargs):
        if name == "markitdown" or name.startswith("markitdown."):
            raise ModuleNotFoundError("markitdown absent on Android")
        return real_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", blocked_import)

    fixtures = {
        ".html": ("<h1>BR_A15_HTML</h1><p>fallback</p>", "STDLIB_HTML_FALLBACK", "BR_A15_HTML"),
        ".txt": ("BR_A15_TXT\nplain", "STDLIB_TEXT_FALLBACK", "BR_A15_TXT"),
        ".md": ("# BR_A15_MD", "STDLIB_TEXT_FALLBACK", "BR_A15_MD"),
        ".csv": ("name,value\nBR_A15_CSV,1", "STDLIB_TEXT_FALLBACK", "BR_A15_CSV"),
        ".json": ('{"sentinel":"BR_A15_JSON"}', "STDLIB_TEXT_FALLBACK", "BR_A15_JSON"),
        ".xml": ("<root>BR_A15_XML</root>", "STDLIB_TEXT_FALLBACK", "BR_A15_XML"),
    }
    for suffix, (payload, engine, sentinel) in fixtures.items():
        path = tmp_path / f"fixture{suffix}"
        path.write_text(payload, encoding="utf-8")
        normalized, state, observed_engine, diagnostic = _normalize(path)
        assert state == "LOCAL_TEXT_NORMALIZED"
        assert observed_engine == engine
        assert sentinel in normalized
        assert "markitdown=ModuleNotFoundError" in str(diagnostic)


def test_rich_documents_are_cloud_required_before_optional_local_converter(tmp_path):
    for suffix in (".pdf", ".docx", ".pptx", ".xlsx"):
        path = tmp_path / f"fixture{suffix}"
        path.write_bytes(b"rich-document")
        normalized, state, engine, diagnostic = _normalize(path)
        assert normalized is None
        assert state == "CLOUD_REQUIRED"
        assert engine is None
        assert diagnostic is None
