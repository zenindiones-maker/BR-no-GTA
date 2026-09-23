from __future__ import annotations

import base64
from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any, Protocol
import unicodedata

from app.services.github_actions_artifact_service import GitHubActionsArtifactService
from app.services.github_actions_command_runner import run_github_actions_command
from app.services.github_actions_dispatcher import GitHubActionsDispatcher
from app.services.github_actions_run_tracker import GitHubActionsRunTracker
from app.services.github_actions_run_watcher import GitHubActionsRunWatcher
from app.services.harness_authorization_service import (
    HarnessAuthorization,
    consume_harness_authorization,
    issue_harness_authorization,
    validate_harness_authorization,
)
from app.services.harness_routing_policy_service import (
    HarnessRoutingDecision,
    HarnessRoutingRequest,
    route_harness_request,
)


FRESH_RESEARCH_CAPABILITY_ID = "gta6.research.fresh-cloud"
FRESH_RESEARCH_EXECUTOR_BINDING = (
    "app.services.telegram_fresh_research_service.execute_fresh_gta6_research_capability"
)
FRESH_RESEARCH_ARTIFACT = "gta6-fresh-research"
FRESH_RESEARCH_TASK_CLASS = "telegram-source-fresh-research"


class FreshResearchError(RuntimeError):
    pass


@dataclass(frozen=True)
class FreshResearchEvidence:
    status: str
    authority: str
    routing_id: str
    authorization_id: str
    execution_id: str
    checked_at: str
    official_source_count: int
    secondary_source_count: int
    packet: dict[str, Any]
    execution_ref: str
    artifact_ref: str


class FreshResearchTransport(Protocol):
    def execute(
        self,
        *,
        query: str,
        execution_id: str,
        source_context: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], str]: ...


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).casefold()


def requires_fresh_research(
    message: str,
    *,
    input_context: dict[str, Any] | None = None,
) -> bool:
    """Deterministic freshness gate using message plus structured ingress context.

    Telegram classification/provenance is authoritative input to this gate.
    Keyword matching is only a fallback for ordinary unstructured chat.
    """
    context = dict(input_context or {})
    classification = str(context.get("classification") or "").strip().lower()
    input_kind = str(context.get("input_kind") or "").strip().lower()
    source_url = str(context.get("source_url") or "").strip()
    if classification == "news" or source_url:
        return True
    if input_kind in {"url", "link", "social", "social_link"}:
        return True
    text = _fold(message).strip()
    if not text:
        return False
    if "https://" in str(message or "").casefold() or "http://" in str(message or "").casefold():
        return True
    system_only = (
        "como funciona o sistema",
        "quem manda no sistema",
        "qual capability",
        "qual capacidade",
        "o harness",
        "meu projeto",
    )
    if any(term in text for term in system_only) and "gta 6" not in text and "gta vi" not in text:
        return False
    freshness_terms = (
        "hoje", "atual", "atualizado", "atualizada", "agora", "recente", "recentes",
        "ultima", "ultimas", "ultimo", "ultimos", "novidade", "novidades", "noticia", "noticias",
        "rockstar", "newswire", "confirmado", "confirmada", "oficial", "oficiais", "rumor", "rumores",
        "vazamento", "vazamentos", "lancamento", "data", "pre-venda", "pre venda", "trailer",
        "o que se sabe", "o que sabemos", "o que voce sabe", "o que sabe",
        "verifique", "verificar", "verifica", "confira", "confere", "cheque",
        "checar", "fact-check", "fact check", "factcheck",
    )
    if any(term in text for term in freshness_terms):
        return True
    gta_terms = ("gta 6", "gta vi", "grand theft auto vi", "grand theft auto 6", "leonida", "lucia", "jason")
    question_shape = text.endswith("?") or text.startswith(
        ("qual ", "quais ", "quando ", "onde ", "como ", "quem ", "o que ", "me diga", "explique")
    )
    return question_shape and any(term in text for term in gta_terms)


class GitHubActionsFreshResearchTransport:
    def __init__(
        self,
        *,
        repository: str | None = None,
        ref: str | None = None,
        workflow: str = "gta6-fresh-research.yml",
        artifact_root: str | Path | None = None,
    ) -> None:
        self.repository = (
            repository
            or os.getenv("BR_FRESH_RESEARCH_REPOSITORY")
            or os.getenv("BR_OMNIROUTE_REPOSITORY")
            or "zenindiones-maker/BR-no-GTA"
        ).strip()
        self.ref = (
            ref
            or os.getenv("BR_FRESH_RESEARCH_REF")
            or os.getenv("BR_OMNIROUTE_REF")
            or "main"
        ).strip()
        self.workflow = workflow
        if not self.repository or not self.ref or not self.workflow:
            raise ValueError("Fresh research GitHub transport is incomplete")
        dispatcher = GitHubActionsDispatcher(run_github_actions_command)
        tracker = GitHubActionsRunTracker(run_github_actions_command)
        self.watcher = GitHubActionsRunWatcher(
            tracker,
            poll_interval=float(os.getenv("BR_FRESH_RESEARCH_POLL_INTERVAL", "5")),
            timeout=float(os.getenv("BR_FRESH_RESEARCH_RUN_TIMEOUT", "600")),
        )
        self.dispatcher = dispatcher
        self.artifacts = GitHubActionsArtifactService(run_github_actions_command)
        self.artifact_root = Path(
            artifact_root
            or os.getenv("BR_FRESH_RESEARCH_ARTIFACT_ROOT")
            or "runtime/gta6-fresh-research-artifacts"
        )

    def execute(
        self,
        *,
        query: str,
        execution_id: str,
        source_context: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], str]:
        source_context = dict(source_context or {})
        source_url = str(source_context.get("source_url") or "").strip()
        dispatched = self.dispatcher.dispatch(
            repository=self.repository,
            workflow=self.workflow,
            ref=self.ref,
            inputs={
                "execution_id": execution_id,
                "query_b64": base64.b64encode(query.encode("utf-8")).decode("ascii"),
                "source_url_b64": (
                    base64.b64encode(source_url.encode("utf-8")).decode("ascii")
                    if source_url else ""
                ),
                "telegram_input_id": str(source_context.get("id") or ""),
                "classification": str(source_context.get("classification") or ""),
                "input_kind": str(source_context.get("input_kind") or ""),
                "memory_event_id": str(source_context.get("memory_event_id") or ""),
            },
        )
        watched = self.watcher.wait_for_completion(
            repository=self.repository,
            run_id=dispatched.run_id,
        )
        if not watched.succeeded:
            raise FreshResearchError(
                f"fresh research workflow failed run_id={dispatched.run_id} "
                f"status={watched.status} conclusion={watched.conclusion}"
            )
        output_dir = self.artifact_root / str(dispatched.run_id)
        self.artifacts.download(
            repository=self.repository,
            run_id=dispatched.run_id,
            artifact_name=FRESH_RESEARCH_ARTIFACT,
            output_dir=output_dir,
        )
        files = sorted(output_dir.rglob("result.json"))
        if len(files) != 1:
            raise FreshResearchError(
                f"expected one fresh research result.json, found {len(files)}"
            )
        try:
            payload = json.loads(files[0].read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise FreshResearchError("invalid fresh research artifact") from exc
        return payload, f"github-actions:{dispatched.run_id}"


def _validate_packet(packet: dict[str, Any], *, execution_id: str) -> None:
    if not isinstance(packet, dict):
        raise FreshResearchError("fresh research packet is not an object")
    if packet.get("status") != "PASS":
        raise FreshResearchError("fresh research did not pass")
    if packet.get("execution_id") != execution_id:
        raise FreshResearchError("fresh research execution lineage mismatch")
    if not str(packet.get("checked_at") or "").strip():
        raise FreshResearchError("fresh research has no checked_at timestamp")
    official = packet.get("official_sources")
    if not isinstance(official, list) or not official:
        raise FreshResearchError("fresh research has no official Rockstar source")
    for source in official:
        if not isinstance(source, dict):
            raise FreshResearchError("fresh research official source is malformed")
        url = str(source.get("url") or "")
        resolved_url = str(source.get("resolved_url") or url)
        allowed = ("https://www.rockstargames.com/", "https://store.rockstargames.com/")
        if not url.startswith(allowed) or not resolved_url.startswith(allowed):
            raise FreshResearchError(
                "fresh research official source escaped Rockstar allowlist after resolution"
            )
        if source.get("source_hierarchy") not in (None, "OFFICIAL_PRIMARY"):
            raise FreshResearchError("fresh research official source hierarchy mismatch")
        if source.get("original_source") not in (None, True):
            raise FreshResearchError("fresh research official source is not direct evidence")
        if not str(source.get("content_excerpt") or "").strip():
            raise FreshResearchError("fresh research official source has no evidence text")


def execute_fresh_gta6_research_capability(
    *,
    query: str,
    authorization: HarnessAuthorization | dict[str, Any] | str,
    routing_decision: HarnessRoutingDecision,
    transport: FreshResearchTransport | None = None,
    source_context: dict[str, Any] | None = None,
) -> FreshResearchEvidence:
    auth = validate_harness_authorization(
        authorization,
        expected_action="RESEARCH",
        expected_subject=f"capability:{FRESH_RESEARCH_CAPABILITY_ID}",
    )
    if routing_decision.authorized_action != "RESEARCH":
        raise PermissionError("fresh research routing action mismatch")
    if routing_decision.selected_capability_id != FRESH_RESEARCH_CAPABILITY_ID:
        raise PermissionError("fresh research capability mismatch")
    if routing_decision.selected_executor_binding != FRESH_RESEARCH_EXECUTOR_BINDING:
        raise PermissionError("fresh research executor escaped Registry binding")
    if not str(query or "").strip():
        raise ValueError("fresh research query is required")
    selected_transport = transport or GitHubActionsFreshResearchTransport()
    try:
        if source_context:
            packet, execution_ref = selected_transport.execute(
                query=query.strip(),
                execution_id=auth.execution_id,
                source_context=dict(source_context),
            )
        else:
            packet, execution_ref = selected_transport.execute(
                query=query.strip(),
                execution_id=auth.execution_id,
            )
    except FreshResearchError:
        raise
    except Exception as exc:
        raise FreshResearchError(
            f"fresh research transport failed: {type(exc).__name__}"
        ) from exc
    _validate_packet(packet, execution_id=auth.execution_id)
    return FreshResearchEvidence(
        status="PASS",
        authority=auth.issued_by,
        routing_id=routing_decision.routing_id,
        authorization_id=auth.authorization_id,
        execution_id=auth.execution_id,
        checked_at=str(packet["checked_at"]),
        official_source_count=int(packet.get("official_source_count") or 0),
        secondary_source_count=int(packet.get("secondary_source_count") or 0),
        packet=packet,
        execution_ref=execution_ref,
        artifact_ref=execution_ref,
    )


def research_fresh_gta6_under_harness(
    query: str,
    *,
    transport: FreshResearchTransport | None = None,
    source_context: dict[str, Any] | None = None,
) -> FreshResearchEvidence:
    context = dict(source_context or {})
    telegram_input_id = context.get("id")
    goal_id = (
        f"telegram-source:{telegram_input_id}"
        if telegram_input_id is not None
        else None
    )
    routing = route_harness_request(
        HarnessRoutingRequest(
            intent="collect fresh current GTA6 evidence from official Rockstar and configured sources",
            authorized_action="RESEARCH",
            domain="research",
            task_class=FRESH_RESEARCH_TASK_CLASS,
            goal_id=goal_id,
            required_capability_id=FRESH_RESEARCH_CAPABILITY_ID,
            required_policy_tags=("gta6", "research", "fresh", "cloud", "evidence"),
            provider_required=False,
            fallback_allowed=False,
            zero_cost_operation=True,
            learning_required=True,
        )
    )
    authorization = issue_harness_authorization(
        authorized_action="RESEARCH",
        subject=f"capability:{FRESH_RESEARCH_CAPABILITY_ID}",
        lineage={
            "routing_id": routing.routing_id,
            "capability_id": routing.selected_capability_id,
            "selected_executor_binding": routing.selected_executor_binding,
            "ingress": "telegram",
            "freshness_required": True,
            "task_class": FRESH_RESEARCH_TASK_CLASS,
            "goal_id": goal_id,
            "classification": context.get("classification"),
            "input_kind": context.get("input_kind"),
            "source_url": context.get("source_url"),
            "telegram_input_id": context.get("id"),
            "memory_event_id": context.get("memory_event_id"),
        },
    )
    try:
        return execute_fresh_gta6_research_capability(
            query=query,
            authorization=authorization,
            routing_decision=routing,
            transport=transport,
            source_context=context,
        )
    finally:
        consume_harness_authorization(authorization)
