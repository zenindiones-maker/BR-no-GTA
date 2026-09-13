"""Hydrate remote identities only on the cloud execution boundary."""
from copy import deepcopy
import hashlib
import math
from pathlib import Path
from urllib.parse import urlsplit, parse_qsl


class MaterializationError(ValueError):
    pass


def validate_remote_source(item):
    if not isinstance(item.get("asset_ref"), str) or not item["asset_ref"].startswith("remote://media-worker/"):
        raise MaterializationError("Missing official media-worker asset_ref")
    url = item.get("source_url")
    if not isinstance(url, str):
        raise MaterializationError("Missing source_url")
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        raise MaterializationError("source_url must be public HTTPS without credentials")
    if any(any(word in key.lower() for word in ("token", "secret", "password", "signature", "credential", "api_key")) for key, _ in parse_qsl(parts.query)):
        raise MaterializationError("Credential-bearing source_url is forbidden")


def materialize_scenes(job, root, *, ingestion=None, probe=None):
    from app.workers.audiovisual_worker import probe_video
    probe = probe or probe_video
    if ingestion is None:
        from app.services.ytdlp_media_ingestion import YtDlpMediaIngestion
        ingestion = YtDlpMediaIngestion()
    hydrated = deepcopy(job)
    items = hydrated["scenes"] + hydrated.get("audio_requirements", [])
    identities = {}
    for item in items:
        validate_remote_source(item)
        previous = identities.setdefault(item["asset_ref"], item["source_url"])
        if previous != item["source_url"]:
            raise MaterializationError("Conflicting source URLs for asset_ref")
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    resolved = {}
    evidence = []
    for ref, url in identities.items():
        key = hashlib.sha256((ref + "\n" + url).encode()).hexdigest()
        directory = root / key
        # No reuse of partial files from an interrupted ingestion.
        directory.mkdir(exist_ok=False)
        result = ingestion.ingest(url, directory / "source.mp4")
        if not result.succeeded or result.output_path is None:
            raise MaterializationError("Media ingestion failed: " + result.status.value)
        path = Path(result.output_path).resolve()
        if not path.is_relative_to(directory) or not path.is_file() or path.stat().st_size <= 0:
            raise MaterializationError("Media ingestion returned missing/unsafe output")
        data = probe(path)
        try:
            duration = float(data["format"]["duration"])
        except (KeyError, TypeError, ValueError):
            raise MaterializationError("Source duration missing") from None
        if not math.isfinite(duration) or duration <= 0:
            raise MaterializationError("Invalid source duration")
        resolved[ref] = (path, duration, data)
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        evidence.append(dict(asset_ref=ref, source_url=url, sha256=digest,
                             size_bytes=path.stat().st_size, duration_seconds=duration))
    for item in items:
        path, duration, data = resolved[item["asset_ref"]]
        start = item.get("source_start_seconds")
        length = item.get("duration_seconds")
        if not all(type(v) in (int, float) and math.isfinite(v) for v in (start, length)) or start < 0 or length <= 0 or start + length > duration + .001:
            raise MaterializationError("Source window exceeds recovered media")
        if "source_end_seconds" in item:
            end = item["source_end_seconds"]
            if type(end) not in (int, float) or not math.isfinite(end) or end < start + length or end > duration + .001:
                raise MaterializationError("Invalid source_end_seconds")
        kind = "video" if any(item is scene for scene in hydrated["scenes"]) else "audio"
        if not any(s.get("codec_type") == kind for s in data.get("streams", [])):
            raise MaterializationError("Required source stream missing: " + kind)
        item["media_path"] = str(path)
        item["file_path"] = str(path)
    return hydrated, evidence
