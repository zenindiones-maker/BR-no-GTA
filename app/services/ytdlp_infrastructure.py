from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class YtDlpInfrastructureConfig:
    """Configuração não-secreta da infraestrutura do yt-dlp."""

    player_client: str = "mweb"
    js_runtime: str = "deno"
    po_token_base_url: str | None = None
