from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any
from urllib import error, request


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_body(raw: bytes, limit: int = 8000) -> str:
    text = raw.decode("utf-8", errors="replace")
    text = re.sub(
        r"(?i)(authorization|bearer|api[_-]?key|access[_-]?token|refresh[_-]?token)[^\s,;]*",
        "[REDACTED]",
        text,
    )
    return text[:limit]


def _headers(value) -> dict[str, str]:
    return {
        str(k).lower(): str(v)
        for k, v in value.items()
        if str(k).lower().startswith("x-rotator-")
        or str(k).lower() in {"content-type", "retry-after"}
    }


def _http_json(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    api_key: str = "tuxevil",
    timeout: float = 30.0,
) -> dict[str, Any]:
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = request.Request(url, data=body, headers=headers, method=method)
    started = datetime.now(timezone.utc)
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            status = int(resp.status)
            response_headers = _headers(resp.headers)
    except error.HTTPError as exc:
        raw = exc.read()
        status = int(exc.code)
        response_headers = _headers(exc.headers)
    except Exception as exc:
        return {
            "ok": False,
            "status": None,
            "error_type": type(exc).__name__,
            "error": str(exc)[:1000],
            "elapsed_seconds": (
                datetime.now(timezone.utc) - started
            ).total_seconds(),
        }
    safe = _safe_body(raw)
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception:
        data = None
    return {
        "ok": 200 <= status < 300,
        "status": status,
        "headers": response_headers,
        "body_sha256": hashlib.sha256(raw).hexdigest(),
        "body_excerpt": safe,
        "json": data,
        "elapsed_seconds": (
            datetime.now(timezone.utc) - started
        ).total_seconds(),
    }


def _model_ids(models_probe: dict[str, Any]) -> list[str]:
    data = models_probe.get("json")
    if not isinstance(data, dict):
        return []
    values = data.get("data")
    if not isinstance(values, list):
        return []
    result = []
    for item in values:
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            result.append(item["id"])
    return result[:200]


def _selected_probe_model(model_ids: list[str], configured: str) -> str:
    if configured in model_ids:
        return configured
    gemini = [item for item in model_ids if "gemini" in item.casefold()]
    return gemini[0] if gemini else configured


def _numeric_zero_cost_header(headers: dict[str, str]) -> tuple[bool, list[str]]:
    matched: list[str] = []
    for key, value in headers.items():
        low = key.casefold()
        if not any(term in low for term in ("cost", "usd", "billing", "spend")):
            continue
        try:
            numeric = float(re.sub(r"[^0-9eE+\-.]", "", value))
        except ValueError:
            continue
        if numeric == 0.0:
            matched.append(f"{key}={value}")
    return bool(matched), matched


def _quota_header_present(headers: dict[str, str]) -> tuple[bool, list[str]]:
    matched = [
        f"{key}={value}"
        for key, value in headers.items()
        if any(term in key.casefold() for term in ("quota", "remaining", "limit", "tier"))
    ]
    return bool(matched), matched


def run(
    *,
    output: Path,
    base_url: str,
    configured_model: str,
    package_version: str,
    package_integrity: str,
    package_git_head: str,
    server_started: bool,
) -> dict[str, Any]:
    root = base_url.rstrip("/")
    models = _http_json(f"{root}/v1/models")
    model_ids = _model_ids(models)
    probe_model = _selected_probe_model(model_ids, configured_model)
    inference = _http_json(
        f"{root}/v1/chat/completions",
        method="POST",
        payload={
            "model": probe_model,
            "messages": [
                {
                    "role": "user",
                    "content": "Return exactly TUXEVIL_LIVE_INFERENCE_OK and nothing else.",
                }
            ],
            "stream": False,
        },
        timeout=90.0,
    )
    response_text = ""
    data = inference.get("json")
    if isinstance(data, dict):
        try:
            response_text = str(data["choices"][0]["message"]["content"]).strip()
        except Exception:
            response_text = ""

    inference_pass = bool(inference.get("ok") and response_text)
    headers = dict(inference.get("headers") or {})
    cost_zero, cost_evidence = _numeric_zero_cost_header(headers)
    quota_present, quota_evidence = _quota_header_present(headers)

    # Fail closed: upstream marketing/free-tier claims are not billing proof.
    # A passing zero-cost proof requires a real inference plus runtime evidence
    # of zero request cost and a concrete quota/tier signal.
    no_external_billing_proven = bool(
        inference_pass and cost_zero and quota_present
    )
    zero_cost_proof = no_external_billing_proven

    report = {
        "schema": "br-tuxevil-zero-cost-proof/v1",
        "generated_at": _utcnow(),
        "authority": "DEEPSEEK_HARNESS",
        "zero_cost_operation": True,
        "provider_id": "tuxevil",
        "upstream_package": "tuxevil-rotator",
        "upstream_package_version": package_version,
        "upstream_package_integrity": package_integrity,
        "upstream_package_git_head": package_git_head,
        "runtime": "github-actions:ubuntu-24.04:node22",
        "runtime_endpoint": root,
        "loopback_only": root.startswith("http://127.0.0.1:"),
        "server_started": bool(server_started),
        "project_configured_model": configured_model,
        "discovered_model_ids": model_ids,
        "probe_model": probe_model,
        "models_probe": models,
        "inference_probe": {
            **inference,
            "response_text_sha256": (
                hashlib.sha256(response_text.encode("utf-8")).hexdigest()
                if response_text
                else None
            ),
            "response_text_excerpt": response_text[:500],
        },
        "PROVIDER_LIVE_INFERENCE": "PASS" if inference_pass else "FAIL",
        "NO_EXTERNAL_BILLING": (
            "PROVEN" if no_external_billing_proven else "NOT_PROVEN"
        ),
        "ZERO_COST_PROOF": "PASS" if zero_cost_proof else "FAIL",
        "TUXEVIL_ZERO_COST_PROOF": "PASS" if zero_cost_proof else "FAIL",
        "quota_evidence": quota_evidence,
        "zero_cost_header_evidence": cost_evidence,
        "conclusion": (
            "ELIGIBLE_ZERO_COST_PROVIDER"
            if zero_cost_proof
            else "NOT_ELIGIBLE_WITH_CURRENT_EVIDENCE"
        ),
        "evidence_refs": [
            "repo:.dsh/cordis.patch.yml:tuxevil-localhost-51200",
            "repo:app/services/tuxevil_ai_provider.py",
            "upstream:tuxevil/tuxevil-rotator",
            "runtime:github-actions-standard-public-runner",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, default=str)
        + "\n",
        encoding="utf-8",
    )
    print("TUXEVIL_RUNTIME_BOOTSTRAP=" + ("PASS" if server_started else "FAIL"))
    print("TUXEVIL_PROVIDER_LIVE_INFERENCE=" + report["PROVIDER_LIVE_INFERENCE"])
    print("TUXEVIL_NO_EXTERNAL_BILLING=" + report["NO_EXTERNAL_BILLING"])
    print("TUXEVIL_ZERO_COST_PROOF=" + report["TUXEVIL_ZERO_COST_PROOF"])
    print("TUXEVIL_PROBE_MODEL=" + probe_model)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:51200")
    parser.add_argument("--configured-model", default="gemini-3-flash")
    parser.add_argument("--package-version", default="")
    parser.add_argument("--package-integrity", default="")
    parser.add_argument("--package-git-head", default="")
    parser.add_argument("--server-started", action="store_true")
    args = parser.parse_args()
    report = run(
        output=Path(args.output),
        base_url=args.base_url,
        configured_model=args.configured_model,
        package_version=args.package_version,
        package_integrity=args.package_integrity,
        package_git_head=args.package_git_head,
        server_started=args.server_started,
    )
    return 0 if report["TUXEVIL_ZERO_COST_PROOF"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
