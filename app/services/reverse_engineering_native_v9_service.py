"""REA 6.0.0 / Ghidra 12.1.4: bounded native ELF function investigation.

The target is NEVER executed by this service. It only runs a pinned REA CLI
against a separately authorized owner-built Linux x86-64 executable.
Original code, pseudocode, symbols, strings and locations are not surfaced.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from app.services.reverse_engineering_media_service import ObservationError, _sha256

SCHEMA = "BRREANativeFunctionEvidence/v1"
EXACT_REA_VERSION = "6.0.0"
FUNCTION_NAME = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,63}$")
MAX_TARGET_BYTES = 2_000_000
MAX_ENVELOPE_CHARS = 2_000_000


def _call(args: list[str], *, timeout: int = 360,
          environment: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            args, capture_output=True, text=True, check=False, timeout=timeout,
            env=environment,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ObservationError("REA_NATIVE_PROVIDER_UNAVAILABLE_OR_TIMEOUT") from exc


def _elf_x86_64(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink() or not 64 <= path.stat().st_size <= MAX_TARGET_BYTES:
        raise ObservationError("REA_NATIVE_ELF_SOURCE_SIZE_OR_TYPE_INVALID")
    with path.open("rb") as source:
        header=source.read(64)
    if (header[0:4] != b"\x7fELF" or header[4] != 2
        or header[5] != 1 or int.from_bytes(header[18:20], "little") != 62
        or int.from_bytes(header[16:18], "little") not in (2, 3)):
        raise ObservationError("REA_NATIVE_REQUIRES_LINUX_X64_ELF")
    return {"elf_class":"ELF64","machine":"x86_64","source_size":path.stat().st_size}


def _json_result(raw: str, *, command: str) -> dict:
    if len(raw)>MAX_ENVELOPE_CHARS:
        raise ObservationError("REA_NATIVE_OUTPUT_TOO_LARGE")
    try:
        report=json.loads(raw)
    except ValueError as exc:
        raise ObservationError("REA_NATIVE_REPORT_INVALID_JSON") from exc
    if not isinstance(report,dict):
        raise ObservationError("REA_NATIVE_REPORT_INVALID_SHAPE")
    return report


def inspect_native_function(
    *, source: Path, function: str,
    rea_prefix: Path, ghidra_install: Path, java_home: Path,
) -> dict[str, Any]:
    """Analyze only: never start application, CLI MCP server, or external agent."""
    if not isinstance(function,str) or not FUNCTION_NAME.fullmatch(function):
        raise ObservationError("REA_NATIVE_FUNCTION_SELECTOR_INVALID")
    elf=_elf_x86_64(source)
    rea=rea_prefix/"node_modules"/".bin"/"rea"
    if not rea.is_file() or not rea_prefix.is_absolute():
        raise ObservationError("REA_NATIVE_PINNED_CLI_MISSING")
    if not ghidra_install.is_absolute() or not (ghidra_install/"support"/"analyzeHeadless").is_file():
        raise ObservationError("REA_NATIVE_GHIDRA_INSTALL_UNVERIFIED")
    if not java_home.is_absolute() or not (java_home/"bin"/"javac").is_file():
        raise ObservationError("REA_NATIVE_JDK_MISSING")
    # REA setup should not alter host registrations; explicit env bind only.
    env={
        **os.environ, "GHIDRA_INSTALL_DIR":str(ghidra_install),
        "JAVA_HOME":str(java_home), "REA_ANALYSIS_PROVIDER":"ghidra",
    }
    version=_call([str(rea),"--version"],timeout=15,environment=env)
    if version.returncode or version.stdout.strip()!=EXACT_REA_VERSION:
        raise ObservationError("REA_NATIVE_VERSION_PIN_INVALID")
    doctor=_call([str(rea),"doctor","--provider","ghidra","--json"],timeout=45,environment=env)
    doc=_json_result(doctor.stdout,command="doctor")
    if doctor.returncode!=0:
        raise ObservationError("REA_NATIVE_GHIDRA_DOCTOR_FAILED")
    observed=_call([
        str(rea),"function",str(source),function,"--provider","ghidra","--json",
    ],timeout=360,environment=env)
    if observed.returncode!=0:
        raise ObservationError("REA_NATIVE_FUNCTION_INVESTIGATION_FAILED")
    result=_json_result(observed.stdout,command="function")
    if isinstance(result.get("error"),(str,dict)):
        raise ObservationError("REA_NATIVE_REPORTED_ERROR")
    provider=result.get("provider")
    if not isinstance(provider,dict) or provider.get("id")!="ghidra":
        raise ObservationError("REA_NATIVE_PROVIDER_EVIDENCE_MISMATCH")
    if not isinstance(result.get("evidence_id"),str) or not result["evidence_id"]:
        raise ObservationError("REA_NATIVE_EVIDENCE_ID_MISSING")
    normalized=result.get("normalized_result")
    if not isinstance(normalized,dict):
        raise ObservationError("REA_NATIVE_NORMALIZED_RESULT_MISSING")
    # Never place target pseudocode, disassembly, paths or inferred descriptions
    # in the downstream report. A credible function result is not a proof of
    # a successful reconstruction or identical instructions.
    return {
        "schema_version":SCHEMA,
        "status":"NATIVE_GHIDRA_FUNCTION_EVIDENCE_CAPTURED",
        "source":{**elf,"sha256":_sha256(source),"rights":"owned"},
        "requested_function":function,
        "rea_version":EXACT_REA_VERSION,
        "ghidra_version":"12.1.4",
        "ghidra_doctor_exit":doctor.returncode,
        "ghidra_doctor_json_sha256":hashlib.sha256(doctor.stdout.encode()).hexdigest(),
        "function_evidence_sha256":hashlib.sha256(observed.stdout.encode()).hexdigest(),
        "function_evidence_id_sha256":hashlib.sha256(result["evidence_id"].encode()).hexdigest(),
        "normalized_top_level_fields":sorted(
            k for k in normalized if isinstance(k,str) and re.fullmatch(r"[a-zA-Z0-9_]{1,60}",k)
        )[:64],
        "native_function_executed":False,
        "pseudocode_forwarded_to_agents":False,
        "reverse_engineered_source_code_certified":False,
        "behavioral_equivalence_tested":False,
        "owner_voice_access":"FORBIDDEN",
        "canonical_learning_write":"NOT_ATTEMPTED",
        "publication_authorized":False,
        "limitations":"Native analysis and evidence metadata only; independent behavioral tests and expert reconstruction review still required",
    }
