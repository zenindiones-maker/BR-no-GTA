from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import re
from typing import Any, Mapping

from app.services.harness_authorization_service import (
    consume_harness_authorization,
    issue_harness_authorization,
)
from app.services.harness_capability_service import execute_capability
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest,
    route_harness_request,
)


PRESENTATION_CAPABILITY_ID = "human.presentation.action-first"
PRESENTATION_SKILL_ID = "human.presentation.action-first"
PRESENTATION_EXECUTOR_BINDING = (
    "app.services.human_presentation_service.execute_human_presentation_capability"
)
UPSTREAM_REPOSITORY = "ayghri/i-have-adhd"
UPSTREAM_COMMIT = "b15d0be58f55b33972ba3e39709e0e5208ef30cb"
UPSTREAM_VERSION = "0.3.0"

NORMAL = "NORMAL"
ACTION_FIRST = "ACTION_FIRST"
TECHNICAL_FULL = "TECHNICAL_FULL"
MACHINE_READABLE = "MACHINE_READABLE"
PRESENTATION_MODES = {NORMAL, ACTION_FIRST, TECHNICAL_FULL, MACHINE_READABLE}


@dataclass(frozen=True)
class PresentationResult:
    mode: str
    surface: str
    text: str
    canonical_sha256: str
    canonical_chars: int
    presented_chars: int
    canonical_unchanged: bool
    canonical_lines: int
    presented_lines: int
    canonical_internal_id_mentions: int
    presented_internal_id_mentions: int
    conclusion_present: bool
    next_action_present: bool
    material_warnings_preserved: bool
    evidence_access_present: bool
    capability_id: str = PRESENTATION_CAPABILITY_ID
    skill_id: str = PRESENTATION_SKILL_ID
    upstream_repository: str = UPSTREAM_REPOSITORY
    upstream_commit: str = UPSTREAM_COMMIT
    upstream_version: str = UPSTREAM_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _canonical_json(value: Mapping[str, Any], *, pretty: bool = False) -> str:
    return json.dumps(
        dict(value),
        ensure_ascii=False,
        sort_keys=True,
        indent=2 if pretty else None,
        separators=None if pretty else (",", ":"),
        default=str,
    )


def resolve_presentation_mode(
    *,
    surface: str,
    canonical_result: Mapping[str, Any] | None = None,
    user_intent: str | None = None,
    explicit_mode: str | None = None,
) -> str:
    """Deterministic presentation policy; never performs execution/editorial routing."""
    del canonical_result, user_intent
    if explicit_mode is not None:
        mode = str(explicit_mode).strip().upper()
        if mode not in PRESENTATION_MODES:
            raise ValueError("unsupported presentation mode")
        return mode
    normalized = str(surface or "").strip().lower()
    if normalized in {"telegram", "termux", "work", "codex", "admin"}:
        return ACTION_FIRST
    if normalized in {"artifact", "machine", "api", "json"}:
        return MACHINE_READABLE
    return NORMAL


def _mode_for_surface(surface: str, requested_mode: str | None) -> str:
    return resolve_presentation_mode(
        surface=surface,
        explicit_mode=requested_mode,
    )


def _failure_state(result: Mapping[str, Any]) -> str | None:
    status = str(result.get("status") or "").strip().upper()
    if status in {"FAIL", "FAILED", "BLOCKED", "CANCELLED", "ERROR"}:
        return status
    if result.get("success") is False:
        return "FAIL"
    if str(result.get("fresh_research_status") or "").upper() == "FAIL_CLOSED":
        return "FAIL"
    return None


def _error_detail(result: Mapping[str, Any]) -> str | None:
    error = result.get("error")
    if isinstance(error, Mapping):
        value = error.get("error") or error.get("message") or error.get("code")
        if value:
            return str(value).strip()
    if isinstance(error, str) and error.strip():
        return error.strip()
    value = result.get("fresh_research_error")
    return str(value).strip() if value else None


def _material_warnings(result: Mapping[str, Any]) -> tuple[str, ...]:
    """Return human-relevant warnings without inventing or reclassifying them."""
    collected: list[str] = []

    def add(value: Any, *, label: str) -> None:
        if value in (None, False, "", [], {}, ()):
            return
        if isinstance(value, Mapping):
            detail = value.get("message") or value.get("reason") or value.get("code")
            if detail:
                collected.append(f"{label}: {str(detail).strip()}")
            else:
                collected.append(
                    f"{label}: "
                    + json.dumps(dict(value), ensure_ascii=False, sort_keys=True, default=str)
                )
            return
        if isinstance(value, (list, tuple)):
            for item in value[:3]:
                add(item, label=label)
            return
        if isinstance(value, bool):
            if value:
                collected.append(label)
            return
        collected.append(f"{label}: {str(value).strip()}")

    add(result.get("policy_violation"), label="Policy violation")
    add(result.get("policy_violations"), label="Policy violation")
    add(result.get("warning"), label="Aviso")
    add(result.get("warnings"), label="Aviso")

    # Some canonical executors place policy evidence one level below evidence.
    evidence = result.get("evidence")
    if isinstance(evidence, Mapping):
        add(evidence.get("policy_violation"), label="Policy violation")
        add(evidence.get("policy_violations"), label="Policy violation")

    return tuple(dict.fromkeys(item for item in collected if item))

def _answer(result: Mapping[str, Any]) -> str:
    for key in ("answer", "message", "summary"):
        value = result.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    nested = result.get("result")
    if isinstance(nested, Mapping):
        for key in ("text", "answer", "message", "summary"):
            value = nested.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _source_status(
    result: Mapping[str, Any],
) -> tuple[str | None, str | None, str | None, str | None]:
    intelligence = result.get("source_intelligence")
    if not isinstance(intelligence, Mapping):
        return None, None, None, None
    signal = intelligence.get("editorial_signal")
    decision = None
    if isinstance(signal, Mapping):
        decision = str(signal.get("harness_decision") or "").strip() or None
    claims = intelligence.get("claims")
    verification = None
    if isinstance(claims, list) and claims:
        statuses = {
            str(item.get("verification_status") or "").upper()
            for item in claims
            if isinstance(item, Mapping)
        }
        if "CONTRADICTED" in statuses:
            verification = "CONTRADICTED"
        elif "INSUFFICIENT_EVIDENCE" in statuses:
            verification = "INSUFFICIENT_EVIDENCE"
        elif statuses and statuses == {"VERIFIED"}:
            verification = "VERIFIED"
    resolution = str(intelligence.get("SOURCE_CONTENT_RESOLVED") or "").upper() or None
    hierarchy = str(
        intelligence.get("source_hierarchy")
        or result.get("source_hierarchy")
        or ""
    ).strip().upper() or None
    return resolution, verification, decision, hierarchy


def _action_first(result: Mapping[str, Any]) -> str:
    failure = _failure_state(result)
    answer = _answer(result)
    resolution, verification, decision, hierarchy = _source_status(result)
    warnings = _material_warnings(result)

    if failure:
        detail = _error_detail(result)
        lines = [f"❌ {failure}"]
        if detail:
            lines.append(f"Causa observada: {detail}")
        lines.extend(f"⚠️ {item}" for item in warnings)
        if answer:
            lines.append(f"Ação: {answer}")
        else:
            lines.append("Ação: consulte /evidence para o diagnóstico completo.")
        return "\n".join(lines)

    if resolution or verification or decision:
        if resolution == "FAIL":
            headline = "❌ Falha ao resolver a fonte"
        elif verification == "VERIFIED":
            headline = "✅ Fonte analisada"
        elif verification == "CONTRADICTED":
            headline = "⚠️ Alegação contraditada"
        elif verification == "INSUFFICIENT_EVIDENCE":
            headline = "⚠️ Evidência insuficiente"
        else:
            headline = "✅ Fonte analisada"
        lines = [headline]
        if answer:
            lines.append(f"Resultado: {answer}")
        if verification:
            lines.append(f"Verificação: {verification}")
        if hierarchy:
            hierarchy_labels = {
                "OFFICIAL_PRIMARY": "fonte primária oficial",
                "PRIMARY_STATEMENT_REPORTED_BY_SECONDARY": (
                    "declaração primária relatada por fonte secundária"
                ),
                "MULTIPLE_INDEPENDENT_REPORTS": "múltiplas fontes independentes",
            }
            lines.append("Evidência: " + hierarchy_labels.get(hierarchy, hierarchy))
        if decision:
            lines.append(f"Ação do Harness: {decision}")
            lines.append(
                "Uso editorial: "
                + ("SIM" if decision in {"USE_FOR_VIDEO", "MERGE_WITH_EXISTING_GOAL", "STORE_FOR_FUTURE"} else "NÃO")
            )
        lines.extend(f"⚠️ {item}" for item in warnings)
        lines.append("Digite /evidence para auditoria completa.")
        return "\n".join(lines)

    if answer:
        if warnings:
            return "\n".join([answer, *(f"⚠️ {item}" for item in warnings)])
        return answer
    status = str(result.get("status") or "").strip()
    base = status or "Concluído."
    if warnings:
        return "\n".join([base, *(f"⚠️ {item}" for item in warnings)])
    return base


_INTERNAL_TELEMETRY_PATTERN = re.compile(
    r"(?i)\\b(?:routing_id|authorization_id|memory_id|competence(?:_id)?|"
    r"executor_binding|provider(?:_id)?|model(?:_id)?|artifact_id|database_id|"
    r"episode_id|claim_id|signal_id|sha256)\\b"
)


def _line_count(text: str) -> int:
    return 0 if text == "" else text.count("\n") + 1


def _internal_id_mentions(text: str) -> int:
    return len(_INTERNAL_TELEMETRY_PATTERN.findall(text))


def _presentation_metrics(
    canonical_result: Mapping[str, Any],
    *,
    canonical_pretty: str,
    presented_text: str,
    mode: str,
) -> dict[str, Any]:
    warnings = _material_warnings(canonical_result)
    conclusion_present = bool(
        _answer(canonical_result)
        or _failure_state(canonical_result)
        or any(_source_status(canonical_result))
        or str(canonical_result.get("status") or "").strip()
    )
    next_action_present = (
        "Ação:" in presented_text
        or "Ação do Harness:" in presented_text
        or "Próximo passo:" in presented_text
        or "/evidence" in presented_text
    )
    return {
        "canonical_lines": _line_count(canonical_pretty),
        "presented_lines": _line_count(presented_text),
        "canonical_internal_id_mentions": _internal_id_mentions(canonical_pretty),
        "presented_internal_id_mentions": _internal_id_mentions(presented_text),
        "conclusion_present": conclusion_present,
        "next_action_present": next_action_present,
        "material_warnings_preserved": all(item in presented_text for item in warnings),
        "evidence_access_present": (
            mode in {TECHNICAL_FULL, MACHINE_READABLE}
            or "/evidence" in presented_text
        ),
    }


def render_human_presentation(
    canonical_result: Mapping[str, Any],
    *,
    surface: str,
    mode: str | None = None,
) -> PresentationResult:
    if not isinstance(canonical_result, Mapping):
        raise TypeError("canonical_result must be a mapping")
    canonical_copy = deepcopy(dict(canonical_result))
    before = _canonical_json(canonical_copy)
    selected_mode = resolve_presentation_mode(
        surface=surface,
        canonical_result=canonical_copy,
        explicit_mode=mode,
    )

    if selected_mode == MACHINE_READABLE:
        text = before
    elif selected_mode == TECHNICAL_FULL:
        text = _canonical_json(canonical_copy, pretty=True)
    elif selected_mode == ACTION_FIRST:
        text = _action_first(canonical_copy)
    else:
        text = _answer(canonical_copy) or _action_first(canonical_copy)

    after = _canonical_json(canonical_copy)
    metrics = _presentation_metrics(
        canonical_copy,
        canonical_pretty=_canonical_json(canonical_copy, pretty=True),
        presented_text=text,
        mode=selected_mode,
    )
    return PresentationResult(
        mode=selected_mode,
        surface=str(surface or "unknown"),
        text=text,
        canonical_sha256=sha256(before.encode("utf-8")).hexdigest(),
        canonical_chars=len(before),
        presented_chars=len(text),
        canonical_unchanged=before == after,
        canonical_lines=metrics["canonical_lines"],
        presented_lines=metrics["presented_lines"],
        canonical_internal_id_mentions=metrics["canonical_internal_id_mentions"],
        presented_internal_id_mentions=metrics["presented_internal_id_mentions"],
        conclusion_present=metrics["conclusion_present"],
        next_action_present=metrics["next_action_present"],
        material_warnings_preserved=metrics["material_warnings_preserved"],
        evidence_access_present=metrics["evidence_access_present"],
    )


def execute_human_presentation_capability(_capability, payload: dict[str, Any]) -> dict[str, Any]:
    canonical = payload.get("canonical_result")
    if not isinstance(canonical, Mapping):
        raise ValueError("presentation requires canonical_result")
    result = render_human_presentation(
        canonical,
        surface=str(payload.get("surface") or "human"),
        mode=payload.get("mode"),
    )
    if not result.canonical_unchanged:
        raise RuntimeError("presentation mutated canonical result")
    return result.to_dict()


def present_canonical_result_under_harness(
    canonical_result: Mapping[str, Any],
    *,
    surface: str,
    mode: str | None = None,
    lineage: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    selected_mode = resolve_presentation_mode(
        surface=surface,
        canonical_result=canonical_result,
        explicit_mode=mode,
    )
    routing = route_harness_request(
        HarnessRoutingRequest(
            intent=f"present canonical result to human surface={surface} mode={selected_mode}",
            authorized_action="DECISION",
            domain="human-presentation",
            required_capability_id=PRESENTATION_CAPABILITY_ID,
            required_policy_tags=("presentation", "human", "no-authority"),
            provider_required=False,
            fallback_allowed=False,
            zero_cost_operation=True,
        )
    )
    authorization = issue_harness_authorization(
        authorized_action="DECISION",
        subject=f"capability:{PRESENTATION_CAPABILITY_ID}",
        lineage={
            "routing_id": routing.routing_id,
            "capability_id": routing.selected_capability_id,
            "selected_executor_binding": routing.selected_executor_binding,
            "surface": surface,
            "presentation_mode": selected_mode,
            "canonical_sha256": sha256(
                _canonical_json(canonical_result).encode("utf-8")
            ).hexdigest(),
            "authority_scope": "presentation_only",
            "memory_write": False,
            "routing_authority": False,
            "publication_authority": False,
            **{
                str(key): value
                for key, value in dict(lineage or {}).items()
                if value is not None
            },
        },
    )
    try:
        evidence = execute_capability(
            capability_id=PRESENTATION_CAPABILITY_ID,
            authorization=authorization,
            payload={
                "canonical_result": dict(canonical_result),
                "surface": surface,
                "mode": selected_mode,
            },
            routing_decision=routing,
            executor=execute_human_presentation_capability,
        )
    finally:
        consume_harness_authorization(authorization)
    if evidence.status != "EXECUTED" or not isinstance(evidence.result, dict):
        raise RuntimeError("presentation capability did not execute")
    result = dict(evidence.result)
    result.update(
        {
            "authority": authorization.issued_by,
            "routing_id": routing.routing_id,
            "authorization_id": authorization.authorization_id,
            "authorization_status": "consumed",
            "no_memory_authority": True,
            "no_routing_authority": True,
            "no_publication_authority": True,
        }
    )
    return result
