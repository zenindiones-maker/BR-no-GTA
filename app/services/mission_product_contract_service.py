from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from app.services.human_review_quality_gate import (
    TARGET_MIN_SECONDS,
    TARGET_PREFERRED_MAX_SECONDS,
)
from app.services.pronunciation_service import DEFAULT_LOCALE, DEFAULT_VOICE


MISSION_PRODUCT_CONTRACT_SCHEMA = "MissionProductContract/v1"
BR_NO_GTA_PRODUCT_ID = "BR-no-GTA"
BR_NO_GTA_MASTER_PROFILE = "1920x1080@30 H264 AAC"
BR_NO_GTA_SEMANTIC_PLANNING_BOUNDARY = (
    "PREPRODUCTION_THROUGH_PRODUCTION_PLAN"
)
_MAX_PLANNER_CONTRACT_BYTES = 8192

_DURATION_RANGE_RE = re.compile(
    r"(?<!\d)(\d+(?:[.,]\d+)?)\s*"
    r"(?:-|–|—|a|até|to)\s*"
    r"(\d+(?:[.,]\d+)?)\s*"
    r"(?:min(?:uto)?s?|minutes?)\b",
    re.IGNORECASE,
)
_DURATION_SINGLE_RE = re.compile(
    r"(?<!\d)(\d+(?:[.,]\d+)?)\s*"
    r"(?:min(?:uto)?s?|minutes?)\b",
    re.IGNORECASE,
)


def _number(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if number < 0:
        raise ValueError(f"{field} must be non-negative")
    return number


def validate_mission_product_contract(
    contract: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(contract, dict):
        raise ValueError("mission product contract must be an object")
    if contract.get("schema") != MISSION_PRODUCT_CONTRACT_SCHEMA:
        raise ValueError("unsupported mission product contract schema")

    duration = contract.get("duration")
    if not isinstance(duration, dict):
        raise ValueError("mission product contract duration is required")
    minimum_final = _number(
        duration.get("minimum_final_duration_seconds"),
        "minimum_final_duration_seconds",
    )
    target = duration.get("target_final_duration_seconds")
    if not isinstance(target, dict):
        raise ValueError("target_final_duration_seconds is required")
    target_minimum = _number(target.get("minimum"), "target duration minimum")
    target_maximum = _number(target.get("maximum"), "target duration maximum")
    supported_minutes = _number(
        duration.get("minimum_supported_editorial_duration_minutes"),
        "minimum_supported_editorial_duration_minutes",
    )
    if target_minimum < minimum_final or target_maximum < target_minimum:
        raise ValueError("mission product duration range is inconsistent")
    if supported_minutes * 60.0 < minimum_final:
        raise ValueError("supported editorial duration is below final minimum")
    if duration.get("artificial_padding_forbidden") is not True:
        raise ValueError("artificial padding must be forbidden")

    review = contract.get("human_review")
    if not isinstance(review, dict):
        raise ValueError("mission product human_review is required")
    if str(review.get("primary_interface") or "").casefold() != "telegram":
        raise ValueError("Telegram must remain the primary human interface")
    if review.get("youtube_private_hd_review_required") is not True:
        raise ValueError("private HD review requirement must remain enabled")
    if str(review.get("youtube_review_privacy") or "").upper() != "PRIVATE":
        raise ValueError("YouTube review privacy must remain PRIVATE")

    publication = contract.get("publication")
    if not isinstance(publication, dict):
        raise ValueError("mission product publication policy is required")
    if publication.get("public_release_allowed") is not False:
        raise ValueError("public release must remain forbidden")
    if publication.get("unlisted_release_allowed") is not False:
        raise ValueError("unlisted release must remain forbidden")

    planning = contract.get("semantic_planning")
    if not isinstance(planning, dict) or not str(
        planning.get("boundary") or ""
    ).strip():
        raise ValueError("semantic planning boundary is required")

    narration = contract.get("narration")
    if not isinstance(narration, dict) or not str(
        narration.get("voice") or ""
    ).strip():
        raise ValueError("narration voice is required")
    if not str(contract.get("master_profile") or "").strip():
        raise ValueError("master profile is required")
    return contract


def canonical_mission_product_contract_json(
    contract: dict[str, Any],
) -> str:
    validated = validate_mission_product_contract(dict(contract))
    return json.dumps(
        validated,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def mission_product_contract_digest(contract: dict[str, Any]) -> str:
    canonical = canonical_mission_product_contract_json(contract)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def bounded_planner_product_contract_projection(
    contract: dict[str, Any],
) -> dict[str, Any]:
    canonical = canonical_mission_product_contract_json(contract)
    if len(canonical.encode("utf-8")) > _MAX_PLANNER_CONTRACT_BYTES:
        raise ValueError("mission product contract exceeds planner projection bound")
    # The current contract is intentionally small enough that the bounded
    # projection is lossless: no hard product fact is summarized away.
    return json.loads(canonical)


def materialize_br_no_gta_mission_product_contract() -> dict[str, Any]:
    contract = {
        "schema": MISSION_PRODUCT_CONTRACT_SCHEMA,
        "product_id": BR_NO_GTA_PRODUCT_ID,
        "duration": {
            "minimum_final_duration_seconds": int(TARGET_MIN_SECONDS),
            "target_final_duration_seconds": {
                "minimum": int(TARGET_MIN_SECONDS),
                "maximum": int(TARGET_PREFERRED_MAX_SECONDS),
            },
            "minimum_supported_editorial_duration_minutes": (
                float(TARGET_MIN_SECONDS) / 60.0
            ),
            "artificial_padding_forbidden": True,
        },
        "master_profile": BR_NO_GTA_MASTER_PROFILE,
        "narration": {
            "locale": DEFAULT_LOCALE,
            "voice": DEFAULT_VOICE,
        },
        "human_review": {
            "primary_interface": "telegram",
            "telegram_surface": "telegram_group",
            "youtube_review_privacy": "PRIVATE",
            "youtube_private_hd_review_required": True,
        },
        "publication": {
            "public_release_allowed": False,
            "unlisted_release_allowed": False,
        },
        "subtitles": {
            "burned_subtitles": False,
        },
        "semantic_planning": {
            "boundary": BR_NO_GTA_SEMANTIC_PLANNING_BOUNDARY,
            "downstream_execution_orchestrated_by_workflow": True,
        },
    }
    return validate_mission_product_contract(contract)


def _proposal_text_fragments(proposal: Any) -> list[tuple[str, str]]:
    if hasattr(proposal, "to_dict"):
        proposal = proposal.to_dict()
    if not isinstance(proposal, dict):
        raise ValueError("mission plan proposal must be an object")
    fragments: list[tuple[str, str]] = []

    def walk(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                walk(item, f"{path}.{key}" if path else str(key))
        elif isinstance(value, (list, tuple)):
            for index, item in enumerate(value):
                walk(item, f"{path}[{index}]")
        elif isinstance(value, str) and value.strip():
            fragments.append((path, value))

    walk(proposal, "proposal")
    return fragments


def _duration_mentions_minutes(text: str) -> list[tuple[float, float]]:
    mentions: list[tuple[float, float]] = []
    range_spans: list[tuple[int, int]] = []
    for match in _DURATION_RANGE_RE.finditer(text):
        low = float(match.group(1).replace(",", "."))
        high = float(match.group(2).replace(",", "."))
        mentions.append((min(low, high), max(low, high)))
        range_spans.append(match.span())
    for match in _DURATION_SINGLE_RE.finditer(text):
        if any(
            start <= match.start() and match.end() <= end
            for start, end in range_spans
        ):
            continue
        value = float(match.group(1).replace(",", "."))
        mentions.append((value, value))
    return mentions


def mission_plan_product_contract_violations(
    proposal: Any,
    contract: dict[str, Any],
) -> tuple[str, ...]:
    validate_mission_product_contract(contract)
    duration = contract["duration"]
    target = duration["target_final_duration_seconds"]
    target_min = float(target["minimum"])
    target_max = float(target["maximum"])
    violations: list[str] = []
    duration_mention_count = 0
    proposal_mapping = (
        proposal.to_dict() if hasattr(proposal, "to_dict") else proposal
    )
    duration_required = False
    if isinstance(proposal_mapping, dict):
        for task in proposal_mapping.get("tasks") or ():
            if not isinstance(task, dict):
                continue
            task_text = " ".join(
                str(task.get(key) or "")
                for key in ("task_class", "objective", "expected_output")
            ).casefold()
            if any(
                marker in task_text
                for marker in (
                    "editorial",
                    "script",
                    "content",
                    "production-plan",
                    "production plan",
                )
            ):
                duration_required = True
                break

    for path, text in _proposal_text_fragments(proposal):
        mentions = _duration_mentions_minutes(text)
        duration_mention_count += len(mentions)
        for low_minutes, high_minutes in mentions:
            low_seconds = low_minutes * 60.0
            high_seconds = high_minutes * 60.0
            if low_seconds < target_min or high_seconds > target_max:
                violations.append(
                    "PRODUCT_DURATION_CONTRACT_VIOLATION:"
                    f"path={path}:"
                    f"observed={low_minutes:g}-{high_minutes:g}min:"
                    f"required={target_min / 60.0:g}-{target_max / 60.0:g}min"
                )
        folded = " ".join(text.casefold().split())
        if duration.get("artificial_padding_forbidden") is True and any(
            phrase in folded
            for phrase in (
                "artificial padding allowed",
                "allow artificial padding",
                "padding permitido",
                "permitir padding",
                "use filler",
                "add filler",
                "usar filler",
            )
        ):
            violations.append(
                "PRODUCT_ARTIFICIAL_PADDING_CONTRACT_VIOLATION:"
                f"path={path}"
            )
    if duration_required and duration_mention_count == 0:
        violations.append("PRODUCT_DURATION_CONTRACT_MISSING")
    return tuple(dict.fromkeys(violations))


def validate_mission_plan_product_contract(
    proposal: Any,
    contract: dict[str, Any],
) -> dict[str, Any]:
    violations = mission_plan_product_contract_violations(proposal, contract)
    return {
        "schema": "MissionPlanProductContractValidation/v1",
        "product_contract_digest": mission_product_contract_digest(contract),
        "valid": not violations,
        "violations": list(violations),
    }
