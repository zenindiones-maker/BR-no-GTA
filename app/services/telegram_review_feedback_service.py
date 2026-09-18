from __future__ import annotations

import re
from typing import Any

from app.services.harness_learning_service import record_human_correction


READY_FOR_HUMAN_REVIEW = "READY_FOR_HUMAN_REVIEW"
RENDER_CAPABILITY_ID = "production.render.execute"
RENDER_SKILL_ID = "vedit.longform.render-profile"


def _caption_fields(caption: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in str(caption or "").splitlines():
        if "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key and value:
            result[key] = value
    return result


def _positive_int(value: Any, label: str) -> int:
    try:
        number = int(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a positive integer") from exc
    if number <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return number


def parse_changes_requested(text: str) -> tuple[str, str] | None:
    clean = str(text or "").strip()
    match = re.match(
        r"^CHANGES_REQUESTED(?:\s+(LOCAL|TASK_CLASS|GLOBAL_CANDIDATE))?\s*:\s*(.+)$",
        clean,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if match is None:
        return None
    scope = str(match.group(1) or "LOCAL").upper()
    correction = str(match.group(2) or "").strip()
    if not correction:
        raise ValueError("CHANGES_REQUESTED correction text is required")
    return scope, correction


def is_render_review_feedback_message(message: dict[str, Any], text: str) -> bool:
    parsed = parse_changes_requested(text)
    if parsed is None:
        return False
    reply = message.get("reply_to_message")
    if not isinstance(reply, dict):
        return False
    fields = _caption_fields(str(reply.get("caption") or reply.get("text") or ""))
    return (
        fields.get("HUMAN_REVIEW_STATE") == READY_FOR_HUMAN_REVIEW
        and fields.get("PUBLICATION_AUTHORITY") == "NONE"
        and "RenderJob" in fields
    )


def record_render_review_feedback(
    *,
    message: dict[str, Any],
    input_record: dict[str, Any],
    text: str,
) -> dict[str, Any]:
    parsed = parse_changes_requested(text)
    if parsed is None:
        raise ValueError("message is not CHANGES_REQUESTED feedback")
    scope, correction = parsed

    reply = message.get("reply_to_message")
    if not isinstance(reply, dict):
        raise ValueError("CHANGES_REQUESTED must reply to the Telegram review message")
    caption = str(reply.get("caption") or reply.get("text") or "")
    fields = _caption_fields(caption)
    if fields.get("HUMAN_REVIEW_STATE") != READY_FOR_HUMAN_REVIEW:
        raise ValueError("feedback target is not READY_FOR_HUMAN_REVIEW")
    if fields.get("PUBLICATION_AUTHORITY") != "NONE":
        raise PermissionError("review feedback must not carry publication authority")

    render_job_id = _positive_int(fields.get("RenderJob"), "RenderJob")
    video_id = _positive_int(fields.get("video_id"), "video_id")
    run_id = _positive_int(fields.get("run_id"), "run_id")
    execution_id = str(fields.get("execution_id") or "").strip()
    if not execution_id:
        raise ValueError("review caption lacks execution_id")
    product_version = str(fields.get("versão") or fields.get("version") or "").strip() or None

    chat_id = _positive_int(input_record.get("telegram_chat_id"), "telegram_chat_id")
    feedback_message_id = _positive_int(
        input_record.get("telegram_message_id"), "telegram_message_id"
    )
    review_message_id = _positive_int(reply.get("message_id"), "review_message_id")

    evidence_refs = (
        f"telegram-review-message:{chat_id}:{review_message_id}",
        f"telegram-feedback-message:{chat_id}:{feedback_message_id}",
        f"telegram-input:{input_record.get('id')}",
        f"memory-event:{input_record.get('memory_event_id')}",
        f"render-job:{render_job_id}",
        f"video:{video_id}",
        f"execution:{execution_id}",
        f"github:run:{run_id}",
    )
    correction_record = record_human_correction(
        context=(
            f"Human review requested changes for RenderJob {render_job_id}, "
            f"video {video_id}, execution {execution_id}."
        ),
        undesired_behavior="Current rendered review did not satisfy the human reviewer.",
        desired_behavior=correction,
        evidence_refs=evidence_refs,
        goal_id=None,
        task_id=f"render-job:{render_job_id}",
        affected_agent="audiovisual-worker",
        affected_capability=RENDER_CAPABILITY_ID,
        affected_skill=RENDER_SKILL_ID,
        metadata={
            "source": "telegram_render_review",
            "review_state": "CHANGES_REQUESTED",
            "telegram_input_id": input_record.get("id"),
            "telegram_chat_id": chat_id,
            "telegram_feedback_message_id": feedback_message_id,
            "telegram_review_message_id": review_message_id,
            "render_job_id": render_job_id,
            "video_id": video_id,
            "execution_id": execution_id,
            "github_run_id": run_id,
            "product_version": product_version,
            "requested_scope": scope,
            "publication_authority": "NONE",
        },
        scope=scope,
    )
    return {
        "HUMAN_FEEDBACK_INGESTION": "PASS",
        "review_state": "CHANGES_REQUESTED",
        "correction_id": correction_record["correction_id"],
        "scope": correction_record["scope"],
        "render_job_id": render_job_id,
        "video_id": video_id,
        "execution_id": execution_id,
        "github_run_id": run_id,
        "affected_capability": RENDER_CAPABILITY_ID,
        "affected_skill": RENDER_SKILL_ID,
        "publication_authority": "NONE",
        "evidence_refs": list(correction_record["evidence_refs"]),
    }
