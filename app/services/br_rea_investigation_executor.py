"""Read-only, first-party REA source-dependency evidence under DeepSeek Harness.

This is NOT the ARTEX runtime and not a substitute for BR's historical REA.
It parses exact local BR source files; no subprocess, network, writes or imports
of analyzed source. A fresh persisted Harness decision is required per run.
"""
from __future__ import annotations

import ast
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any

from app.database.harness_authorization_repository import (
    consume_active_harness_authorization,
)
from app.services.harness_authorization_service import validate_harness_authorization
from app.services.br_rea_issuer_attestation_service import (
    verify_trusted_issuer_attestation,
)


CAPABILITY_ID = "reverse-engineering.evidence.inspect"
EVIDENCE_SCHEMA = "BRReaInvestigationEvidence/v1"
ROOT = Path(__file__).resolve().parents[2]
MAX_FILES = 8
MAX_BYTES = 256 * 1024
MAX_TOTAL_BYTES = 768 * 1024
ALLOWED_PREFIXES = ("app/services/", "app/database/", "scripts/")
EXCLUDED_PARTS = frozenset({
    "__pycache__", ".git", ".venv", ".local", "secrets", "secret",
    "private", "credentials", "credential", "tokens", "token", "keys", "key",
})


class InvestigationBlocked(PermissionError):
    """Deliberate deny; never forward raw filesystem paths or private text."""


@dataclass(frozen=True)
class InvestigationRequest:
    authorization_id: str
    harness_decision_id: str
    execution_id: str
    paths: tuple[str, ...]
    issuer_attestation: dict[str, Any]

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "InvestigationRequest":
        if not isinstance(payload, dict):
            raise InvestigationBlocked("Typed investigation payload required")
        if set(payload) != {"authorization_id", "harness_decision_id", "execution_id", "paths", "issuer_attestation"}:
            raise InvestigationBlocked("Unexpected investigation payload fields")
        ids = (payload.get("authorization_id"), payload.get("harness_decision_id"), payload.get("execution_id"))
        if any(not isinstance(value, str) or not value or len(value) > 128 for value in ids):
            raise InvestigationBlocked("Valid Harness lineage IDs required")
        paths = payload["paths"]
        if not isinstance(paths, (list, tuple)) or not 1 <= len(paths) <= MAX_FILES:
            raise InvestigationBlocked("Explicit bounded file list required")
        if any(not isinstance(path, str) or not path for path in paths):
            raise InvestigationBlocked("Paths must be nonempty strings")
        if len(set(paths)) != len(paths):
            raise InvestigationBlocked("Duplicate paths denied")
        proof = payload["issuer_attestation"]
        if not isinstance(proof, dict):
            raise InvestigationBlocked("Signed independent issuer proof required")
        return cls(*ids, tuple(paths), proof)


@dataclass(frozen=True)
class SourceObservation:
    path: str
    sha256: str
    size_bytes: int
    first_party_imports: tuple[dict[str, str], ...]


def _safe_components(relative: str) -> tuple[str, ...]:
    if (
        len(relative) > 180 or "\\" in relative or "\x00" in relative
        or relative.startswith("/") or not relative.endswith(".py")
        or not relative.startswith(ALLOWED_PREFIXES)
    ):
        raise InvestigationBlocked("Path outside authorized source scope")
    parts = tuple(relative.split("/"))
    if any(
        part in ("", ".", "..") or part.lower().split(".")[0] in EXCLUDED_PARTS
        for part in parts
    ):
        raise InvestigationBlocked("Path outside authorized source scope")
    return parts


def _read_scoped(root: Path, relative: str) -> bytes:
    """Anchor to trusted root and open every component without following links."""
    parts = _safe_components(relative)
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    file_flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0)
    descriptors: list[int] = []
    try:
        current = os.open(root, directory_flags)
        descriptors.append(current)
        for component in parts[:-1]:
            current = os.open(component, directory_flags, dir_fd=current)
            descriptors.append(current)
        fd = os.open(parts[-1], file_flags, dir_fd=current)
        descriptors.append(fd)
        information = os.fstat(fd)
        if not stat.S_ISREG(information.st_mode) or not 0 <= information.st_size <= MAX_BYTES:
            raise InvestigationBlocked("Source is not a bounded regular file")
        with os.fdopen(os.dup(fd), "rb", closefd=True) as handle:
            data = handle.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES or len(data) != information.st_size:
            raise InvestigationBlocked("Source changed or exceeded file budget")
        if os.fstat(fd).st_size != information.st_size:
            raise InvestigationBlocked("Source changed during inspection")
        return data
    except (OSError, ValueError) as exc:
        raise InvestigationBlocked("Authorized source unavailable or unsafe") from exc
    finally:
        for fd in reversed(descriptors):
            os.close(fd)


def _imports(source: bytes) -> tuple[dict[str, str], ...]:
    try:
        tree = ast.parse(source.decode("utf-8"))
    except (SyntaxError, UnicodeError, ValueError) as exc:
        raise InvestigationBlocked("Authorized Python source cannot be parsed") from exc
    observed: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            observed.update(alias.name for alias in node.names if alias.name.startswith("app."))
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module and node.module.startswith("app."):
                observed.add(node.module)
    return tuple({"module": module} for module in sorted(observed))


def _first_party_edges(root: Path, references: tuple[dict[str, str], ...]) -> tuple[dict[str, str], ...]:
    result = []
    for entry in references:
        module = entry["module"]
        if not module.startswith(("app.services.", "app.database.")):
            continue
        relative = module.replace(".", "/") + ".py"
        # Only confirm known module paths: don't follow external links.
        try:
            _read_scoped(root, relative)
            status = "PRESENT"
        except InvestigationBlocked:
            status = "UNRESOLVED"
        result.append({"module": module, "status": status})
    return tuple(result)


def inspect_first_party_sources(request: InvestigationRequest, *, root: Path = ROOT) -> dict[str, Any]:
    """Perform actual bounded source reads and return provenance-only evidence."""
    observations: list[SourceObservation] = []
    total_bytes = 0
    for path in request.paths:
        data = _read_scoped(root, path)
        total_bytes += len(data)
        if total_bytes > MAX_TOTAL_BYTES:
            raise InvestigationBlocked("Investigation total byte budget exceeded")
        references = _imports(data)
        observations.append(SourceObservation(
            path=path,
            sha256=hashlib.sha256(data).hexdigest(),
            size_bytes=len(data),
            first_party_imports=_first_party_edges(root, references),
        ))
    evidence: dict[str, Any] = {
        "schema": EVIDENCE_SCHEMA,
        "status": "OBSERVED",
        "authority": "deepseek_harness",
        "authorization_id": request.authorization_id,
        "harness_decision_id": request.harness_decision_id,
        "execution_id": request.execution_id,
        "sources": [asdict(item) for item in observations],
        "total_bytes": total_bytes,
        "source_count": len(observations),
        "unresolved_first_party_imports": sum(
            edge["status"] == "UNRESOLVED"
            for obs in observations for edge in obs.first_party_imports
        ),
    }
    canonical = json.dumps(evidence, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()
    evidence["receipt_sha256"] = hashlib.sha256(canonical).hexdigest()
    return evidence


def execute_br_rea_investigation(capability: Any, payload: dict[str, Any]) -> dict[str, Any]:
    """Run through registered Harness executor; never acquire authority itself."""
    if getattr(capability, "capability_id", None) != CAPABILITY_ID:
        raise InvestigationBlocked("Registry executor identity mismatch")
    request = InvestigationRequest.from_payload(payload)
    authorized = validate_harness_authorization(
        request.authorization_id,
        expected_action="DEVELOPMENT",
        expected_subject=f"capability:{CAPABILITY_ID}",
        expected_execution_id=request.execution_id,
    )
    if authorized.harness_decision_id != request.harness_decision_id:
        raise InvestigationBlocked("Harness decision lineage mismatch")
    verify_trusted_issuer_attestation(
        authorized,
        request.paths,
        request.issuer_attestation,
    )
    # Single-use transition is atomic in SQLite and precedes every filesystem read.
    if not consume_active_harness_authorization(request.authorization_id):
        raise InvestigationBlocked("Harness authorization already used")
    return inspect_first_party_sources(request)
