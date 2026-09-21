from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from typing import Any

from app.services.harness_collaboration_service import build_goal_envelope


@dataclass(frozen=True)
class IntentResolution:
    intent: str
    layer: str
    confidence: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {
            "intent": self.intent,
            "layer": self.layer,
            "confidence": self.confidence,
            "reason": self.reason,
        }


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).casefold().strip()


def _tokens(value: str) -> tuple[str, ...]:
    return tuple(re.findall(r"[a-z0-9][a-z0-9_-]*", _fold(value)))


def _project_is_gta6(state: dict[str, Any]) -> bool:
    haystack = _fold(" ".join(
        str(value or "")
        for value in (
            state.get("active_project"),
            state.get("current_subject"),
            state.get("active_task"),
        )
    ))
    return any(term in haystack for term in ("br-no-gta", "gta6", "gta 6", "gta vi"))


def resolve_contextual_intent(
    message: str,
    *,
    state: dict[str, Any],
    recent_turns: list[dict[str, Any]],
    has_attachment: bool = False,
) -> IntentResolution | None:
    """Resolve high-confidence controls and context-bound goals before any provider.

    This is intentionally narrow. It never tries to generically understand arbitrary
    language; it resolves controls/canonical-context requests whose meaning is already
    grounded in local state. Open semantic language remains eligible for the provider
    only after this layer and the Harness Mission Planner decline the request.
    """

    if has_attachment:
        return IntentResolution("FILE_SUBMISSION", "LAYER_1_CONTROL", "HIGH", "attachment")

    text = _fold(message)
    tokens = _tokens(message)
    if not text:
        return IntentResolution("CLARIFICATION", "LAYER_1_CONTROL", "HIGH", "empty")

    if re.search(r"\b(aprovo|aprovado|aprovada|pode seguir|pode continuar|ficou bom)\b", text):
        return IntentResolution("APPROVAL", "LAYER_1_CONTROL", "HIGH", "explicit approval")
    if re.search(r"\b(rejeito|reprovado|reprovada|nao gostei|ficou ruim|esta ruim|ta ruim)\b", text):
        return IntentResolution("REJECTION", "LAYER_1_CONTROL", "HIGH", "explicit rejection")
    if re.search(r"\b(cancela|cancelar|pare|parar|interrompe|interromper)\b", text):
        return IntentResolution("CANCEL_REQUEST", "LAYER_1_CONTROL", "HIGH", "explicit cancel")

    if text in {"onde estamos", "onde estamos?", "status", "status?"} or any(term in text for term in (
        "qual o status", "o que voce esta fazendo", "como esta o run", "como esta a tarefa",
    )):
        return IntentResolution("STATUS_REQUEST", "LAYER_1_CONTROL", "HIGH", "status control")

    memory_forms = {
        "memoria", "memoria?", "o que voce lembra", "o que voce lembra?",
        "oque voce lembra", "oque voce lembra?", "o que lembra", "o que lembra?",
    }
    if text in memory_forms or any(term in text for term in (
        "o que eu decidi", "qual foi minha decisao", "o que eu falei sobre",
        "o que eu pedi sobre", "minhas decisoes sobre",
    )):
        return IntentResolution(
            "MEMORY_RECALL_REQUEST",
            "LAYER_1_CONTROL" if text in memory_forms else "LAYER_2_CONTEXT",
            "HIGH",
            "canonical human-memory recall",
        )

    knowledge_forms = {"conhecimento", "conhecimento?"}
    if text in knowledge_forms:
        if _project_is_gta6(state):
            return IntentResolution(
                "KNOWLEDGE_RECALL_REQUEST",
                "LAYER_2_CONTEXT",
                "HIGH",
                "short knowledge request resolved from active BR-no-GTA project",
            )
        return IntentResolution(
            "CLARIFICATION",
            "LAYER_2_CONTEXT",
            "MEDIUM",
            "knowledge scope is ambiguous outside an active canonical project",
        )
    if any(term in text for term in (
        "conhecimento sobre", "o que sabemos sobre", "oque sabemos sobre",
        "o que voce sabe sobre", "oque voce sabe sobre",
    )):
        return IntentResolution("KNOWLEDGE_RECALL_REQUEST", "LAYER_1_CONTROL", "HIGH", "knowledge recall")

    if re.search(r"\b(lembra disso|guarda isso|guarde isso|anota isso|anote isso)\b", text):
        return IntentResolution(
            "MEMORY_WRITE_REQUEST",
            "LAYER_1_CONTROL",
            "HIGH",
            "explicit governed memory-candidate request",
        )

    if text in {"continua", "continue", "retoma", "retome"}:
        return IntentResolution(
            "EXECUTION_REQUEST",
            "LAYER_2_CONTEXT",
            "HIGH",
            "continue control resolved against active/pending conversation context",
        )

    # A direct human constraint is a canonical decision, not an open chat prompt.
    if (
        text.startswith(("nao faca ", "nao produza ", "nao use ", "nao execute "))
        and any(term in text for term in ("aprovar", "aprovacao", "revisao", "revisar", "antes"))
    ):
        return IntentResolution(
            "REJECTION",
            "LAYER_2_CONTEXT",
            "HIGH",
            "explicit human constraint bound to active project/artifact",
        )

    # Layer 3: determine whether this is a known operational goal. This uses the
    # Harness goal taxonomy, not agent/runtime keywords supplied by the human.
    try:
        goal = build_goal_envelope(
            human_goal=message,
            project=str(state.get("active_project") or "BR-no-GTA"),
            goal_id=str(state.get("active_goal_id") or "telegram-human-goal"),
            subject=str(state.get("current_subject") or "").strip() or None,
            source_surface="telegram",
        )
    except Exception:
        goal = None
    if goal is not None and goal.mission_class != "OPEN_SEMANTIC":
        return IntentResolution(
            "EXECUTION_REQUEST",
            "LAYER_3_MISSION_PLANNER",
            "HIGH",
            f"known Harness mission class: {goal.mission_class}",
        )

    # A one-token unknown utterance should not burn a provider by default.
    if len(tokens) <= 1:
        return IntentResolution(
            "CLARIFICATION",
            "LAYER_2_CONTEXT",
            "MEDIUM",
            "short utterance has no canonical control/goal resolution",
        )

    return None
