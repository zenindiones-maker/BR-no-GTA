"""Typed, fail-closed GitHub Actions outputs for one BR_OWNER_V1 audition.

No biometrics or Telegram media are read or written here. The existing
DeepSeek Harness remains sole authority; this only routes already-evaluated
audition outcomes to the existing approved delivery workers.
"""
from __future__ import annotations

import os
import re
import stat
from pathlib import Path

_CLONE_ID=re.compile(r"^BR_OWNER_V1_SINGLE_CLONE_[A-Za-z0-9_-]+$")


def write_delivery_step_outputs(
    *,
    output_path: Path,
    manifest_path: Path,
    clone_id: str,
    send_eligible: bool,
    critical_scope: bool,
    control_only: bool = False,
) -> None:
    """Atomically prepare the complete routing record for GitHub Actions.

    Missing or malformed outputs must fail the generating step rather than
    allow an ambiguous external delivery. No separate or fallback speaker.
    """
    if any(type(flag) is not bool for flag in (send_eligible,critical_scope,control_only)):
        raise ValueError("OWNER_CLONE_OUTPUT_FLAGS_NOT_BOOLEAN")
    if control_only and (critical_scope or not send_eligible):
        raise ValueError("OWNER_CLONE_CONTROL_ROUTE_INVALID")
    if not isinstance(clone_id,str) or not _CLONE_ID.fullmatch(clone_id):
        raise ValueError("OWNER_CLONE_OUTPUT_ID_INVALID")
    if (not isinstance(manifest_path,Path) or not manifest_path.is_absolute()
        or manifest_path.is_symlink() or not manifest_path.is_file()
        or manifest_path.suffix!=".json" or any(ord(c) in (10,13) for c in str(manifest_path))):
        raise ValueError("OWNER_CLONE_MANIFEST_OUTPUT_INVALID")
    if (not isinstance(output_path,Path) or not output_path.is_absolute()
        or output_path.is_symlink() or not output_path.is_file()
        or any(ord(c) in (10,13) for c in str(output_path))):
        raise RuntimeError("OWNER_CLONE_GITHUB_OUTPUT_REQUIRED")
    rows=(
        f"manifest_path={manifest_path}",
        f"clone_id={clone_id}",
        "send_eligible="+("true" if send_eligible else "false"),
        "critical_scope="+("true" if critical_scope else "false"),
    )
    payload=(chr(10).join(rows)+chr(10)).encode("utf-8")
    # O_NOFOLLOW rejects link swaps after the initial is_symlink check.
    fd=os.open(output_path,os.O_WRONLY|os.O_APPEND|getattr(os,"O_NOFOLLOW",0))
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise RuntimeError("OWNER_CLONE_GITHUB_OUTPUT_NOT_REGULAR")
        with os.fdopen(fd,"ab") as output:
            fd=-1
            output.write(payload)
            output.flush()
    finally:
        if fd>=0:
            os.close(fd)


def reject_critical_scope_for_standard_delivery(manifest: dict) -> None:
    """Keep single-clone Telegram delivery separate from protected critical WAV.

    Called after structural validation and before any ledger or Telegram I/O.
    Even if workflow step routing is wrong, this worker cannot send the
    18-name protected audition through the legacy multi-message delivery.
    """
    if not isinstance(manifest,dict):
        raise ValueError("OWNER_CLONE_STANDARD_MANIFEST_INVALID")
    schema=manifest.get("schema_version")
    if schema=="OwnerVoiceSingleCloneControlReconciliation/v1":
        if manifest.get("control_only") is True and manifest.get("runtime_activation") is False:
            return
        raise ValueError("OWNER_CLONE_CONTROL_MODE_INVALID")
    if schema!="OwnerVoiceSingleCloneCandidate/v1":
        raise ValueError("OWNER_CLONE_STANDARD_MANIFEST_INVALID")
    if manifest.get("pronunciation_scope") not in (None,"LEGACY"):
        raise ValueError("CRITICAL_OWNER_AUDIO_PROTECTED_DELIVERY_REQUIRED")
