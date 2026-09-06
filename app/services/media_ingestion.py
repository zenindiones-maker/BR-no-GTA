from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol


class IngestionStatus(str, Enum):
    DOWNLOAD_OK = "DOWNLOAD_OK"
    DOWNLOAD_BLOCKED = "DOWNLOAD_BLOCKED"
    SOURCE_UNSUPPORTED = "SOURCE_UNSUPPORTED"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"


@dataclass(frozen=True)
class IngestionResult:
    status: IngestionStatus
    source_url: str
    output_path: Path | None = None
    reason: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.status is IngestionStatus.DOWNLOAD_OK


class MediaIngestionProvider(Protocol):
    def ingest(
        self,
        source_url: str,
        output_path: Path,
    ) -> IngestionResult:
        ...
