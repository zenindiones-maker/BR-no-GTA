from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

from app.main import initialize_application
from app.database.telegram_user_input_repository import (
    get_telegram_user_input,
    list_recent_telegram_user_inputs,
)
from app.services.telegram_obsidian_attachment_bridge_service import (
    DEFAULT_MAX_FILE_BYTES,
    materialize_staged_telegram_attachment_under_harness,
)
from scripts.telegram_harness_gateway import TelegramApi


def _select_input(input_id: int | None) -> dict[str, Any]:
    if input_id is not None:
        record = get_telegram_user_input(int(input_id))
        if record is None:
            raise RuntimeError("TELEGRAM_INPUT_NOT_FOUND")
        return record
    for record in list_recent_telegram_user_inputs(limit=200):
        if record.get("remote_verified") is not True:
            continue
        if str(record.get("classification") or "") in {
            "owner_voice_reference",
            "brand_asset",
        }:
            continue
        if not str(record.get("telegram_file_id") or "").strip():
            continue
        if (
            str(
                record.get("obsidian_materialization_status")
                or "NOT_REQUESTED"
            )
            == "MATERIALIZED"
        ):
            continue
        return record
    raise RuntimeError("NO_PENDING_TELEGRAM_ATTACHMENT_FOR_OBSIDIAN")


def _stage_and_materialize(
    *,
    api: TelegramApi,
    record: dict[str, Any],
    vault_root: Path | None,
) -> dict[str, Any]:
    file_id = str(record.get("telegram_file_id") or "").strip()
    if not file_id:
        raise RuntimeError("TELEGRAM_FILE_ID_UNAVAILABLE")
    declared_size = record.get("file_size")
    if (
        isinstance(declared_size, int)
        and declared_size > DEFAULT_MAX_FILE_BYTES
    ):
        raise RuntimeError("TELEGRAM_BOT_DOWNLOAD_LIMIT_EXCEEDED")

    staging_root = (
        Path.home() / ".local/state/br-no-gta/telegram-obsidian-bridge"
    )
    staging_root.mkdir(parents=True, exist_ok=True)
    try:
        staging_root.chmod(0o700)
    except OSError:
        pass
    staging = (
        staging_root
        / f"backfill-{int(record['id'])}-{os.getpid()}.part"
    )
    staging.unlink(missing_ok=True)
    try:
        api.download_file(
            file_id,
            staging,
            max_bytes=DEFAULT_MAX_FILE_BYTES,
        )
        return materialize_staged_telegram_attachment_under_harness(
            input_record=record,
            source_path=staging,
            vault_root=vault_root,
        )
    finally:
        staging.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill one verified Telegram attachment into the configured "
            "BR-no-GTA Obsidian vault."
        )
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--input-id", type=int)
    group.add_argument("--latest", action="store_true")
    parser.add_argument("--vault-root", type=Path)
    args = parser.parse_args(argv)

    token = str(os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    if not token:
        print(
            "TELEGRAM_OBSIDIAN_BRIDGE=FAIL TRANSPORT_CREDENTIAL_UNAVAILABLE",
            file=sys.stderr,
        )
        return 2

    initialize_application()
    record = _select_input(args.input_id)
    result = _stage_and_materialize(
        api=TelegramApi(token),
        record=record,
        vault_root=args.vault_root,
    )
    safe = {
        key: result.get(key)
        for key in (
            "status",
            "telegram_input_id",
            "obsidian_attachment_ref",
            "obsidian_note_ref",
            "content_sha256",
            "size_bytes",
            "normalization_state",
            "normalization_engine",
            "normalization_diagnostic",
            "normalized_markdown_ref",
            "canonical_memory_promoted",
            "obsidian_authority",
            "transport_secrets_persisted_in_obsidian",
            "media_bytes_on_a15",
        )
    }
    print(json.dumps(safe, ensure_ascii=False, sort_keys=True))
    print("TELEGRAM_OBSIDIAN_BRIDGE=PASS")
    print(f"TELEGRAM_INPUT_ID={safe['telegram_input_id']}")
    print(f"OBSIDIAN_NOTE_REF={safe['obsidian_note_ref']}")
    print(f"OBSIDIAN_ATTACHMENT_REF={safe['obsidian_attachment_ref']}")
    print(f"CONTENT_SHA256={safe['content_sha256']}")
    print(f"NORMALIZATION_STATE={safe['normalization_state']}")
    print(f"NORMALIZATION_ENGINE={safe['normalization_engine']}")
    if safe.get("normalization_diagnostic"):
        print(f"NORMALIZATION_DIAGNOSTIC={safe['normalization_diagnostic']}")
    print("TRANSPORT_SECRET_IN_OBSIDIAN=NO")
    print("CANONICAL_MEMORY_PROMOTED=NO")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
