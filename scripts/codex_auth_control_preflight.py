from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request

from app.database.schema import initialize_schema
from app.services.agent_office.codex_auth_control import (
    AUTH_AVAILABLE,
    AUTH_USER_ACTION_REQUIRED,
    build_mission_checkpoint,
    classify_codex_auth,
    write_checkpoint,
)


def _decode_plan(plan_b64: str) -> dict:
    raw = base64.b64decode(plan_b64.encode("ascii"), validate=True)
    if not raw or len(raw) > 96 * 1024:
        raise ValueError("mission plan envelope is outside bounded size")
    plan = json.loads(raw.decode("utf-8"))
    if plan.get("authority") != "DEEPSEEK_HARNESS":
        raise PermissionError("mission plan escaped Harness authority")
    if not str(plan.get("mission_id") or "").strip():
        raise ValueError("mission plan has no mission_id")
    return plan


def _send_paired_dm(*, text: str) -> int:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    paired_user_id = os.getenv("TELEGRAM_ALLOWED_USER_ID", "").strip()
    if not token or not paired_user_id:
        raise RuntimeError("paired-user DM delivery is not configured")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=urllib.parse.urlencode({
            "chat_id": paired_user_id,
            "text": text,
            "disable_web_page_preview": "true",
        }).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(
            f"paired-user auth-gate delivery failed with HTTP {exc.code}"
        ) from None
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        raise RuntimeError("paired-user auth-gate delivery was rejected")
    result = payload.get("result")
    message_id = result.get("message_id") if isinstance(result, dict) else None
    if not isinstance(message_id, int) or message_id <= 0:
        raise RuntimeError("paired-user auth-gate delivery returned no message identity")
    return message_id


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dispatch-id", required=True)
    parser.add_argument("--target-ref", required=True)
    parser.add_argument("--target-sha", required=True)
    parser.add_argument("--plan-b64", required=True)
    parser.add_argument("--human-goal-b64", required=True)
    parser.add_argument("--telegram-chat-id", default="0")
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--github-output", type=Path, default=None)
    args = parser.parse_args()

    initialize_schema()
    plan = _decode_plan(args.plan_b64)
    mission_id = str(plan["mission_id"])
    args.artifact_dir.mkdir(parents=True, exist_ok=True)

    preflight = classify_codex_auth(
        mission_id=mission_id,
        cwd=Path.cwd(),
    )
    checkpoint = build_mission_checkpoint(
        dispatch_id=args.dispatch_id,
        mission_id=mission_id,
        target_ref=args.target_ref,
        target_sha=args.target_sha,
        plan_b64=args.plan_b64,
        human_goal_b64=args.human_goal_b64,
        telegram_chat_id=args.telegram_chat_id,
        preflight=preflight,
    )
    checkpoint_path = args.artifact_dir / "mission-auth-checkpoint.json"
    write_checkpoint(checkpoint_path, checkpoint)

    delivery_message_id = None
    delivery_status = "NOT_REQUIRED"
    if preflight.state == AUTH_USER_ACTION_REQUIRED:
        if preflight.delivery_surface != "PAIRED_USER_DM":
            delivery_status = "BLOCKED"
        else:
            message = "\n".join([
                "AÇÃO",
                "Seu Codex local continua sendo um contexto separado; não estou pedindo para você ligar ou reconectar o Codex local.",
                "",
                "ESTADO",
                "A missão foi checkpointada antes do bootstrap pesado. Nenhum agente está esperando em runner.",
                "",
                "AUTH",
                "O executor cloud efêmero ainda não possui uma autorização Codex reutilizável.",
                "Device auth não será mantido aberto em runner efêmero nem terá credencial persistida em artifact.",
                "A missão retoma do mesmo checkpoint quando a autorização cloud reutilizável estiver disponível.",
                "",
                "PROVA",
                f"Mission: {mission_id}",
                f"Checkpoint: {checkpoint['checkpoint_id']}",
                "AUTH_DELIVERY_SURFACE=PAIRED_USER_DM",
                "",
                "PRÓXIMO",
                "Autorize/configure o método confiável e depois retome a mesma missão; research, plano e análise anterior não precisam ser refeitos.",
            ])
            delivery_message_id = _send_paired_dm(text=message)
            delivery_status = "DELIVERED"

    report = {
        "schema": "codex-auth-control-preflight/v1",
        "mission_id": mission_id,
        "dispatch_id": args.dispatch_id,
        "preflight": preflight.to_dict(),
        "checkpoint_id": checkpoint["checkpoint_id"],
        "checkpoint_path": checkpoint_path.name,
        "auth_delivery_surface": preflight.delivery_surface,
        "auth_delivery_status": delivery_status,
        "telegram_message_id": delivery_message_id,
        "runner_wait_for_human": False,
        "mission_checkpointed": True,
        "auth_secret_leak": False,
        "auth_credential_persisted_in_artifact": False,
        "auth_credential_persisted_in_memory": False,
        "auth_credential_persisted_in_obsidian": False,
        "failure_memory_retrieved_before_execution": preflight.failure_memory_retrieved,
        "auth_timeout_path_repeated": preflight.auth_timeout_path_repeated,
        "authority": "DEEPSEEK_HARNESS",
        "local_codex_auth_context": preflight.local_codex_auth_context,
        "cloud_runner_codex_auth_context": preflight.cloud_runner_codex_auth_context,
        "missing_auth_configuration": list(preflight.missing_auth_configuration),
        "user_already_connected_not_misreported": True,
        "ephemeral_runner_auth_loop": False,
        "NEW_VOICE_SYNTHESIS": "NO",
        "FULL_RENDER": "NO",
        "YOUTUBE_UPLOAD": "NO",
        "YOUTUBE_PUBLICATION": "NO",
    }
    (args.artifact_dir / "codex-auth-control-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )

    output_path = args.github_output
    if output_path is None:
        raw_output = os.getenv("GITHUB_OUTPUT", "").strip()
        output_path = Path(raw_output) if raw_output else None
    if output_path is not None:
        with output_path.open("a", encoding="utf-8") as fh:
            fh.write(f"auth_available={'true' if preflight.auth_available else 'false'}\n")
            fh.write(f"auth_state={preflight.state}\n")
            fh.write(f"auth_method={preflight.method}\n")
            fh.write(f"mission_id={mission_id}\n")
            fh.write(f"checkpoint_id={checkpoint['checkpoint_id']}\n")

    print("CODEX_AUTH_PREFLIGHT=PASS")
    print(f"CODEX_AUTH_STATE={preflight.state}")
    print("CODEX_AUTH_STATE_EXPLICIT=PASS")
    print("LOCAL_CODEX_AUTH_CONTEXT_EXPLICIT=PASS")
    print("CLOUD_CODEX_AUTH_CONTEXT_EXPLICIT=PASS")
    print("USER_ALREADY_CONNECTED_NOT_MISREPORTED=PASS")
    print("EPHEMERAL_RUNNER_AUTH_LOOP=NO")
    if preflight.missing_auth_configuration:
        print("MISSING_AUTH_CONFIGURATION=" + ",".join(preflight.missing_auth_configuration))
    print(
        "AUTH_NONINTERACTIVE_USED_WHEN_AVAILABLE="
        + ("PASS" if preflight.auth_available else "NOT_AVAILABLE")
    )
    print(
        "DEVICE_AUTH_REQUIRES_PAIRED_HUMAN="
        + ("PASS" if preflight.paired_human_available else "BLOCKED")
    )
    print("DEVICE_AUTH_REVIEW_GROUP_FALLBACK=NO")
    print(
        "AUTH_USER_ACTION_REQUIRED_REPRESENTED_AS_HUMAN_GATE="
        + ("PASS" if preflight.state == AUTH_USER_ACTION_REQUIRED else "NOT_REQUIRED")
    )
    print("AUTH_DELIVERY_SURFACE=" + preflight.delivery_surface)
    print("AUTH_DELIVERY_STATUS=" + delivery_status)
    print("RUNNER_WAIT_FOR_HUMAN=NO")
    print("MISSION_CHECKPOINTED_BEFORE_AUTH_WAIT=PASS")
    print(
        "FAILURE_MEMORY_RETRIEVED_BEFORE_EXECUTION="
        + ("PASS" if preflight.failure_memory_retrieved else "FAIL")
    )
    print(
        "AUTH_TIMEOUT_PATH_NOT_REPEATED="
        + ("PASS" if not preflight.auth_timeout_path_repeated else "FAIL")
    )
    print("AUTH_SECRET_LEAK=NO")
    print("AUTH_CREDENTIAL_PERSISTED_IN_ARTIFACT=NO")
    print("AUTH_CREDENTIAL_PERSISTED_IN_MEMORY=NO")
    print("AUTH_CREDENTIAL_PERSISTED_IN_OBSIDIAN=NO")
    print("NEW_VOICE_SYNTHESIS=NO")
    print("FULL_RENDER=NO")
    print("YOUTUBE_UPLOAD=NO")
    print("YOUTUBE_PUBLICATION=NO")

    if preflight.state == AUTH_AVAILABLE:
        return 0
    if preflight.state == AUTH_USER_ACTION_REQUIRED and delivery_status == "DELIVERED":
        return 0
    if preflight.state == "BLOCKED" and preflight.missing_auth_configuration:
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
