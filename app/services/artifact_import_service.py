from __future__ import annotations

from dataclasses import dataclass, asdict
from hashlib import sha256
import json
from pathlib import Path
from typing import Iterable


SCHEMA = "ArtifactImportManifest/v1"


class ArtifactImportError(ValueError):
    pass


@dataclass(frozen=True)
class ArtifactImportManifest:
    schema: str
    mission_id: str
    source_kind: str
    source_locator: str
    source_sha256: str
    source_size_bytes: int
    canonical_artifact_ref: str
    canonical_sha256: str
    canonical_size_bytes: int
    imported_at: str
    content_sha256: str

    def to_dict(self):
        return asdict(self)


def _canonical_bytes(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def import_artifact(
    *,
    mission_id: str,
    source_path: Path,
    ingress_roots: Iterable[Path],
    artifact_root: Path,
    source_kind: str,
    source_locator: str,
    imported_at: str,
    expected_sha256: str | None = None,
) -> ArtifactImportManifest:
    mission_id = str(mission_id or "").strip()
    if not mission_id:
        raise ArtifactImportError("ARTIFACT_IMPORT_MISSION_ID_REQUIRED")
    roots = tuple(Path(p).resolve() for p in ingress_roots)
    if not roots:
        raise ArtifactImportError("ARTIFACT_IMPORT_INGRESS_ROOT_REQUIRED")
    source = Path(source_path).resolve()
    if not any(source == root or root in source.parents for root in roots):
        raise ArtifactImportError("ARTIFACT_IMPORT_PATH_ESCAPE")
    if not source.is_file():
        raise ArtifactImportError("ARTIFACT_IMPORT_SOURCE_MISSING")
    raw = source.read_bytes()
    if not raw:
        raise ArtifactImportError("ARTIFACT_IMPORT_SOURCE_EMPTY")
    digest = sha256(raw).hexdigest()
    expected = str(expected_sha256 or "").removeprefix("sha256:").lower()
    if expected and expected != digest:
        raise ArtifactImportError("ARTIFACT_IMPORT_SOURCE_SHA_MISMATCH")

    relative = Path("input-artifacts") / "sha256" / (digest + source.suffix.lower())
    root = Path(artifact_root).resolve()
    target = (root / relative).resolve()
    if root not in target.parents:
        raise ArtifactImportError("ARTIFACT_IMPORT_DESTINATION_ESCAPE")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if sha256(target.read_bytes()).hexdigest() != digest:
            raise ArtifactImportError("ARTIFACT_IMPORT_CANONICAL_COLLISION")
    else:
        target.write_bytes(raw)

    artifact_ref = "artifact:" + relative.as_posix()
    body = {
        "schema": SCHEMA,
        "mission_id": mission_id,
        "source_kind": str(source_kind),
        "source_locator": str(source_locator),
        "source_sha256": digest,
        "source_size_bytes": len(raw),
        "canonical_artifact_ref": artifact_ref,
        "canonical_sha256": digest,
        "canonical_size_bytes": len(raw),
        "imported_at": str(imported_at),
    }
    content_hash = sha256(_canonical_bytes(body)).hexdigest()
    manifest = ArtifactImportManifest(**body, content_sha256=content_hash)
    manifest_dir = root / "artifact-import-manifests" / "sha256"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / (content_hash + ".json")
    encoded = json.dumps(manifest.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    if manifest_path.exists() and manifest_path.read_text(encoding="utf-8") != encoded:
        raise ArtifactImportError("ARTIFACT_IMPORT_MANIFEST_COLLISION")
    manifest_path.write_text(encoded, encoding="utf-8")
    return manifest
