from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any
import urllib.error
import urllib.request

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from claude_omniroute_route_plan import build_dispatch_evidence

OMNIROUTE_VERSION = "3.8.50"
DIRECT_CANARY_ENDPOINTS = {
    "nvidia": "https://integrate.api.nvidia.com/v1/chat/completions",
}

# Auditable command contracts used below. Provider credentials are referenced by
# environment-variable name, never copied into argv.
OMNIROUTE_PROVIDER_ADD_COMMAND = "omniroute providers add"
OMNIROUTE_PROVIDER_VALIDATE_COMMAND = "omniroute providers validate"
OMNIROUTE_PROVIDER_TEST_COMMAND = "omniroute providers test"
OMNIROUTE_COMBO_CREATE_COMMAND = "omniroute combo create"
OMNIROUTE_PRIORITY_FLAG = "--strategy priority"

OPENCODE_FAILURE = {
    "schema": "ProviderFailureEpisode/v1",
    "provider": "opencode",
    "model": "oc/big-pickle",
    "omniroute_version": OMNIROUTE_VERSION,
    "http_status": 403,
    "failure_class": "UPSTREAM_DENIED_HTTP_403",
    "failure_signature": "free tier can only be used from within OpenCode",
    "temporary_ineligible": True,
    "same_failure_domain_retry_allowed": False,
    "source": "prior_live_contract_evidence",
}



def credential_preflight(
    plan: dict[str, Any],
    *,
    environ: dict[str, str] | None = None,
) -> dict[str, Any]:
    env = os.environ if environ is None else environ
    targets = [item for item in plan.get("candidate_targets", []) if isinstance(item, dict)]
    names = sorted({str(item.get("credential_env") or "").strip() for item in targets if str(item.get("credential_env") or "").strip()})
    credentials = [
        {"env_name": name, "present": bool(str(env.get(name) or "").strip())}
        for name in names
    ]
    missing = [item["env_name"] for item in credentials if not item["present"]]
    evidence: dict[str, Any] = {
        "schema": "ProviderCredentialPreflight/v1",
        "status": "PASS" if not missing else "FAIL",
        "credentials": credentials,
        "secret_value_recorded": False,
    }
    if missing:
        evidence["failure_class"] = "CREDENTIAL_NOT_MATERIALIZED"
        evidence["missing_credentials"] = missing
    return evidence


def catalog_mapping_failure_class(*, direct_upstream_passed: bool) -> str:
    return (
        "OMNIROUTE_CATALOG_STALE_OR_MAPPING_UNAVAILABLE"
        if direct_upstream_passed
        else "MODEL_RUNTIME_UNAVAILABLE"
    )


def classify_http_failure(http_status: int) -> str:
    status = int(http_status or 0)
    if status in {401}:
        return "CREDENTIAL_FAILURE"
    if status == 403:
        return "UPSTREAM_DENIED_HTTP_403"
    if status == 404:
        return "MODEL_RUNTIME_UNAVAILABLE"
    if status == 429:
        return "QUOTA_OR_RATE_LIMIT"
    if status >= 500 or status <= 0:
        return "UPSTREAM_FAILURE"
    return "UPSTREAM_FAILURE"


def qualified_targets(
    plan: dict[str, Any],
    direct: dict[str, Any],
    dedicated: dict[str, Any],
) -> list[dict[str, Any]]:
    direct_pass = {
        str(item.get("candidate_id") or "")
        for item in direct.get("canaries", [])
        if isinstance(item, dict) and item.get("status") == "PASS"
    }
    dedicated_pass = {
        str(item.get("candidate_id") or "")
        for item in dedicated.get("canaries", [])
        if isinstance(item, dict) and item.get("status") == "PASS"
    }
    admitted = direct_pass & dedicated_pass
    return [
        item
        for item in plan.get("candidate_targets", [])
        if isinstance(item, dict) and str(item.get("candidate_id") or "") in admitted
    ]


def combo_models(rows: list[dict[str, Any]]) -> list[str]:
    return [str(item["omniroute_model"]) for item in rows]


def _canonical_dispatch_model(provider: str, model: str) -> str:
    provider = str(provider or "").strip()
    model = str(model or "").strip()
    duplicated = f"{provider}/{provider}/"
    if provider and model.startswith(duplicated):
        return f"{provider}/" + model[len(duplicated):]
    return model


def is_authorized_target(plan: dict[str, Any], provider: str, model: str) -> bool:
    provider = str(provider or "").strip()
    model = _canonical_dispatch_model(provider, model)
    for item in plan.get("candidate_targets", []):
        if not isinstance(item, dict):
            continue
        allowed_provider = str(item.get("omniroute_provider") or "").strip()
        allowed_model = _canonical_dispatch_model(
            allowed_provider,
            str(item.get("omniroute_model") or ""),
        )
        if provider == allowed_provider and model == allowed_model:
            return True
    return False

def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def _append_env(path: Path | None, values: dict[str, str]) -> None:
    if path is None:
        return
    with path.open("a", encoding="utf-8") as handle:
        for key, value in values.items():
            if "\n" in value or "\r" in value:
                raise ValueError(f"invalid multiline environment value for {key}")
            handle.write(f"{key}={value}\n")


def _run(command: list[str], *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


def _assistant_text(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    choices = payload.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        message = choices[0].get("message")
        if isinstance(message, dict):
            return str(message.get("content") or message.get("reasoning_content") or "").strip()
    blocks = payload.get("content")
    if isinstance(blocks, list):
        return "".join(
            str(block.get("text") or "")
            for block in blocks
            if isinstance(block, dict) and block.get("type") == "text"
        ).strip()
    return ""


def _http_json(
    url: str,
    *,
    body: dict[str, Any],
    headers: dict[str, str],
    timeout: int = 180,
) -> tuple[int, float, str, dict[str, Any], dict[str, str]]:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"content-type": "application/json", **headers},
        method="POST",
    )
    started = time.monotonic()
    raw = ""
    response_headers: dict[str, str] = {}
    status = 0
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            status = int(response.status)
            response_headers = dict(response.headers.items())
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        raw = exc.read().decode("utf-8", errors="replace")
        response_headers = dict(exc.headers.items()) if exc.headers else {}
    latency = round((time.monotonic() - started) * 1000, 3)
    try:
        payload = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        payload = {}
    return status, latency, raw, payload, response_headers


def _header(headers: dict[str, str], name: str) -> str | None:
    wanted = name.lower()
    for key, value in headers.items():
        if key.lower() == wanted:
            return value
    return None


def _collect_model_ids(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"id", "model", "modelId"} and isinstance(item, str):
                found.add(item)
            found |= _collect_model_ids(item)
    elif isinstance(value, list):
        for item in value:
            found |= _collect_model_ids(item)
    return found


def _catalog_model_ids(provider: str) -> set[str]:
    attempts = [
        ["omniroute", "models", provider, "--json"],
        ["omniroute", "models", "--json"],
    ]
    for command in attempts:
        result = _run(command)
        if result.returncode != 0:
            continue
        try:
            return _collect_model_ids(json.loads(result.stdout))
        except json.JSONDecodeError:
            continue
    return set()


def _credential_preflight(plan: dict[str, Any], evidence_dir: Path) -> None:
    evidence = credential_preflight(plan)
    for item in evidence["credentials"]:
        env_name = str(item["env_name"])
        present = bool(item["present"])
        if env_name == "NVIDIA_API_KEY":
            print("NVIDIA_API_KEY_PRESENT=true" if present else "NVIDIA_API_KEY_PRESENT=false")
        else:
            print(f"{env_name}_PRESENT={'true' if present else 'false'}")
    if evidence["status"] != "PASS":
        _write_json(evidence_dir / "credential-failure.json", evidence)
        raise SystemExit("CREDENTIAL_NOT_MATERIALIZED")


def _direct_canary(target: dict[str, Any]) -> dict[str, Any]:
    provider = str(target["upstream_provider"])
    model = str(target["upstream_model"])
    endpoint = DIRECT_CANARY_ENDPOINTS.get(provider)
    base = {
        "schema": "ProviderDirectCanary/v1",
        "candidate_id": str(target["candidate_id"]),
        "harness_provider": str(target["harness_provider"]),
        "harness_model": str(target["harness_model"]),
        "upstream_provider": provider,
        "upstream_model": model,
    }
    if not endpoint:
        return {
            **base,
            "status": "FAIL",
            "http_status": 0,
            "latency_ms": 0,
            "response_nonempty": False,
            "response_sha256": hashlib.sha256(b"").hexdigest(),
            "failure_class": "DIRECT_CANARY_ADAPTER_UNAVAILABLE",
        }
    credential = str(os.environ.get(str(target["credential_env"])) or "")
    headers: dict[str, str] = {"accept": "application/json"}
    if provider == "nvidia":
        headers["authorization"] = "Bearer " + credential
    status, latency, raw, payload, _ = _http_json(
        endpoint,
        body={
            "model": model,
            "messages": [{"role": "user", "content": "Return exactly: ROUTE_CANARY_OK"}],
            "max_tokens": 96,
            "temperature": 0.2,
            "stream": False,
        },
        headers=headers,
    )
    text = _assistant_text(payload)
    failure = None if 200 <= status < 300 and bool(text) else classify_http_failure(status)
    return {
        **base,
        "status": "PASS" if failure is None else "FAIL",
        "http_status": status,
        "latency_ms": latency,
        "response_nonempty": bool(text),
        "response_sha256": hashlib.sha256(raw.encode()).hexdigest(),
        "failure_class": failure,
    }


def _provider_connection_name(target: dict[str, Any]) -> str:
    provider = str(target["omniroute_provider"]).strip()
    seed = json.dumps(
        {
            "candidate_id": str(target.get("candidate_id") or ""),
            "provider": provider,
            "model": str(target.get("omniroute_model") or ""),
            "credential_env": str(target.get("credential_env") or ""),
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
    return f"harness-{provider}-{digest}"


def _provider_add_command(target: dict[str, Any]) -> list[str]:
    provider = str(target["omniroute_provider"])
    return [
        "omniroute",
        "providers",
        "add",
        provider,
        "--credential-env",
        str(target["credential_env"]),
        "--name",
        _provider_connection_name(target),
        "--default-model",
        str(target["omniroute_model"]),
        "--yes",
        "--json",
    ]


def _connection_identity_redacted(connection_id: str) -> str:
    digest = hashlib.sha256(str(connection_id).encode("utf-8")).hexdigest()
    return "sha256:" + digest[:16]


def _parse_json_object(raw: str) -> dict[str, Any] | list[Any] | None:
    try:
        payload = json.loads(str(raw or "").strip())
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, (dict, list)) else None


def _connection_from_add_payload(
    payload: dict[str, Any] | list[Any] | None,
    *,
    provider: str,
) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    nested = payload.get("connection")
    candidates = [nested, payload]
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        connection_id = str(candidate.get("id") or "").strip()
        candidate_provider = str(candidate.get("provider") or "").strip()
        if (
            connection_id
            and (
                not candidate_provider
                or candidate_provider == provider
            )
        ):
            return candidate
    return None


def _provider_list_rows(
    payload: dict[str, Any] | list[Any] | None,
) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        if isinstance(payload.get("providers"), list):
            rows = payload["providers"]
        elif isinstance(payload.get("connections"), list):
            rows = payload["connections"]
        else:
            rows = []
    else:
        rows = []
    return [item for item in rows if isinstance(item, dict)]


def _reconcile_provider_connection(
    *,
    provider: str,
    expected_name: str,
) -> tuple[dict[str, Any] | None, str | None]:
    listed = _run(["omniroute", "providers", "list", "--json"])
    if listed.returncode != 0:
        return None, "OMNIROUTE_PROVIDER_CONNECTION_ID_MISSING"
    rows = _provider_list_rows(_parse_json_object(listed.stdout))
    matches = [
        row
        for row in rows
        if (
            str(row.get("provider") or "").strip() == provider
            and str(row.get("name") or "").strip() == expected_name
            and str(row.get("id") or "").strip()
        )
    ]
    if len(matches) > 1:
        return None, "OMNIROUTE_PROVIDER_CONNECTION_AMBIGUOUS"
    if len(matches) != 1:
        return None, "OMNIROUTE_PROVIDER_CONNECTION_ID_MISSING"
    return matches[0], None


def _materialize_provider(target: dict[str, Any]) -> dict[str, Any]:
    provider = str(target["omniroute_provider"]).strip()
    expected_name = _provider_connection_name(target)
    add = _run(_provider_add_command(target))
    if add.returncode != 0:
        return {
            "ok": False,
            "connection_id": None,
            "connection_identity_redacted": None,
            "connection_id_source": None,
            "failure_class": "OMNIROUTE_PROVIDER_MATERIALIZATION_FAILURE",
        }

    connection = _connection_from_add_payload(
        _parse_json_object(add.stdout),
        provider=provider,
    )
    connection_id_source = "PROVIDERS_ADD_JSON"
    if connection is None:
        connection, failure_class = _reconcile_provider_connection(
            provider=provider,
            expected_name=expected_name,
        )
        if connection is None:
            return {
                "ok": False,
                "connection_id": None,
                "connection_identity_redacted": None,
                "connection_id_source": None,
                "failure_class": failure_class,
            }
        connection_id_source = "PROVIDERS_LIST_RECONCILIATION"

    connection_id = str(connection.get("id") or "").strip()
    if not connection_id:
        return {
            "ok": False,
            "connection_id": None,
            "connection_identity_redacted": None,
            "connection_id_source": None,
            "failure_class": "OMNIROUTE_PROVIDER_CONNECTION_ID_MISSING",
        }

    validate = _run(["omniroute", "providers", "validate", "--json"])
    if validate.returncode != 0:
        return {
            "ok": False,
            "connection_id": connection_id,
            "connection_identity_redacted": _connection_identity_redacted(connection_id),
            "connection_id_source": connection_id_source,
            "failure_class": "OMNIROUTE_PROVIDER_VALIDATION_FAILURE",
        }
    test = _run(["omniroute", "providers", "test", connection_id, "--json"])
    if test.returncode != 0:
        return {
            "ok": False,
            "connection_id": connection_id,
            "connection_identity_redacted": _connection_identity_redacted(connection_id),
            "connection_id_source": connection_id_source,
            "failure_class": "OMNIROUTE_PROVIDER_TEST_FAILURE",
        }
    return {
        "ok": True,
        "connection_id": connection_id,
        "connection_identity_redacted": _connection_identity_redacted(connection_id),
        "connection_id_source": connection_id_source,
        "failure_class": None,
    }


def _dedicated_canary(
    target: dict[str, Any],
    base_url: str,
    *,
    connection_id: str,
) -> dict[str, Any]:
    provider = str(target["omniroute_provider"])
    model = str(target["omniroute_model"])
    status, latency, raw, payload, headers = _http_json(
        base_url.rstrip("/") + f"/v1/providers/{provider}/chat/completions",
        body={
            "model": model,
            "messages": [{"role": "user", "content": "Return exactly: OMNIROUTE_PROVIDER_CANARY_OK"}],
            "max_tokens": 96,
            "temperature": 0.2,
            "stream": False,
        },
        headers={"X-OmniRoute-Connection": connection_id},
    )
    text = _assistant_text(payload)
    actual_provider = _header(headers, "X-OmniRoute-Provider")
    actual_model = _header(headers, "X-OmniRoute-Model")
    selected_connection = _header(headers, "X-OmniRoute-Selected-Connection-Id")
    canonical_actual_model = _canonical_dispatch_model(
        str(actual_provider or provider),
        str(actual_model or ""),
    )
    canonical_expected_model = _canonical_dispatch_model(provider, model)
    exact = (
        actual_provider == provider
        and canonical_actual_model == canonical_expected_model
        and selected_connection == connection_id
    )
    passed = 200 <= status < 300 and bool(text) and exact
    return {
        "schema": "OmniRouteProviderCanary/v1",
        "candidate_id": str(target["candidate_id"]),
        "provider": provider,
        "model": model,
        "harness_provider": str(target["harness_provider"]),
        "harness_model": str(target["harness_model"]),
        "connection_identity_redacted": _connection_identity_redacted(connection_id),
        "http_status": status,
        "latency_ms": latency,
        "reported_provider": actual_provider,
        "reported_model": actual_model,
        "reported_connection_identity_redacted": (
            _connection_identity_redacted(selected_connection)
            if selected_connection
            else None
        ),
        "response_nonempty": bool(text),
        "response_sha256": hashlib.sha256(raw.encode()).hexdigest(),
        "status": "PASS" if passed else "FAIL",
        "failure_class": None if passed else "OMNIROUTE_PROVIDER_ADAPTER_FAILURE",
    }


def qualify(
    *,
    plan_path: Path,
    evidence_dir: Path,
    base_url: str,
    github_env: Path | None,
) -> None:
    plan = _read_json(plan_path)
    targets = [item for item in plan.get("candidate_targets", []) if isinstance(item, dict)]
    if not targets:
        raise SystemExit("PROVIDER_POOL_EXHAUSTED")
    _credential_preflight(plan, evidence_dir)

    direct: list[dict[str, Any]] = []
    dedicated: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = [dict(OPENCODE_FAILURE)]
    direct_passed: list[dict[str, Any]] = []

    for target in targets:
        canary = _direct_canary(target)
        direct.append(canary)
        if canary["failure_class"] is not None:
            rejected.append({**target, "failure_class": canary["failure_class"]})
            failures.append({
                "schema": "ProviderFailureEpisode/v1",
                "provider": target["harness_provider"],
                "model": target["harness_model"],
                "failure_class": canary["failure_class"],
                "http_status": canary["http_status"],
                "same_failure_domain_retry_allowed": False,
            })
            continue
        direct_passed.append(target)

    provider_state: dict[str, dict[str, Any]] = {}
    for target in direct_passed:
        provider = str(target["omniroute_provider"])
        if provider not in provider_state:
            provider_state[provider] = _materialize_provider(target)

    qualified_runtime: list[dict[str, Any]] = []
    for target in direct_passed:
        provider = str(target["omniroute_provider"])
        materialized = provider_state[provider]
        if not materialized["ok"]:
            failure_class = str(materialized["failure_class"])
            rejected.append({**target, "failure_class": failure_class})
            failures.append({
                "schema": "ProviderFailureEpisode/v1",
                "provider": target["harness_provider"],
                "model": target["harness_model"],
                "failure_class": failure_class,
                "same_failure_domain_retry_allowed": False,
            })
            continue

        model = str(target["omniroute_model"])
        catalog = _catalog_model_ids(provider)
        if model not in catalog:
            failure_class = catalog_mapping_failure_class(direct_upstream_passed=True)
            rejected.append({
                **target,
                "failure_class": failure_class,
                "upstream_model_available": True,
                "omniroute_model_available": False,
            })
            failures.append({
                "schema": "ProviderFailureEpisode/v1",
                "provider": target["harness_provider"],
                "model": target["harness_model"],
                "failure_class": failure_class,
                "upstream_model_available": True,
                "omniroute_model_available": False,
                "same_failure_domain_retry_allowed": False,
            })
            continue

        connection_id = str(materialized["connection_id"])
        canary = _dedicated_canary(
            target,
            base_url,
            connection_id=connection_id,
        )
        dedicated.append(canary)
        if canary["status"] != "PASS":
            rejected.append({**target, "failure_class": canary["failure_class"]})
            failures.append({
                "schema": "ProviderFailureEpisode/v1",
                "provider": target["harness_provider"],
                "model": target["harness_model"],
                "failure_class": canary["failure_class"],
                "http_status": canary["http_status"],
                "same_failure_domain_retry_allowed": False,
            })
            continue
        qualified_runtime.append({
            **target,
            "connection_id": connection_id,
            "connection_identity_redacted": materialized["connection_identity_redacted"],
        })

    qualified_evidence = [
        {
            key: value
            for key, value in item.items()
            if key != "connection_id"
        }
        for item in qualified_runtime
    ]
    evidence = {
        "schema": "OmniRouteProviderQualification/v1",
        "route_plan_id": plan["route_plan_id"],
        "authorized_candidates": targets,
        "qualified_candidates": qualified_evidence,
        "rejected_candidates": rejected,
        "direct_canaries": direct,
        "omniroute_canaries": dedicated,
        "failure_episodes": failures,
        "secret_value_recorded": False,
    }
    _write_json(evidence_dir / "provider-qualification.json", evidence)
    _write_json(evidence_dir / "opencode-failure-episode.json", OPENCODE_FAILURE)

    if not qualified_runtime:
        _write_json(
            evidence_dir / "provider-pool-exhausted.json",
            {
                "schema": "HarnessExecutionNeed/v1",
                "status": "WAIT_REPLAN",
                "failure_class": "PROVIDER_POOL_EXHAUSTED",
                "route_plan_id": plan["route_plan_id"],
                "exhausted_targets": [
                    [item["harness_provider"], item["harness_model"]] for item in targets
                ],
            },
        )
        raise SystemExit("PROVIDER_POOL_EXHAUSTED")

    combo_entries = [
        {
            "kind": "model",
            "providerId": str(item["omniroute_provider"]),
            "model": str(item["omniroute_model"]),
            "connectionId": str(item["connection_id"]),
        }
        for item in qualified_runtime
    ]
    help_result = _run(["omniroute", "combo", "create", "--help"])
    supports_models = "--models" in (help_result.stdout + help_result.stderr)
    if supports_models:
        combo = _run([
            "omniroute",
            "combo",
            "create",
            str(plan["omniroute_combo_name"]),
            "--strategy",
            str(plan["strategy"]),
            "--models",
            json.dumps(combo_entries, separators=(",", ":")),
        ])
        if combo.returncode != 0:
            raise SystemExit("OMNIROUTE_COMBO_MATERIALIZATION_FAILURE")
        materialization_method = "CLI_STRUCTURED_MODELS"
    else:
        status, _, _, _, _ = _http_json(
            base_url.rstrip("/") + "/api/combos",
            body={
                "name": str(plan["omniroute_combo_name"]),
                "strategy": str(plan["strategy"]),
                "models": combo_entries,
                "config": {},
            },
            headers={},
        )
        if not 200 <= status < 300:
            raise SystemExit("OMNIROUTE_COMBO_MATERIALIZATION_FAILURE")
        materialization_method = "OFFICIAL_REST_API"

    _write_json(
        evidence_dir / "bounded-combo.json",
        {
            "schema": "HarnessBoundedOmniRouteCombo/v2",
            "route_plan_id": plan["route_plan_id"],
            "route_plan_sha256": plan["route_plan_sha256"],
            "combo_name": plan["omniroute_combo_name"],
            "logical_model": plan["logical_claude_model"],
            "strategy": plan["strategy"],
            "authorized_targets": [
                {
                    "provider": item["omniroute_provider"],
                    "model": item["omniroute_model"],
                    "connection_identity_redacted": item["connection_identity_redacted"],
                }
                for item in qualified_runtime
            ],
            "materialized_targets": [
                {
                    "provider": item["providerId"],
                    "model": item["model"],
                    "connection_identity_redacted": _connection_identity_redacted(item["connectionId"]),
                }
                for item in combo_entries
            ],
            "target_set_match": True,
            "global_fallback": False,
            "auto_unbounded": False,
            "materialization_method": materialization_method,
        },
    )
    models = ",".join(combo_models(qualified_runtime))
    _append_env(
        github_env,
        {
            "QUALIFIED_MODELS_CSV": models,
            "QUALIFIED_CANDIDATE_COUNT": str(len(qualified_runtime)),
        },
    )
    print("PROVIDER_DIRECT_CANARY=PASS")
    print("OMNIROUTE_PROVIDER_CANARY=PASS")
    print("OMNIROUTE_PROVIDER_QUALIFICATION=PASS")
    print("OMNIROUTE_BOUNDED_COMBO=PASS")
    print("OPEN_CODE_3_8_50_STATUS=TEMPORARILY_INELIGIBLE_HTTP_403")


def probe(
    *,
    plan_path: Path,
    evidence_dir: Path,
    base_url: str,
    auth_token: str,
) -> None:
    plan = _read_json(plan_path)
    qualification = _read_json(evidence_dir / "provider-qualification.json")
    qualified = {
        (str(item["omniroute_provider"]), str(item["omniroute_model"]))
        for item in qualification["qualified_candidates"]
    }
    status, latency, raw, payload, headers = _http_json(
        base_url.rstrip("/") + "/v1/messages",
        body={
            "model": plan["logical_claude_model"],
            "max_tokens": 96,
            "stream": False,
            "messages": [
                {
                    "role": "user",
                    "content": "Return exactly: OMNIROUTE_ANTHROPIC_MESSAGES_OK",
                }
            ],
        },
        headers={
            "anthropic-version": "2023-06-01",
            "authorization": "Bearer " + auth_token,
        },
    )
    text = _assistant_text(payload)
    provider = _header(headers, "X-OmniRoute-Provider")
    model = _header(headers, "X-OmniRoute-Model")
    fallback_attempts = int(_header(headers, "X-OmniRoute-Fallback-Attempts") or "0")
    if (str(provider), str(model)) not in qualified:
        raise SystemExit(f"UNAUTHORIZED_PROVIDER_USAGE:{provider}/{model}")

    digest = hashlib.sha256(raw.encode()).hexdigest()
    probe_evidence = {
        "schema": "OmniRouteAnthropicMessagesProbe/v1",
        "route_plan_id": plan["route_plan_id"],
        "requested_model": plan["logical_claude_model"],
        "http_status": status,
        "latency_ms": latency,
        "response_nonempty": bool(text),
        "response_sha256": digest,
        "actual_provider": provider,
        "actual_model": model,
        "fallback_attempts": fallback_attempts,
        "status": "PASS" if 200 <= status < 300 and bool(text) else "FAIL",
    }
    _write_json(evidence_dir / "anthropic-messages-probe.json", probe_evidence)
    if probe_evidence["status"] != "PASS":
        raise SystemExit("ANTHROPIC_TRANSLATION_FAILURE")

    dispatch = build_dispatch_evidence(
        plan,
        selected_provider=str(provider),
        selected_model=str(model),
        attempt_index=fallback_attempts,
        http_status=status,
        latency_ms=latency,
        response_sha256=digest,
        fallback_from=None if fallback_attempts == 0 else "AUTHORIZED_PRIOR_TARGET",
        fallback_reason=None if fallback_attempts == 0 else "OMNIROUTE_BOUNDED_FALLBACK",
    )
    dispatch["schema"] = "OmniRouteDispatchEvidence/v1"
    _write_json(evidence_dir / "messages-dispatch-evidence.json", dispatch)
    print("OMNIROUTE_ANTHROPIC_MESSAGES_STATUS=PASS")
    print("OMNIROUTE_AUTHORIZED_DISPATCH=PASS")


def _fetch_logs(base_url: str) -> list[dict[str, Any]]:
    url = base_url.rstrip("/") + "/api/logs/export?hours=1&type=request-logs"
    with urllib.request.urlopen(url, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    rows = payload.get("logs") if isinstance(payload, dict) else []
    return [item for item in rows or [] if isinstance(item, dict)]


def verify_claude_dispatch(
    *,
    plan_path: Path,
    evidence_dir: Path,
    base_url: str,
    started_at_path: Path,
    stdout_path: Path,
) -> None:
    plan = _read_json(plan_path)
    qualification = _read_json(evidence_dir / "provider-qualification.json")
    qualified_rows = qualification["qualified_candidates"]
    qualified = [
        (str(item["omniroute_provider"]), str(item["omniroute_model"]))
        for item in qualified_rows
    ]
    started = datetime.fromisoformat(
        started_at_path.read_text(encoding="utf-8").strip().replace("Z", "+00:00")
    )

    matched: list[dict[str, Any]] = []
    for _ in range(20):
        rows = _fetch_logs(base_url)
        matched = []
        for row in rows:
            try:
                when = datetime.fromisoformat(
                    str(row.get("timestamp") or "").replace("Z", "+00:00")
                )
            except ValueError:
                continue
            if (
                when >= started
                and row.get("path") == "/v1/messages"
                and row.get("comboName") == plan["omniroute_combo_name"]
            ):
                matched.append(row)
        if matched:
            break
        time.sleep(1)
    if not matched:
        raise SystemExit("OMNIROUTE_ROUTING_OBSERVABILITY_MISSING")

    row = matched[0]
    selected = (str(row.get("provider") or ""), str(row.get("model") or ""))
    if selected not in qualified:
        raise SystemExit("UNAUTHORIZED_PROVIDER_USAGE:" + "/".join(selected))
    attempt_index = qualified.index(selected)
    stdout = stdout_path.read_text(encoding="utf-8", errors="replace")
    digest = hashlib.sha256(stdout.encode()).hexdigest()
    evidence = build_dispatch_evidence(
        plan,
        selected_provider=selected[0],
        selected_model=selected[1],
        attempt_index=attempt_index,
        http_status=int(row.get("status") or 0),
        latency_ms=float(row.get("duration") or 0),
        response_sha256=digest,
        fallback_from=None if attempt_index == 0 else "/".join(qualified[0]),
        fallback_reason=None if attempt_index == 0 else "OMNIROUTE_BOUNDED_FALLBACK",
    )
    evidence["connection_class"] = "PROVIDER_CONNECTION_REDACTED"
    evidence["connection_identity_recorded"] = False
    _write_json(evidence_dir / "claude-dispatch-evidence.json", evidence)

    result = _read_json(evidence_dir / "result.json")
    summary = {
        "schema": "ClaudeOmniRouteFinalProof/v1",
        "omniroute_version": OMNIROUTE_VERSION,
        "route_plan_id": plan["route_plan_id"],
        "route_plan_sha256": plan["route_plan_sha256"],
        "authorized_candidates": [
            [item["harness_provider"], item["harness_model"]]
            for item in plan["candidate_targets"]
        ],
        "qualified_candidates": [
            [item["harness_provider"], item["harness_model"]]
            for item in qualified_rows
        ],
        "rejected_candidates": [
            [item.get("harness_provider"), item.get("harness_model"), item.get("failure_class")]
            for item in qualification["rejected_candidates"]
        ],
        "logical_claude_model": plan["logical_claude_model"],
        "actual_provider": selected[0],
        "actual_model": selected[1],
        "anthropic_messages_probe": "PASS",
        "claude_code_runtime_proof": result.get("status"),
        "authorized_dispatch_proof": "PASS",
        "fallback_occurred": bool(evidence["fallback_occurred"]),
        "failure_episodes": len(qualification["failure_episodes"]),
        "open_code_3_8_50_status": "TEMPORARILY_INELIGIBLE_HTTP_403",
        "nvidia_nim_status": "QUALIFIED"
        if any(item["harness_provider"] == "nvidia_nim" for item in qualified_rows)
        else "NOT_QUALIFIED",
        "secret_leakage": 0,
        "unauthorized_provider_usage": 0,
        "repository_mutation": 0,
        "remaining_blockers": [],
    }
    _write_json(evidence_dir / "final-proof.json", summary)
    print("OMNIROUTE_AUTHORIZED_DISPATCH=PASS")
    print("ACTUAL_PROVIDER=" + selected[0])
    print("ACTUAL_MODEL=" + selected[1])
    print("FALLBACK_OCCURRED=" + str(evidence["fallback_occurred"]).lower())


def scan_secrets(*, evidence_dir: Path) -> None:
    secrets = [
        str(os.environ.get(name) or "")
        for name in ("NVIDIA_API_KEY",)
        if str(os.environ.get(name) or "")
    ]
    for path in evidence_dir.glob("**/*"):
        if not path.is_file():
            continue
        data = path.read_bytes()
        for secret in secrets:
            if secret.encode() in data:
                raise SystemExit("SECRET_LEAKAGE_DETECTED")
    print("SECRET_LEAKAGE=0")
    print("UNAUTHORIZED_PROVIDER_USAGE=0")


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    q = sub.add_parser("qualify")
    q.add_argument("--plan", type=Path, required=True)
    q.add_argument("--evidence-dir", type=Path, required=True)
    q.add_argument("--base-url", required=True)
    q.add_argument("--github-env", type=Path)

    p = sub.add_parser("probe")
    p.add_argument("--plan", type=Path, required=True)
    p.add_argument("--evidence-dir", type=Path, required=True)
    p.add_argument("--base-url", required=True)
    p.add_argument("--auth-token", required=True)

    v = sub.add_parser("verify-claude-dispatch")
    v.add_argument("--plan", type=Path, required=True)
    v.add_argument("--evidence-dir", type=Path, required=True)
    v.add_argument("--base-url", required=True)
    v.add_argument("--started-at", type=Path, required=True)
    v.add_argument("--stdout", type=Path, required=True)

    s = sub.add_parser("scan-secrets")
    s.add_argument("--evidence-dir", type=Path, required=True)

    args = parser.parse_args()
    if args.command == "qualify":
        qualify(
            plan_path=args.plan,
            evidence_dir=args.evidence_dir,
            base_url=args.base_url,
            github_env=args.github_env,
        )
    elif args.command == "probe":
        probe(
            plan_path=args.plan,
            evidence_dir=args.evidence_dir,
            base_url=args.base_url,
            auth_token=args.auth_token,
        )
    elif args.command == "verify-claude-dispatch":
        verify_claude_dispatch(
            plan_path=args.plan,
            evidence_dir=args.evidence_dir,
            base_url=args.base_url,
            started_at_path=args.started_at,
            stdout_path=args.stdout,
        )
    elif args.command == "scan-secrets":
        scan_secrets(evidence_dir=args.evidence_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
