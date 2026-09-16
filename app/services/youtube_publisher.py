from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class YouTubeUploadResult:
    """Resultado explícito de uma tentativa de upload para o YouTube."""

    success: bool
    youtube_video_id: str | None = None
    youtube_url: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class YouTubeVisibilityResult:
    """Resultado explícito de uma tentativa de alteração de visibilidade."""

    success: bool
    error: str | None = None


@dataclass(frozen=True)
class YouTubeVisibilityStateResult:
    """Observação read-only do estado remoto de visibilidade de um vídeo."""

    success: bool
    privacy_status: str | None = None
    error: str | None = None


class YouTubePublisher(Protocol):
    """Contrato de execução YouTube; não concede autoridade editorial/publicação."""

    def upload(self, publication: Any) -> YouTubeUploadResult:
        ...

    def make_public(self, youtube_video_id: str) -> YouTubeVisibilityResult:
        ...

    def get_visibility(self, youtube_video_id: str) -> YouTubeVisibilityStateResult:
        """Consulta visibilidade remota sem alterar o vídeo."""
        ...
