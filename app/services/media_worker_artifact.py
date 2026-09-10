from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.media_analysis.models import MediaKnowledge
from app.services.media_analysis.serialization import serialize_media_knowledge
from app.services.speech.models import SpeechAnalysis
from app.services.speech.qa import SpeechQAResult


MEDIA_KNOWLEDGE_FILENAME = "media_knowledge.json"
MEDIA_MANIFEST_FILENAME = "manifest.json"
MEDIA_PROBE_FILENAME = "media_probe.json"
SPEECH_ANALYSIS_FILENAME = "speech_analysis.json"
SPEECH_QA_FILENAME = "speech_qa.json"

ARTIFACT_TYPE = "media-worker"
ARTIFACT_SCHEMA_VERSION = "3"


def _stable_source_path(
    *,
    source_url: str,
    source_name: str,
) -> str:
    url = source_url.strip()
    name = source_name.strip()

    if not url:
        raise ValueError("source_url é obrigatório.")

    if not name:
        raise ValueError("source_name é obrigatório.")

    return f"remote://media-worker/{name}"


def _normalize_visual_samples_for_artifact(
    payload: dict[str, Any],
) -> dict[str, Any]:
    """
    Normaliza VisualSample para o artifact JSON.

    Os JPGs gerados durante a análise são temporários e ficam
    somente no GitHub Actions runner. Eles não são transportados
    para o A15.

    ``frame_ref`` preserva a referência lógica por timestamp.
    ``path`` permanece no payload por compatibilidade, mas fica
    explicitamente nulo porque o arquivo físico não é enviado.
    """
    visual_samples = payload.get("visual_samples")

    if visual_samples is None:
        return payload

    if not isinstance(visual_samples, (list, tuple)):
        raise ValueError(
            "visual_samples precisa ser uma lista ou tupla."
        )

    normalized_samples: list[dict[str, Any]] = []

    for index, sample in enumerate(visual_samples):
        if not isinstance(sample, dict):
            raise ValueError(
                f"visual_samples[{index}] precisa ser um objeto."
            )

        normalized = dict(sample)
        time_seconds = normalized.get("time_seconds")

        if isinstance(time_seconds, bool) or not isinstance(
            time_seconds,
            (int, float),
        ):
            raise ValueError(
                f"visual_samples[{index}].time_seconds inválido."
            )

        normalized["frame_ref"] = (
            f"frame:{float(time_seconds):.3f}"
        )

        # O JPG existe apenas temporariamente no worker.
        normalized["path"] = None

        normalized_samples.append(normalized)

    payload["visual_samples"] = normalized_samples
    return payload


def _serialize_knowledge_with_stable_source(
    knowledge: MediaKnowledge,
    *,
    source_url: str,
    source_name: str,
) -> dict[str, Any]:
    payload = serialize_media_knowledge(knowledge)

    if not isinstance(payload, dict):
        raise ValueError(
            "serialize_media_knowledge() não retornou dict."
        )

    payload = dict(payload)

    payload = _normalize_visual_samples_for_artifact(
        payload,
    )

    payload["source_path"] = _stable_source_path(
        source_url=source_url,
        source_name=source_name,
    )

    metadata = dict(payload.get("metadata") or {})
    metadata.update(
        {
            "artifact_type": ARTIFACT_TYPE,
            "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
            "source_url": source_url.strip(),
            "source_name": source_name.strip(),
            "source_storage": "remote",
            "source_local_file_required": False,
        }
    )
    payload["metadata"] = metadata

    return payload


def write_media_knowledge_artifact(
    knowledge: MediaKnowledge,
    output_dir: str | Path,
    *,
    source_url: str | None = None,
    source_name: str | None = None,
) -> Path:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)

    output_path = directory / MEDIA_KNOWLEDGE_FILENAME

    if source_url is not None and source_name is not None:
        payload = _serialize_knowledge_with_stable_source(
            knowledge,
            source_url=source_url,
            source_name=source_name,
        )
    else:
        payload = serialize_media_knowledge(knowledge)

    output_path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    return output_path


def package_media_worker_artifact(
    knowledge: MediaKnowledge,
    source_path: str | Path,
    output_dir: str | Path,
    *,
    source_url: str | None = None,
    source_name: str = "gta6-media",
    media_probe: dict[str, Any] | None = None,
    speech_analysis: SpeechAnalysis | None = None,
    speech_qa: SpeechQAResult | None = None,
    extra_manifest: dict[str, Any] | None = None,
) -> dict[str, Path]:
    """
    Empacota somente artefatos estruturados do Media Worker.

    IMPORTANTE:
    - A mídia física pode existir temporariamente no worker.
    - A mídia física NÃO é copiada para o artifact.
    - O transporte entre GitHub Actions e A15 é JSON-only.
    """
    source = Path(source_path)

    if (speech_analysis is None) != (speech_qa is None):
        raise ValueError(
            "speech_analysis e speech_qa devem ser fornecidos juntos."
        )

    if not source.is_file():
        raise FileNotFoundError(
            f"Mídia de origem não encontrada: {source}"
        )

    if str(Path(knowledge.source_path)) != str(source):
        raise ValueError(
            "O source_path do MediaKnowledge não corresponde "
            "à mídia fornecida."
        )

    if source_url is not None:
        source_ref = _stable_source_path(
            source_url=source_url,
            source_name=source_name,
        )
    else:
        source_ref = str(source)

    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)

    knowledge_output = write_media_knowledge_artifact(
        knowledge,
        directory,
        source_url=source_url,
        source_name=source_name,
    )

    files: dict[str, str] = {
        "media_knowledge": MEDIA_KNOWLEDGE_FILENAME,
    }

    if media_probe is not None:
        probe_output = directory / MEDIA_PROBE_FILENAME
        probe_output.write_text(
            json.dumps(
                media_probe,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        files["media_probe"] = MEDIA_PROBE_FILENAME

    manifest: dict[str, Any] = {
        "artifact_type": ARTIFACT_TYPE,
        "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
        "worker_version": "2",
        "source_ref": source_ref,
        "source_url": source_url.strip() if source_url else None,
        "source_name": source_name.strip(),
        "source_local_file_included": False,
        "source_local_file_required": False,
        "files": files,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    speech_analysis_output: Path | None = None
    speech_qa_output: Path | None = None

    if speech_analysis is not None and speech_qa is not None:
        speech_analysis_output = directory / SPEECH_ANALYSIS_FILENAME
        speech_analysis_output.write_text(
            json.dumps(
                speech_analysis.to_dict(),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        speech_qa_output = directory / SPEECH_QA_FILENAME
        speech_qa_output.write_text(
            json.dumps(
                speech_qa.to_dict(),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        files["speech_analysis"] = SPEECH_ANALYSIS_FILENAME
        files["speech_qa"] = SPEECH_QA_FILENAME

    if extra_manifest:
        manifest.update(extra_manifest)

    manifest_output = directory / MEDIA_MANIFEST_FILENAME
    manifest_output.write_text(
        json.dumps(
            manifest,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    result: dict[str, Path] = {
        "knowledge": knowledge_output,
        "manifest": manifest_output,
    }

    if media_probe is not None:
        result["probe"] = directory / MEDIA_PROBE_FILENAME

    if speech_analysis_output is not None:
        result["speech_analysis"] = speech_analysis_output

    if speech_qa_output is not None:
        result["speech_qa"] = speech_qa_output

    return result


def read_media_worker_manifest(
    artifact_path: str | Path,
) -> dict[str, Any]:
    path = Path(artifact_path)

    if not path.is_file():
        raise FileNotFoundError(
            f"Manifest do Media Worker não encontrado: {path}"
        )

    payload = json.loads(
        path.read_text(encoding="utf-8")
    )

    if not isinstance(payload, dict):
        raise ValueError(
            "O manifest do Media Worker precisa conter "
            "um objeto JSON."
        )

    if payload.get("artifact_type") != ARTIFACT_TYPE:
        raise ValueError(
            "artifact_type inválido no Media Worker."
        )

    if payload.get("artifact_schema_version") != ARTIFACT_SCHEMA_VERSION:
        raise ValueError(
            "artifact_schema_version incompatível."
        )

    if payload.get("source_local_file_included") is not False:
        raise ValueError(
            "Artifact inválido: mídia física não pode "
            "ser incluída no transporte."
        )

    files = payload.get("files")
    if not isinstance(files, dict):
        raise ValueError(
            "Manifest sem mapa de arquivos."
        )

    return payload


def read_media_knowledge_artifact(
    artifact_path: str | Path,
) -> dict[str, Any]:
    path = Path(artifact_path)

    if not path.is_file():
        raise FileNotFoundError(
            f"Artifact MediaKnowledge não encontrado: {path}"
        )

    payload = json.loads(
        path.read_text(encoding="utf-8")
    )

    if not isinstance(payload, dict):
        raise ValueError(
            "O artifact MediaKnowledge precisa conter "
            "um objeto JSON."
        )

    return payload
