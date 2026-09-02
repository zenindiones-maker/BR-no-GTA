from __future__ import annotations

import hashlib
import re
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
    json_ld_blocks: list[str] = []

    def preserve_json_ld(match: re.Match[str]) -> str:
        json_ld_blocks.append(match.group(0))
        return f"__GTA6_JSON_LD_{len(json_ld_blocks) - 1}__"

    normalized = re.sub(
        r'<script\b[^>]*type=["\']application/ld\+json["\'][^>]*>.*?</script>',
        preserve_json_ld,
        normalized,
        flags=re.IGNORECASE | re.DOTALL,
    )

    normalized = re.sub(
        r"<script\b[^>]*>.*?</script>",
        "",
        normalized,
        flags=re.IGNORECASE | re.DOTALL,
    )

    normalized = re.sub(
        r"<style\b[^>]*>.*?</style>",
        "",
        normalized,
        flags=re.IGNORECASE | re.DOTALL,
    )

    for index, block in enumerate(json_ld_blocks):
        normalized = normalized.replace(
            f"__GTA6_JSON_LD_{index}__",
            block,
        )

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
