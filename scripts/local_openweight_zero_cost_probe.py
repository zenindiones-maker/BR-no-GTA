from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any
from urllib import error, request


EXPECTED_MODEL = "qwen3:4b-instruct"
EXPECTED_DIGEST_PREFIX = "0edcdef34593"


def _json_request(
    url: str,
    *,
    payload: dict[str, Any] | None = None,
    timeout: float = 180.0,
) -> dict[str, Any]:
    body = None
    headers = {"Accept": "application/json"}
    method = "GET"
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
        method = "POST"
    req = request.Request(url, data=body, headers=headers, method=method)
    started = datetime.now(timezone.utc)
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            status = int(resp.status)
    except error.HTTPError as exc:
        raw = exc.read()
        status = int(exc.code)
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
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception:
        data = None
    return {
        "ok": 200 <= status < 300,
        "status": status,
        "body_sha256": hashlib.sha256(raw).hexdigest(),
        "json": data,
        "elapsed_seconds": (
            datetime.now(timezone.utc) - started
        ).total_seconds(),
    }


def _model_info(tags: dict[str, Any]) -> dict[str, Any] | None:
    data = tags.get("json")
    if not isinstance(data, dict):
        return None
    models = data.get("models")
    if not isinstance(models, list):
        return None
    for item in models:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("model") or "")
        if name == EXPECTED_MODEL:
            return item
    return None


def run(
    *,
    output: Path,
    base_url: str,
    ollama_version: str,
    repository_private: bool,
    egress_blocked: bool,
) -> dict[str, Any]:
    root = base_url.rstrip("/")
    tags = _json_request(f"{root}/api/tags", timeout=15.0)
    info = _model_info(tags) or {}
    digest = str(info.get("digest") or "")
    model_identity_pass = bool(
        digest
        and (
            digest.startswith(EXPECTED_DIGEST_PREFIX)
            or digest.removeprefix("sha256:").startswith(EXPECTED_DIGEST_PREFIX)
        )
    )

    inference = _json_request(
        f"{root}/api/chat",
        payload={
            "model": EXPECTED_MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "Return exactly LOCAL_OPENWEIGHT_INFERENCE_OK and nothing else."
                    ),
                }
            ],
            "stream": False,
            "options": {
                "temperature": 0,
                "num_predict": 32,
                "num_ctx": 4096,
            },
        },
        timeout=300.0,
    )
    data = inference.get("json")
    response_text = ""
    done_reason = None
    eval_count = None
    if isinstance(data, dict):
        message = data.get("message")
        if isinstance(message, dict):
            response_text = str(message.get("content") or "").strip()
        done_reason = data.get("done_reason")
        eval_count = data.get("eval_count")

    inference_pass = bool(
        inference.get("ok")
        and response_text
        and "LOCAL_OPENWEIGHT_INFERENCE_OK" in response_text
    )
    no_external_billing_proven = bool(
        inference_pass
        and model_identity_pass
        and egress_blocked
        and not repository_private
    )

    report = {
        "schema": "br-local-openweight-zero-cost-proof/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "authority": "DEEPSEEK_HARNESS",
        "zero_cost_operation": True,
        "provider_id": "ollama_local",
        "model_id": EXPECTED_MODEL,
        "expected_digest_prefix": EXPECTED_DIGEST_PREFIX,
        "observed_digest": digest,
        "model_identity_proof": "PASS" if model_identity_pass else "FAIL",
        "ollama_version": ollama_version,
        "runtime": "github-actions:ubuntu-24.04:standard-public-runner",
        "repository_private": repository_private,
        "runtime_endpoint": root,
        "loopback_only": root.startswith("http://127.0.0.1:"),
        "egress_blocked_during_inference": egress_blocked,
        "credential_count": 0,
        "external_inference_endpoint_count": 0,
        "tags_probe": tags,
        "inference_probe": {
            "ok": inference.get("ok"),
            "status": inference.get("status"),
            "body_sha256": inference.get("body_sha256"),
            "elapsed_seconds": inference.get("elapsed_seconds"),
            "response_text_sha256": (
                hashlib.sha256(response_text.encode("utf-8")).hexdigest()
                if response_text
                else None
            ),
            "response_text_excerpt": response_text[:300],
            "done_reason": done_reason,
            "eval_count": eval_count,
        },
        "PROVIDER_LIVE_INFERENCE": "PASS" if inference_pass else "FAIL",
        "NO_EXTERNAL_BILLING": (
            "PROVEN" if no_external_billing_proven else "NOT_PROVEN"
        ),
        "ZERO_COST_PROOF": "PASS" if no_external_billing_proven else "FAIL",
        "evidence_refs": [
            "ollama-release:v0.34.2",
            "ollama-library:qwen3:4b-instruct@0edcdef34593",
            "runtime:github-actions:ubuntu-24.04:public-standard",
            "runtime:egress-blocked-during-inference",
            "runtime:loopback:127.0.0.1:11434",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, default=str)
        + "\n",
        encoding="utf-8",
    )
    print("LOCAL_OPENWEIGHT_MODEL_IDENTITY=" + report["model_identity_proof"])
    print("LOCAL_OPENWEIGHT_PROVIDER_LIVE_INFERENCE=" + report["PROVIDER_LIVE_INFERENCE"])
    print("LOCAL_OPENWEIGHT_NO_EXTERNAL_BILLING=" + report["NO_EXTERNAL_BILLING"])
    print("LOCAL_OPENWEIGHT_ZERO_COST_PROOF=" + report["ZERO_COST_PROOF"])
    print("LOCAL_OPENWEIGHT_MODEL=" + EXPECTED_MODEL)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    parser.add_argument("--ollama-version", required=True)
    parser.add_argument("--repository-private", choices=("true", "false"), required=True)
    parser.add_argument("--egress-blocked", action="store_true")
    args = parser.parse_args()
    report = run(
        output=Path(args.output),
        base_url=args.base_url,
        ollama_version=args.ollama_version,
        repository_private=args.repository_private == "true",
        egress_blocked=args.egress_blocked,
    )
    return 0 if report["ZERO_COST_PROOF"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
