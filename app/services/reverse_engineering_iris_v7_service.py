"""Pinned Iris 0.4.1 *local visual camera* behind the DeepSeek Harness.

This adapter executes one camera CLI, not Iris's free-ranging MCP server.
Only locally authored, safe-subset static HTML is in scope. Do not pass
third-party HTML: HTML syntax checks are not a security sandbox.
Live HTTP(S), loopback servers and authenticated browsing are forbidden until
network egress isolation has been independently proved.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from app.services.reverse_engineering_media_service import ObservationError, _sha256, _source

SCHEMA = "BRIrisVisionObservation/v1"
IRIS_VERSION = "iris 0.4.1"
MAX_SOURCE_BYTES = 150_000
MAX_PNG_BYTES = 6_000_000
MAX_SELECTOR_CHARS = 100
_ALLOWED_TAGS = frozenset({
    "html", "head", "body", "title", "style", "meta", "main", "header",
    "footer", "section", "article", "aside", "nav", "div", "span", "p",
    "h1", "h2", "h3", "h4", "h5", "h6", "strong", "em", "small", "b",
    "i", "ul", "ol", "li", "button", "label", "figure", "figcaption",
})
_ALLOWED_ATTRS = frozenset({"class", "id", "lang", "dir", "role", "aria-label", "title", "charset"})
_SELECTOR = re.compile(r"^[#.A-Za-z0-9_ \->:+*,\[\]=\"']{1,100}$")
_BANNED_CSS = re.compile(r"(?i)\\|@|url\s*\(|image-set\s*\(|src\s*:|expression\s*\(|behavior\s*:")
_ALLOWED_MEDIA_QUERY = re.compile(r"(?i)@media\s*\(\s*prefers-color-scheme\s*:\s*(?:dark|light)\s*\)")
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


class _StaticMarkupGuard(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_style = False
        self.has_root = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in _ALLOWED_TAGS:
            raise ObservationError("IRIS_LOCAL_HTML_ACTIVE_OR_UNSUPPORTED_TAG")
        if tag == "html":
            self.has_root = True
        if tag == "style":
            self.in_style = True
        for key, value in attrs:
            if key not in _ALLOWED_ATTRS:
                raise ObservationError("IRIS_LOCAL_HTML_EXTERNAL_OR_ACTIVE_ATTRIBUTE")
            if key == "charset" and (tag != "meta" or str(value).lower() != "utf-8"):
                raise ObservationError("IRIS_LOCAL_HTML_META_INVALID")
            if value is None or len(value) > 150 or any(ord(c) < 32 for c in value):
                raise ObservationError("IRIS_LOCAL_HTML_ATTRIBUTE_INVALID")

    def handle_endtag(self, tag: str) -> None:
        if tag == "style":
            self.in_style = False

    def handle_data(self, data: str) -> None:
        css = _ALLOWED_MEDIA_QUERY.sub("", data) if self.in_style else data
        if self.in_style and _BANNED_CSS.search(css):
            raise ObservationError("IRIS_LOCAL_HTML_EXTERNAL_STYLES_FORBIDDEN")

    def handle_entityref(self, name: str) -> None:
        if self.in_style:
            raise ObservationError("IRIS_LOCAL_HTML_ENTITY_IN_CSS_FORBIDDEN")


def _owned_static_html(source: Path) -> None:
    if source.suffix.lower() != ".html" or source.stat().st_size > MAX_SOURCE_BYTES:
        raise ObservationError("IRIS_LOCAL_HTML_SIZE_OR_SUFFIX_INVALID")
    try:
        text = source.read_text(encoding="utf-8")
    except UnicodeError as exc:
        raise ObservationError("IRIS_LOCAL_HTML_ENCODING_INVALID") from exc
    if "<!doctype html" not in text[:80].casefold():
        raise ObservationError("IRIS_LOCAL_HTML_DOCTYPE_REQUIRED")
    guard = _StaticMarkupGuard()
    guard.feed(text)
    guard.close()
    if not guard.has_root:
        raise ObservationError("IRIS_LOCAL_HTML_ROOT_REQUIRED")


def _iris_path(explicit: str | Path) -> Path:
    binary = _source(explicit)
    if binary.name != "iris" or not os.access(binary, os.X_OK):
        raise ObservationError("IRIS_BINARY_UNAPPROVED")
    try:
        result = subprocess.run([str(binary), "--version"], text=True, capture_output=True,
                                timeout=8, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ObservationError("IRIS_VERSION_PROBE_FAILED") from exc
    if result.returncode or result.stdout.strip() != IRIS_VERSION:
        raise ObservationError("IRIS_VERSION_UNPINNED")
    return binary


def capture_owned_static_page(
    *, source_path: str | Path, output_path: str | Path, iris_binary: str | Path,
    size: str = "960x600", selector: str | None = None,
    full_page: bool = False, dark: bool = False, padding: int = 0,
    wait_for: str | None = None,
) -> dict[str, Any]:
    """Store a screenshot privately, and issue a bounded nonapproval evidence receipt."""
    if size not in ("960x600", "390x844"):
        raise ObservationError("IRIS_VIEWPORT_UNSUPPORTED")
    if type(full_page) is not bool or type(dark) is not bool:
        raise ObservationError("IRIS_MODE_FLAGS_INVALID")
    if full_page and selector is not None:
        raise ObservationError("IRIS_FULL_PAGE_SELECTOR_CONFLICT")
    if type(padding) is not int or not 0 <= padding <= 48 or (padding and selector is None):
        raise ObservationError("IRIS_PADDING_UNSUPPORTED")
    if wait_for is not None and (not isinstance(wait_for,str) or not _SELECTOR.fullmatch(wait_for)):
        raise ObservationError("IRIS_WAIT_FOR_UNSUPPORTED")
    if selector is not None and (
        not isinstance(selector, str) or not _SELECTOR.fullmatch(selector)
        or len(selector) > MAX_SELECTOR_CHARS
    ):
        raise ObservationError("IRIS_SELECTOR_UNSUPPORTED")
    source = _source(source_path, allowed_suffixes=(".html",))
    _owned_static_html(source)
    out = Path(output_path)
    if (not out.is_absolute() or out.suffix != ".png" or out.exists()
        or out.is_symlink() or not out.parent.is_dir() or out.parent.is_symlink()):
        raise ObservationError("IRIS_OUTPUT_NOT_NEW_PRIVATE_PNG")
    iris = _iris_path(iris_binary)
    # The ephemeral Iris-produced file is not trusted as evidence. Re-read and
    # validate before atomically creating the final private output in owner scope.
    with tempfile.TemporaryDirectory(prefix="br-iris-camera-") as temporary:
        stage = Path(temporary) / "shot.png"
        cmd = [
            str(iris), "--size", size, "--scale", "1", "--timeout", "15",
            "--json", "--jobs", "1", "-o", str(stage),
        ]
        if selector:
            cmd.extend(["--selector", selector])
            if padding:
                cmd.extend(["--padding", str(padding)])
        if full_page:
            cmd.append("--full")
        if dark:
            cmd.append("--dark")
        if wait_for:
            cmd.extend(["--wait-for", wait_for])
        cmd.append(source.as_uri())
        try:
            run = subprocess.run(cmd, capture_output=True, text=True,
                                 timeout=65, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ObservationError("IRIS_CAPTURE_UNAVAILABLE_OR_TIMEOUT") from exc
        if run.returncode or len(run.stdout) > 64_000:
            raise ObservationError("IRIS_CAPTURE_FAILED")
        lines = run.stdout.strip().splitlines()
        if len(lines) != 1:
            raise ObservationError("IRIS_CAPTURE_REPORT_INVALID")
        try:
            info = json.loads(lines[0])
        except (ValueError, TypeError) as exc:
            raise ObservationError("IRIS_CAPTURE_JSON_INVALID") from exc
        if (info.get("status") != "ok" or info.get("url") != source.as_uri()
            or info.get("format") != "png" or info.get("output") != str(stage)
            or info.get("mode") != ("element" if selector else "full_page" if full_page else "viewport")
            or (selector is not None and info.get("selector") != selector)
            or (selector is not None and padding and info.get("padding") != padding)):
            raise ObservationError("IRIS_CAPTURE_METADATA_MISMATCH")
        if not stage.is_file() or stage.is_symlink() or not 24 <= stage.stat().st_size <= MAX_PNG_BYTES:
            raise ObservationError("IRIS_CAPTURE_PNG_MISSING_OR_OVERSIZED")
        with stage.open("rb") as reader:
            data = reader.read(MAX_PNG_BYTES + 1)
        if len(data) > MAX_PNG_BYTES or not data.startswith(_PNG_MAGIC):
            raise ObservationError("IRIS_CAPTURE_PNG_CORRUPT")
        width = int.from_bytes(data[16:20], "big")
        height = int.from_bytes(data[20:24], "big")
        if (width <= 0 or height <= 0 or width * height > 6_000_000
            or width != info.get("css_width") or height != info.get("css_height")):
            raise ObservationError("IRIS_CAPTURE_DIMENSIONS_INVALID")
        fd = os.open(out, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            with os.fdopen(fd, "wb") as sink:
                sink.write(data)
        except BaseException:
            out.unlink(missing_ok=True)
            raise
    report: dict[str, Any] = {
        "schema_version": SCHEMA, "status": "MEASURED",
        "source_sha256": _sha256(source),
        "image_sha256": hashlib.sha256(data).hexdigest(),
        "image_bytes": len(data), "image_width": width, "image_height": height,
        "private_output_path": str(out),
        "capture_mode": "local_static_element" if selector else "local_static_full_page" if full_page else "local_static_viewport",
        "dark": dark, "padding": padding, "wait_for_used": wait_for is not None,
        "full_page": full_page,
        "iris_version": IRIS_VERSION, "iris_binary_sha256": _sha256(iris),
        "browser_rendered": True, "external_network_egress_verified_blocked": False,
        "live_website_capture": False, "mcp_registered": False,
        "private_data_redaction_verified": False, "artistic_quality_approved": False,
        "learning_write": "NOT_ATTEMPTED", "publication": "FORBIDDEN",
        "limitations": (
            "Only authorized, trusted static HTML; no network sandbox has been "
            "attested. Do not use for untrusted sites, authenticated content or live URLs."
        ),
    }
    report["evidence_sha256"] = hashlib.sha256(json.dumps(
        report, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode()).hexdigest()
    return report
