from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.render_media_materializer import (
    MaterializationError,
    materialize_scenes,
)
from app.workers.audiovisual_worker import validate_job


def _runtime_job(audio_requirements=None):
    return {
        "render_job_id": 20,
        "video_id": 5,
        "content_item_id": 4,
        "script_id": 8,
        "idea_id": 48,
        "brain_decision_id": "decision-1",
        "execution_id": "execution-1",
        "authorized_action": "EXECUTION",
        "estimated_duration_seconds": 30.0,
        "scenes": [
            {
                "segment_id": 4,
                "content_unit_id": 4,
                "asset_ref": "remote://media-worker/gta6-source",
                "source_url": "https://www.youtube.com/watch?v=source",
                "source_start_seconds": 0.0,
                "source_end_seconds": 30.0,
                "duration_seconds": 30.0,
            }
        ],
        "audio_requirements": audio_requirements
        if audio_requirements is not None
        else [
            "Utilizar narração clara e inteligível.",
            "Manter música e efeitos sonoros abaixo da voz.",
        ],
    }


def test_runtime_validation_accepts_editorial_audio_requirement_text():
    assert validate_job(_runtime_job(), allow_runtime_plan=True) is None


def test_runtime_validation_rejects_invalid_audio_requirement_entry():
    with pytest.raises(MaterializationError, match="objects or non-empty editorial text"):
        validate_job(_runtime_job([42]), allow_runtime_plan=True)


def test_materializer_keeps_text_requirements_out_of_media_ingestion(tmp_path):
    job = _runtime_job()
    original_requirements = list(job["audio_requirements"])

    class StubIngestion:
        def __init__(self):
            self.urls = []

        def ingest(self, url, output_path):
            self.urls.append(url)
            path = Path(output_path)
            path.write_bytes(b"real-media-placeholder")
            return SimpleNamespace(
                succeeded=True,
                output_path=path,
                status=SimpleNamespace(value="ready"),
            )

    ingestion = StubIngestion()

    def probe(_path):
        return {
            "format": {"duration": "60.0"},
            "streams": [
                {"codec_type": "video"},
                {"codec_type": "audio"},
            ],
        }

    hydrated, evidence = materialize_scenes(
        job,
        tmp_path / "assets",
        ingestion=ingestion,
        probe=probe,
    )

    assert job["audio_requirements"] == original_requirements
    assert hydrated["audio_requirements"] == []
    assert len(ingestion.urls) == 1
    assert len(evidence) == 1
    assert hydrated["scenes"][0]["media_path"]


def test_materializer_rejects_blank_editorial_audio_requirement(tmp_path):
    with pytest.raises(MaterializationError, match="must be non-empty"):
        materialize_scenes(
            _runtime_job(["   "]),
            tmp_path / "assets",
            ingestion=object(),
            probe=lambda _path: {},
        )
