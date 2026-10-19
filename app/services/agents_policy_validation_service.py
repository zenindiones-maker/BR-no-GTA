from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re


_REF_RE = re.compile(
    r"(?:Required:|Mandatory:|Canonical:|See:|Policy:|Registry:)\s*\x60?([A-Za-z0-9_./-]+\.(?:md|py|html|json|yml|yaml))\x60?",
    re.I,
)

# Content binding: "Policy: `docs/policy/x.md` (sha256 <hex>)" pins the exact
# bytes of a policy document moved out of AGENTS.md (owner authorizations stay
# verbatim and cannot be edited silently).
_BINDING_RE = re.compile(
    r"Policy:\s*\x60?([A-Za-z0-9_./-]+\.md)\x60?\s*\(sha256\s+([0-9a-f]{64})\)",
)

_CONFLICT_PATTERNS = (
    "agent is final authority",
    "agent is sole authority",
    "skill is authority",
    "worker is final authority",
    "another coordinator is the sole authority",
)


@dataclass(frozen=True)
class AgentsPolicyValidation:
    status: str
    line_count: int
    broken_references: tuple[str, ...]
    stale_mandatory_references: tuple[str, ...]
    authority_conflicts: tuple[str, ...]
    missing_mandatory_references: tuple[str, ...] = ()
    content_binding_mismatches: tuple[str, ...] = ()
    schema: str = "AgentsPolicyValidation/v1"

    @property
    def root_line_count(self) -> int:
        return self.line_count

    @property
    def conflicting_authority_instructions(self) -> tuple[str, ...]:
        return self.authority_conflicts


def _authority_conflicts(text: str, *, source: str) -> tuple[str, ...]:
    lowered = text.lower()
    harness_is_sole = (
        "harness is sole authority" in lowered
        or "harness = sole authority" in lowered
        or "deepseek harness is the sole control plane" in lowered
        or ("deepseek harness" in lowered and "sole authority" in lowered)
    )
    if not harness_is_sole and source == "AGENTS.md":
        return ()
    return tuple(
        f"{source}:{pattern}"
        for pattern in _CONFLICT_PATTERNS
        if pattern in lowered
    )


def validate_agents_policy(
    repo_root: Path,
    agents_path: Path | None = None,
    *,
    mandatory_references: tuple[str, ...] | None = None,
) -> AgentsPolicyValidation:
    root = Path(repo_root).resolve()
    agents = Path(agents_path) if agents_path is not None else root / "AGENTS.md"
    text = agents.read_text(encoding="utf-8")

    discovered = tuple(dict.fromkeys(m.group(1) for m in _REF_RE.finditer(text)))
    mandatory = tuple(dict.fromkeys(mandatory_references or discovered))
    refs = tuple(dict.fromkeys((*discovered, *mandatory)))

    broken = tuple(ref for ref in refs if not (root / ref).exists())
    missing_mandatory = tuple(ref for ref in mandatory if not (root / ref).exists())
    stale = tuple(
        ref for ref in mandatory
        if "deprecated" in ref.lower() or "legacy/" in ref.lower()
    )

    conflicts = list(_authority_conflicts(text, source="AGENTS.md"))
    for ref in mandatory:
        target = root / ref
        if not target.is_file():
            continue
        try:
            referenced = target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        conflicts.extend(_authority_conflicts(referenced, source=ref))

    mismatched: list[str] = []
    for match in _BINDING_RE.finditer(text):
        ref, expected = match.group(1), match.group(2)
        target = root / ref
        try:
            actual = hashlib.sha256(target.read_bytes()).hexdigest()
        except OSError:
            actual = ""
        if actual != expected:
            mismatched.append(ref)

    lines = len(text.splitlines())
    status = (
        "PASS"
        if lines <= 100
        and not broken
        and not missing_mandatory
        and not stale
        and not conflicts
        and not mismatched
        else "FAIL"
    )
    return AgentsPolicyValidation(
        status=status,
        line_count=lines,
        broken_references=broken,
        stale_mandatory_references=stale,
        authority_conflicts=tuple(dict.fromkeys(conflicts)),
        missing_mandatory_references=missing_mandatory,
        content_binding_mismatches=tuple(dict.fromkeys(mismatched)),
    )
