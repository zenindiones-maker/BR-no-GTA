from __future__ import annotations

import hashlib
import re

from bs4 import BeautifulSoup
from dataclasses import dataclass


@dataclass(frozen=True)
class GTA6ChangeResult:
    changed: bool
    previous_hash: str | None
    current_hash: str


def normalize_monitored_content(content: str) -> str:
    """Normaliza conteúdo antes da comparação."""

    if not isinstance(content, str):
        raise ValueError("content must be a string")

    normalized = content
    lowered = content.lower()
    if "<script" in lowered or "<style" in lowered:
        soup = BeautifulSoup(content, "lxml")

        for style in soup.find_all("style"):
            style.decompose()

        for script in soup.find_all("script"):
            script_type = str(script.get("type") or "").strip().lower()
            if script_type != "application/ld+json":
                script.decompose()

        normalized = soup.decode(formatter="minimal")

    normalized = re.sub(r"\s+", " ", normalized)

    return normalized.strip()


def hash_monitored_content(content: str) -> str:
    """Calcula SHA-256 do conteúdo normalizado."""

    normalized = normalize_monitored_content(content)

    return hashlib.sha256(
        normalized.encode("utf-8")
    ).hexdigest()


def detect_content_change(
    content: str,
    previous_hash: str | None,
) -> GTA6ChangeResult:
    """Compara o conteúdo atual com o hash anteriormente observado."""

    current_hash = hash_monitored_content(content)

    if previous_hash is None:
        return GTA6ChangeResult(
            changed=True,
            previous_hash=None,
            current_hash=current_hash,
        )

    if not isinstance(previous_hash, str) or not previous_hash.strip():
        raise ValueError(
            "previous_hash must be a non-empty string or None"
        )

    return GTA6ChangeResult(
        changed=current_hash != previous_hash,
        previous_hash=previous_hash,
        current_hash=current_hash,
    )
