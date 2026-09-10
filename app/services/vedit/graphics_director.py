from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class GraphicDecision:
    kind: str
    start_seconds: float
    duration_seconds: float
    payload: dict[str, Any]
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "start_seconds": self.start_seconds,
            "duration_seconds": self.duration_seconds,
            "payload": dict(self.payload),
            "reason": self.reason,
        }


def build_graphics_plan(
    *,
    narrative_role: str,
    title: str,
    start_seconds: float,
    duration_seconds: float,
    enabled: bool = True,
) -> tuple[GraphicDecision, ...]:
    if not enabled:
        return ()

    role = str(narrative_role).upper()
    decisions: list[GraphicDecision] = []

    if role == "HOOK":
        decisions.append(
            GraphicDecision(
                kind="title",
                start_seconds=start_seconds,
                duration_seconds=min(duration_seconds, 3.0),
                payload={"text": title},
                reason="título usado para estabelecer o gancho",
            )
        )

    elif role == "IMPACT":
        decisions.append(
            GraphicDecision(
                kind="callout",
                start_seconds=start_seconds,
                duration_seconds=min(duration_seconds, 2.5),
                payload={"emphasis": True},
                reason="callout reforça o momento de impacto",
            )
        )

    elif role == "CONCLUSION":
        decisions.append(
            GraphicDecision(
                kind="summary",
                start_seconds=start_seconds,
                duration_seconds=min(duration_seconds, 3.0),
                payload={"text": title},
                reason="gráfico de resumo utilizado no fechamento",
            )
        )

    elif role == "CTA":
        decisions.append(
            GraphicDecision(
                kind="cta",
                start_seconds=start_seconds,
                duration_seconds=min(duration_seconds, 3.0),
                payload={"text": "Inscreva-se e acompanhe as próximas notícias"},
                reason="CTA editorial no encerramento",
            )
        )

    return tuple(decisions)
