from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


ProgressKind = Literal["ACTION", "STATUS", "REVIEW", "WAITING", "RESULT"]


@dataclass(frozen=True)
class HermesTeamProgress:
    kind: ProgressKind
    message: str

    def telegram_text(self) -> str:
        label = {
            "ACTION": "AÇÃO",
            "STATUS": "STATUS",
            "REVIEW": "REVIEW",
            "WAITING": "AGUARDANDO VOCÊ",
            "RESULT": "RESULTADO",
        }[self.kind]
        return f"{label}: {self.message.strip()}"


def format_team_progress(kind: ProgressKind, message: str) -> str:
    return HermesTeamProgress(kind=kind, message=message).telegram_text()
