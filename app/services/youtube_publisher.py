from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class YouTubeUploadResult:
    """
    Resultado explícito de uma tentativa de upload para o YouTube.

    O upload bem-sucedido cria um recurso remoto no YouTube,
    inicialmente com a privacidade controlada pela operação de upload.
    """

    success: bool
    youtube_video_id: str | None = None
    youtube_url: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class YouTubeVisibilityResult:
    """
    Resultado explícito de uma tentativa de alteração de visibilidade
    de um vídeo que já existe no YouTube.
    """

    success: bool
    error: str | None = None


class YouTubePublisher(Protocol):
    """
    Contrato para qualquer implementação capaz de operar sobre o YouTube.

    A camada superior conhece apenas este contrato.

    Implementações concretas podem utilizar:
    - Google YouTube Data API;
    - fake determinístico para testes;
    - futuras implementações alternativas.
    """

    def upload(
        self,
        publication: Any,
    ) -> YouTubeUploadResult:
        """
        Faz o upload de uma YouTubePublication para o YouTube.
        """
        ...

    def make_public(
        self,
        youtube_video_id: str,
    ) -> YouTubeVisibilityResult:
        """
        Torna público um vídeo que já existe no YouTube.
        """
        ...
