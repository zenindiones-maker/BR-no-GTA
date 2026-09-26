from pathlib import Path
import pytest

from app.services.artifact_import_service import ArtifactImportError, import_artifact


def test_import_materializes_content_addressed_artifact(tmp_path):
    ingress=tmp_path/"ingress"; ingress.mkdir()
    source=ingress/"evidence.json"; source.write_text('{"ok":true}',encoding="utf-8")
    root=tmp_path/"artifacts"
    m=import_artifact(mission_id="m1",source_path=source,ingress_roots=(ingress,),artifact_root=root,source_kind="RESIDUAL_EVIDENCE",source_locator="trusted:residual",imported_at="2026-09-26T00:00:00Z")
    assert m.canonical_artifact_ref.startswith("artifact:input-artifacts/sha256/")
    target=root/m.canonical_artifact_ref.removeprefix("artifact:")
    assert target.read_bytes()==source.read_bytes()
    assert m.source_sha256==m.canonical_sha256
    assert m.source_size_bytes==m.canonical_size_bytes>0
    manifests=list((root/"artifact-import-manifests"/"sha256").glob("*.json"))
    assert len(manifests)==1


def test_import_rejects_path_escape_and_sha_mismatch(tmp_path):
    ingress=tmp_path/"ingress"; ingress.mkdir()
    outside=tmp_path/"outside.json"; outside.write_text("x",encoding="utf-8")
    with pytest.raises(ArtifactImportError,match="PATH_ESCAPE"):
        import_artifact(mission_id="m1",source_path=outside,ingress_roots=(ingress,),artifact_root=tmp_path/"a",source_kind="TEST",source_locator="x",imported_at="t")
    source=ingress/"inside.json"; source.write_text("x",encoding="utf-8")
    with pytest.raises(ArtifactImportError,match="SHA_MISMATCH"):
        import_artifact(mission_id="m1",source_path=source,ingress_roots=(ingress,),artifact_root=tmp_path/"a",source_kind="TEST",source_locator="x",imported_at="t",expected_sha256="0"*64)
