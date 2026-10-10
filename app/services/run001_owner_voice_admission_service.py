"""RUN-001 fail-closed preflight for non-legacy BR_OWNER_V1 voice lineage.

This is additional blocking validation. It NEVER approves voice identity:
the independent biometric/human-reviewed Harness approval still controls render.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

_HEX = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED = "BR_OWNER_V1"


class OwnerVoiceAdmissionBlocked(RuntimeError):
    pass


def require_owner_voice_admission(product: Mapping[str, Any]) -> dict[str, str]:
    if not isinstance(product, Mapping):
        raise OwnerVoiceAdmissionBlocked("RUN001_PRODUCT_OBJECT_REQUIRED")
    narration = product.get("narration")
    if not isinstance(narration, Mapping):
        raise OwnerVoiceAdmissionBlocked("RUN001_NARRATION_BINDING_REQUIRED")
    # The archived A product in V24 explicitly requests Thalita / Voice B.
    # This old narrator and every provider preset are FORBIDDEN permanently.
    voice = str(narration.get("voice") or "").strip()
    legacy = (
        str(narration.get("official_profile_id") or "")
        + " " + str(narration.get("human_quality_baseline") or "")
        + " " + voice
    ).lower()
    if any(x in legacy for x in ("thalita", "voice b", "voice-b", "neural")):
        raise OwnerVoiceAdmissionBlocked("RUN001_LEGACY_VOICE_B_FORBIDDEN")
    if voice != _ALLOWED or narration.get("voice_identity_id") != _ALLOWED:
        raise OwnerVoiceAdmissionBlocked("RUN001_ONLY_HUMAN_BR_OWNER_V1_ALLOWED")
    if narration.get("generic_voice_fallback") is not False:
        raise OwnerVoiceAdmissionBlocked("RUN001_GENERIC_VOICE_FALLBACK_FORBIDDEN")
    if narration.get("runtime_activation") != "HUMAN_APPROVED":
        raise OwnerVoiceAdmissionBlocked("RUN001_OWNER_HUMAN_APPROVAL_REQUIRED")
    if narration.get("identity_gate") != "PASS":
        raise OwnerVoiceAdmissionBlocked("RUN001_SPEAKER_IDENTITY_GATE_REQUIRED")
    candidate = narration.get("approved_clone_audio_sha256")
    if not isinstance(candidate, str) or not _HEX.fullmatch(candidate):
        raise OwnerVoiceAdmissionBlocked("RUN001_APPROVED_CLONE_DIGEST_REQUIRED")
    receipt = narration.get("independent_approval_ledger_ref")
    if not isinstance(receipt, str) or not receipt.startswith(
        "BR-no-GTA-audition-ledger:owner-voice-audition-state:"
    ):
        raise OwnerVoiceAdmissionBlocked("RUN001_INDEPENDENT_OWNER_APPROVAL_RECEIPT_REQUIRED")
    revision = receipt.rsplit(":", 1)[-1]
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise OwnerVoiceAdmissionBlocked("RUN001_LEDGER_COMMIT_SHA_INVALID")
    # The upstream Harness MUST separately verify the remote owner approval,
    # actual clone asset SHA and permission. A string is NOT proof of approval.
    return {"voice_identity_id": _ALLOWED, "clone_sha256": candidate,
            "unverified_receipt_ref": receipt}
