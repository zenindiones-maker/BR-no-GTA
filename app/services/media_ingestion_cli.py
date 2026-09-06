from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from app.services.media_ingestion_service import MediaIngestionService
from app.services.ytdlp_infrastructure import (
    YtDlpInfrastructureConfig,
)
from app.services.ytdlp_media_ingestion import YtDlpMediaIngestion


def main() -> int:
    source_url = os.environ.get("SOURCE_URL", "").strip()
    output_path = Path(
        os.environ.get(
            "MEDIA_OUTPUT_PATH",
            "workspace/input/source.mp4",
        )
    )

    infrastructure = YtDlpInfrastructureConfig(
        player_client=os.environ.get(
            "YTDLP_PLAYER_CLIENT",
            "mweb",
        ),
        js_runtime=os.environ.get(
            "YTDLP_JS_RUNTIME",
            "deno",
        ),
        po_token_base_url=os.environ.get(
            "YTDLP_PO_TOKEN_BASE_URL",
        ),
    )

    provider = YtDlpMediaIngestion(
        infrastructure=infrastructure,
    )

    service = MediaIngestionService(provider)

    result = service.ingest(
        source_url=source_url,
        output_path=output_path,
    )

    print(
        json.dumps(
            {
                "status": result.status.value,
                "source_url": result.source_url,
                "output_path": (
                    str(result.output_path)
                    if result.output_path
                    else None
                ),
                "reason": result.reason,
            },
            ensure_ascii=False,
        )
    )

    if not result.succeeded:
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
