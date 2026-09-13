from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class YtDlpInfrastructureConfig:
    """Configuração não-secreta da infraestrutura do yt-dlp."""

    player_client: str = "mweb"
    js_runtime: str = "deno"
    po_token_base_url: str | None = None

    def __post_init__(self) -> None:
        if self.po_token_base_url is None:
            env_value = os.environ.get("YTDLP_PO_TOKEN_BASE_URL")
            if env_value:
                object.__setattr__(
                    self,
                    "po_token_base_url",
                    env_value.strip(),
                )
