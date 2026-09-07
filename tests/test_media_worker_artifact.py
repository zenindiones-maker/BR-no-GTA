from pathlib import Path

import pytest

from app.services.media_analysis.models import MediaKnowledge
from app.services.media_worker_artifact import (
    MEDIA_KNOWLEDGE_FILENAME,
    MEDIA_MANIFEST_FILENAME,
    MEDIA_SOURCE_DIRNAME,
    MEDIA_SOURCE_FILENAME,
    package_media_worker_artifact,
    read_media_knowledge_artifact,
)


def test_package_media_worker_artifact(tmp_path):
    source = tmp_path / "original.mp4"
    source.write_bytes(b"fake-video-content")

    output_dir = tmp_path / "artifact"

    knowledge = MediaKnowledge(
        source_path=str(source),
        metadata={"analysis_version": "3"},
    )

    result = package_media_worker_artifact(
        knowledge,
        source,
        output_dir,
    )

    source_output = (
        output_dir
        / MEDIA_SOURCE_DIRNAME
        / MEDIA_SOURCE_FILENAME
    )

    assert result["source"] == source_output
    assert result["knowledge"] == (
        output_dir / MEDIA_KNOWLEDGE_FILENAME
    )
    assert result["manifest"] == (
        output_dir / MEDIA_MANIFEST_FILENAME
    )

    assert source_output.read_bytes() == b"fake-video-content"

    payload = read_media_knowledge_artifact(
        output_dir / MEDIA_KNOWLEDGE_FILENAME
    )
    assert payload["source_path"] == str(source)
    assert payload["metadata"]["analysis_version"] == "3"

    manifest = (
        output_dir / MEDIA_MANIFEST_FILENAME
    ).read_text(encoding="utf-8")

    assert '"source_file": "media/source.mp4"' in manifest
    assert '"knowledge_file": "media_knowledge.json"' in manifest


def test_package_media_worker_artifact_rejects_mismatched_source(
    tmp_path,
):
    source = tmp_path / "source.mp4"
    other = tmp_path / "other.mp4"

    source.write_bytes(b"source")
    other.write_bytes(b"other")

    knowledge = MediaKnowledge(
        source_path=str(other),
    )

    with pytest.raises(
        ValueError,
        match="source_path.*não corresponde",
    ):
        package_media_worker_artifact(
            knowledge,
            source,
            tmp_path / "artifact",
        )
