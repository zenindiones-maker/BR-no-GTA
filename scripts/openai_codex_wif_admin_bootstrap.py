from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import urllib.error
import urllib.request
from typing import Any

API_BASE = "https://api.openai.com/v1/organization/workload_identity"
ISSUER = "https://token.actions.githubusercontent.com"
DEFAULT_AUDIENCE = "https://api.openai.com/codex/zenindiones-maker/BR-no-GTA"
DEFAULT_PROVIDER_NAME = "github-actions-br-no-gta-codex"
DEFAULT_RULE_NAME = "br-no-gta-gate6f-codex"
REPOSITORY = "zenindiones-maker/BR-no-GTA"
REF = "refs/heads/work/gate6f-analytics-learning"


class AdminBootstrapRequired(RuntimeError):
    pass


def _required_admin_action(message: str) -> None:
    print(f"OPENAI_WIF_ADMIN_BOOTSTRAP_REQUIRED={message}", flush=True)


def _request(
    *,
    method: str,
    path: str,
    admin_key: str,
    payload: dict[str, Any] | None = None,
) -> Any:
    body = None
    headers = {
        "Authorization": f"Bearer {admin_key}",
        "Accept": "application/json",
    }
    if payload is not None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        API_BASE + path,
        data=body,
        method=method,
        headers=headers,
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1200]
        if exc.code in {403, 404}:
            raise AdminBootstrapRequired(
                "enable Codex Workload Identity Federation beta for the managed "
                "ChatGPT workspace and ensure the OpenAI Admin API key owner can "
                "manage workload identity"
            ) from None
        raise RuntimeError(
            f"OpenAI WIF Admin API HTTP {exc.code}: {detail}"
        ) from None
    if not raw:
        return {}
    return json.loads(raw)


def _items(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def _provider_matches(item: dict[str, Any], *, audience: str) -> bool:
    return (
        item.get("type") == "oidc"
        and item.get("issuer") == ISSUER
        and item.get("audience") == audience
        and item.get("enabled", True) is not False
    )


def _claims_match(item: dict[str, Any]) -> bool:
    claims = item.get("claims")
    if not isinstance(claims, dict):
        return False
    return (
        claims.get("repository") == REPOSITORY
        and claims.get("ref") == REF
    )


def _rule_matches(item: dict[str, Any], *, audience: str) -> bool:
    audiences = item.get("audiences")
    audience_ok = True
    if isinstance(audiences, list) and audiences:
        audience_ok = audience in audiences
    return (
        item.get("enabled", True) is not False
        and _claims_match(item)
        and audience_ok
    )


def reconcile(
    *,
    admin_key: str,
    audience: str,
    workspace_id: str,
    principal_id: str,
) -> dict[str, Any]:
    providers = _items(
        _request(method="GET", path="/providers", admin_key=admin_key)
    )
    provider = next(
        (
            item
            for item in providers
            if _provider_matches(item, audience=audience)
        ),
        None,
    )
    provider_created = False
    if provider is None:
        provider = _request(
            method="POST",
            path="/providers",
            admin_key=admin_key,
            payload={
                "name": DEFAULT_PROVIDER_NAME,
                "description": (
                    "GitHub Actions OIDC for zenindiones-maker/BR-no-GTA on "
                    "work/gate6f-analytics-learning"
                ),
                "type": "oidc",
                "issuer": ISSUER,
                "audience": audience,
                "max_assertion_lifetime_seconds": 600,
                "check_jti": True,
            },
        )
        provider_created = True

    provider_id = str(provider.get("id") or "").strip()
    if not provider_id.startswith("idp_"):
        raise RuntimeError(
            "OpenAI WIF provider response did not contain a valid provider id"
        )

    rules = _items(
        _request(
            method="GET",
            path=f"/providers/{provider_id}/mappings",
            admin_key=admin_key,
        )
    )
    rule = next(
        (item for item in rules if _rule_matches(item, audience=audience)),
        None,
    )
    rule_created = False
    if rule is None:
        if not workspace_id or not principal_id:
            raise AdminBootstrapRequired(
                "provide the managed ChatGPT workspace ID and an existing active "
                "ChatGPT user/service-account principal ID, or create the Codex "
                "federation rule once in the OpenAI Admin Portal"
            )
        rule = _request(
            method="POST",
            path=f"/providers/{provider_id}/mappings",
            admin_key=admin_key,
            payload={
                "name": DEFAULT_RULE_NAME,
                "description": (
                    "Codex WIF for zenindiones-maker/BR-no-GTA branch "
                    "work/gate6f-analytics-learning"
                ),
                "workspace_id": workspace_id,
                "principal_id": principal_id,
                "claims": {
                    "repository": REPOSITORY,
                    "ref": REF,
                },
                "audiences": [audience],
                "access_token_lifetime_seconds": 600,
                "enabled": True,
            },
        )
        rule_created = True

    rule_id = str(rule.get("id") or "").strip()
    if not rule_id.startswith("idpm_"):
        raise RuntimeError(
            "OpenAI WIF rule response did not contain a valid federation rule id"
        )

    return {
        "status": "PASS",
        "issuer": ISSUER,
        "audience": audience,
        "repository": REPOSITORY,
        "ref": REF,
        "provider_id": provider_id,
        "provider_created": provider_created,
        "federation_rule_id": rule_id,
        "rule_created": rule_created,
        "runtime_auth_variables": [
            "OPENAI_FEDERATION_RULE_ID",
            "OPENAI_IDENTITY_TOKEN_FILE",
        ],
        "credential_material_persisted": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--audience",
        default=os.getenv(
            "OPENAI_FEDERATION_AUDIENCE",
            DEFAULT_AUDIENCE,
        ),
    )
    parser.add_argument(
        "--workspace-id",
        default=os.getenv("OPENAI_WIF_WORKSPACE_ID", ""),
    )
    parser.add_argument(
        "--principal-id",
        default=os.getenv("OPENAI_WIF_PRINCIPAL_ID", ""),
    )
    args = parser.parse_args()

    admin_key = os.getenv("OPENAI_ADMIN_KEY", "").strip()
    if not admin_key:
        _required_admin_action(
            "provide a one-time OpenAI Admin API key to the bootstrap job or "
            "create/reuse the provider and Codex federation rule in the OpenAI "
            "Admin Portal"
        )
        return 20

    try:
        result = reconcile(
            admin_key=admin_key,
            audience=str(args.audience).strip(),
            workspace_id=str(args.workspace_id).strip(),
            principal_id=str(args.principal_id).strip(),
        )
    except AdminBootstrapRequired as exc:
        _required_admin_action(str(exc))
        return 20

    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print("OPENAI_WIF_ADMIN_RECONCILIATION=PASS")
    print(f"OPENAI_FEDERATION_RULE_ID={result['federation_rule_id']}")
    print(f"OPENAI_FEDERATION_AUDIENCE={result['audience']}")
    print("AUTH_SECRET_LEAK=NO")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
