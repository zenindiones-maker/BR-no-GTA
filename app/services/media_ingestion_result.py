from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from app.services.media_ingestion import IngestionStatus


@dataclass(frozen=True)
class IngestionWorkflowResult:
    status: IngestionStatus
    source_url: str
    output_path: Path | None
    reason: str | None


def parse_ingestion_result(payload: str) -> IngestionWorkflowResult:
    data = json.loads(payload)

    status = IngestionStatus(data["status"])
    source_url = str(data["source_url"])

    output_path_value = data.get("output_path")
    output_path = (
        Path(output_path_value)
        if output_path_value
        else None
    )

    reason = data.get("reason")

    return IngestionWorkflowResult(
        status=status,
        source_url=source_url,
        output_path=output_path,
        reason=reason,
    )


def main() -> int:
    payload = sys.stdin.read().strip()

    if not payload:
        print(
            "MEDIA_INGESTION_RESULT_ERROR: empty payload",
            file=sys.stderr,
        )
        return 2

    try:
        result = parse_ingestion_result(payload)
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        print(
            f"MEDIA_INGESTION_RESULT_ERROR: {exc}",
            file=sys.stderr,
        )
        return 2

    print(f"INGESTION_STATUS={result.status.value}")
    print(f"SOURCE_URL={result.source_url}")

    if result.output_path:
        print(f"OUTPUT_PATH={result.output_path}")

    if result.reason:
        print(f"REASON={result.reason}")

    if result.status is IngestionStatus.DOWNLOAD_OK:
        return 0

    if result.status in {
        IngestionStatus.DOWNLOAD_BLOCKED,
        IngestionStatus.SOURCE_UNSUPPORTED,
        IngestionStatus.SOURCE_UNAVAILABLE,
    }:
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
