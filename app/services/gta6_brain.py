from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

from app.database.editorial_repository import list_editorial_evaluations
from app.database.gta6_monitor_repository import get_gta6_monitor_state
from app.database.ideas_repository import list_ideas
from app.database.queue_repository import (
    list_active_queue_items,
    list_queue_items,
)
from app.database.research_repository import list_research_items
from app.database.scripts_repository import list_scripts
from app.database.video_repository import list_videos
from app.database.youtube_repository import list_youtube_publications
from app.services.ai_provider import AIProvider


@dataclass(frozen=True)
class BrainContext:
    research_count: int
    ideas_count: int
    ideas_by_status: dict[str, int]
    editorial_count: int
    editorial_by_decision: dict[str, int]
    queue_count: int
    queue_by_status: dict[str, int]
    active_queue_count: int
    active_queue_by_status: dict[str, int]
    scripts_count: int
    scripts_by_status: dict[str, int]
    videos_count: int
    videos_by_status: dict[str, int]
    youtube_count: int
    youtube_by_status: dict[str, int]
    monitor_state: dict[str, Any] | None


@dataclass(frozen=True)
class BrainDecision:
    action: str
    reason: str
    priority: str
    confidence: float


class GTA6Brain:
    """Camada de decisão do GTA6 Master Agent."""

    ALLOWED_ACTIONS = {
        "MONITOR",
        "RESEARCH",
        "EDITORIAL",
        "EXECUTION",
        "YOUTUBE",
        "WAIT",
    }

    ALLOWED_PRIORITIES = {
        "LOW",
        "MEDIUM",
        "HIGH",
        "CRITICAL",
    }

    def __init__(self, ai_provider: AIProvider):
        self.ai_provider = ai_provider

    def build_context(self) -> BrainContext:
        research = list_research_items()
        ideas = list_ideas()
        editorial = list_editorial_evaluations()
        queue = list_queue_items()
        active_queue = list_active_queue_items()
        scripts = list_scripts()
        videos = list_videos()
        youtube = list_youtube_publications()

        monitor_state = get_gta6_monitor_state(
            "https://www.rockstargames.com/newswire"
        )

        return BrainContext(
            research_count=len(research),
            ideas_count=len(ideas),
            ideas_by_status=self._count_status(ideas),
            editorial_count=len(editorial),
            editorial_by_decision=self._count_field(
                editorial,
                "decision",
            ),
            queue_count=len(queue),
            queue_by_status=self._count_status(queue),
            active_queue_count=len(active_queue),
            active_queue_by_status=self._count_status(active_queue),
            scripts_count=len(scripts),
            scripts_by_status=self._count_status(scripts),
            videos_count=len(videos),
            videos_by_status=self._count_status(videos),
            youtube_count=len(youtube),
            youtube_by_status=self._count_status(youtube),
            monitor_state=monitor_state,
        )

    def decide(self) -> BrainDecision:
        context = self.build_context()

        prompt = self._build_prompt(context)
        response = self.ai_provider.generate(prompt)

        return self._parse_decision(response.text)

    def _build_prompt(self, context: BrainContext) -> str:
        context_json = json.dumps(
            asdict(context),
            ensure_ascii=False,
            indent=2,
            default=str,
        )

        return f"""
Você é o GTA6 Brain, o núcleo de decisão do GTA6 Master Agent.

Seu domínio é EXCLUSIVAMENTE GTA 6.

Você NÃO executa ferramentas.
Você NÃO inventa dados.
Você NÃO altera banco de dados.
Você NÃO cria fatos que não estejam no contexto.

Sua única responsabilidade é decidir qual deve ser a PRÓXIMA ação operacional.

Ações permitidas:
- MONITOR: verificar novamente fontes monitoradas.
- RESEARCH: executar pesquisa/coleta de informações GTA6.
- EDITORIAL: processar a fila editorial.
- EXECUTION: avançar a produção/renderização.
- YOUTUBE: tratar publicação pendente.
- WAIT: não há ação necessária neste momento.

Prioridades permitidas:
- LOW
- MEDIUM
- HIGH
- CRITICAL

Estado atual do BR-no-GTA:

{context_json}

IMPORTANTE:
- queue_count representa todos os registros da fila, inclusive históricos.
- active_queue_count representa somente trabalho atualmente processável.
- Para decidir EDITORIAL, considere active_queue_count e active_queue_by_status como fonte de verdade operacional.

Regras:
1. Use somente o estado fornecido.
2. Não invente notícias, anúncios ou resultados.
3. Não execute nenhuma ação.
4. Escolha exatamente UMA ação.
5. Explique brevemente por que essa ação é a próxima.
6. Confidence deve ser um número entre 0 e 1.
7. Responda SOMENTE JSON válido.
8. O JSON deve possuir exatamente estes campos:

{{
  "action": "MONITOR|RESEARCH|EDITORIAL|EXECUTION|YOUTUBE|WAIT",
  "reason": "explicação curta",
  "priority": "LOW|MEDIUM|HIGH|CRITICAL",
  "confidence": 0.0
}}
""".strip()

    @staticmethod
    def _count_status(items: list[dict[str, Any]]) -> dict[str, int]:
        result: dict[str, int] = {}

        for item in items:
            status = item.get("status")

            if not isinstance(status, str) or not status:
                status = "unknown"

            result[status] = result.get(status, 0) + 1

        return result

    @staticmethod
    def _count_field(
        items: list[dict[str, Any]],
        field: str,
    ) -> dict[str, int]:
        result: dict[str, int] = {}

        for item in items:
            value = item.get(field)

            if not isinstance(value, str) or not value:
                value = "unknown"

            result[value] = result.get(value, 0) + 1

        return result

    def _parse_decision(self, text: str) -> BrainDecision:
        if not isinstance(text, str) or not text.strip():
            raise ValueError(
                "GTA6 Brain returned invalid JSON."
            )

        normalized = text.strip()

        if normalized.startswith("```") and normalized.endswith("```"):
            lines = normalized.splitlines()

            if len(lines) < 3:
                raise ValueError(
                    "GTA6 Brain returned invalid JSON."
                )

            fence = lines[0].strip().lower()
            closing_fence = lines[-1].strip()

            if fence not in {"```", "```json"} or closing_fence != "```":
                raise ValueError(
                    "GTA6 Brain returned invalid JSON."
                )

            normalized = "\n".join(lines[1:-1]).strip()

        try:
            data = json.loads(normalized)
        except json.JSONDecodeError as exc:
            raise ValueError(
                "GTA6 Brain returned invalid JSON."
            ) from exc

        if not isinstance(data, dict):
            raise ValueError(
                "GTA6 Brain decision must be a JSON object."
            )

        action = data.get("action")
        reason = data.get("reason")
        priority = data.get("priority")
        confidence = data.get("confidence")

        if action not in self.ALLOWED_ACTIONS:
            raise ValueError(
                f"Invalid GTA6 Brain action: {action!r}"
            )

        if priority not in self.ALLOWED_PRIORITIES:
            raise ValueError(
                f"Invalid GTA6 Brain priority: {priority!r}"
            )

        if not isinstance(reason, str) or not reason.strip():
            raise ValueError(
                "GTA6 Brain reason must be a non-empty string."
            )

        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not 0 <= confidence <= 1
        ):
            raise ValueError(
                "GTA6 Brain confidence must be between 0 and 1."
            )

        return BrainDecision(
            action=action,
            reason=reason.strip(),
            priority=priority,
            confidence=float(confidence),
        )
