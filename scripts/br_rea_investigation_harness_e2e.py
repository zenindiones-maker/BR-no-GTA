#!/usr/bin/env python3
"""Real deterministic BR-native REA investigation through routed DeepSeek Harness.

Requires the installed BR project Python dependencies. No external ARTEX
runtime, phone computation, network, model inference or repository mutation.
Creates only an ephemeral Harness SQLite database on an authorized runner.
"""
from __future__ import annotations

import base64
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from app.services.br_rea_issuer_attestation_service import (
    SCHEMA, PUBLIC_KEY_ENV, canonical_message,
)
import time
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile

from app.database.schema import initialize_schema
from app.services.br_rea_investigation_executor import CAPABILITY_ID, ROOT
from app.services.codex_addy_capability_executor import execute_codex_addy_capability
from app.services.harness_authorization_service import (
    issue_harness_authorization,
    resolve_harness_authorization,
)
from app.services.harness_mcp_capability_execution import execute_mcp_capability
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest,
    route_harness_request,
)


def run() -> dict:
    if os.environ.get("BR_TEST_DATABASE"):
        raise RuntimeError("E2E must use a new isolated Harness database")
    if os.environ.get(PUBLIC_KEY_ENV):
        raise RuntimeError("E2E cannot overwrite preconfigured trusted production key")
    paths = (
        "app/services/harness_capability_service.py",
        "app/services/harness_authorization_service.py",
        "app/database/harness_authorization_repository.py",
    )
    with tempfile.TemporaryDirectory(prefix="br-rea-harness-e2e-") as workspace:
        # Synthetic ephemeral CI signer tests verification math only.
        # This key does NOT attest the identity of a production issuer.
        ci_signer = Ed25519PrivateKey.generate()
        os.environ[PUBLIC_KEY_ENV] = base64.b64encode(
            ci_signer.public_key().public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
        ).decode("ascii")
        os.environ["BR_TEST_DATABASE"] = str(Path(workspace) / "harness.sqlite")
        try:
            initialize_schema()
            routing = route_harness_request(HarnessRoutingRequest(
                intent="source dependency inspection and provenance",
                authorized_action="DEVELOPMENT",
                required_capability_id=CAPABILITY_ID,
                fallback_allowed=False,
            ))
            if routing.selected_capability_id != CAPABILITY_ID or routing.fallback_occurred:
                raise RuntimeError("Unexpected Harness routing or fallback")
            implementation = routing.policy_metadata.get("selected_implementation")
            if not isinstance(implementation, dict):
                raise RuntimeError("Harness did not provide an implementation binding")
            authorization = issue_harness_authorization(
                authorized_action="DEVELOPMENT",
                subject=f"capability:{CAPABILITY_ID}",
                lineage={"routing_id": routing.routing_id, "scope": list(paths)},
            )
            now = int(time.time())
            ci_proof = {
                "schema": SCHEMA,
                "issued_at": now,
                "expires_at": now + 60,
            }
            ci_proof["signature_b64"] = base64.b64encode(
                ci_signer.sign(
                    canonical_message(
                        authorization, paths,
                        issued_at=now, expires_at=now + 60,
                    )
                )
            ).decode("ascii")
            payload = {
                "authorization_id": authorization.authorization_id,
                "harness_decision_id": authorization.harness_decision_id,
                "execution_id": authorization.execution_id,
                "paths": list(paths),
                "issuer_attestation": ci_proof,
            }
            # Signing key is not needed by the verifier.
            del ci_signer
            observed = execute_mcp_capability(
                routing_decision=routing,
                authorization=authorization,
                payload=payload,
                implementation=implementation,
                skill_executor=execute_codex_addy_capability,
            )
            if observed.status != "EXECUTED" or not observed.active:
                raise RuntimeError("Native investigator not executed through Harness")
            evidence = observed.result
            if evidence.get("schema") != "BRReaInvestigationEvidence/v1":
                raise RuntimeError("Evidence schema missing or mismatched")
            if evidence.get("source_count") != len(paths):
                raise RuntimeError("Some requested sources were not inspected")
            if [s["path"] for s in evidence["sources"]] != list(paths):
                raise RuntimeError("Source evidence does not match requested paths")
            for entry in evidence["sources"]:
                if sha256((ROOT / entry["path"]).read_bytes()).hexdigest() != entry["sha256"]:
                    raise RuntimeError("Source evidence hash does not match actual bytes")
            if not any(s["first_party_imports"] for s in evidence["sources"]):
                raise RuntimeError("AST returned no real first-party dependency relationships")
            if resolve_harness_authorization(authorization, allowed_statuses=("consumed",)).status != "consumed":
                raise RuntimeError("Authorization was not consumed")
            # Replay must fail at the persisted authorization boundary.
            from app.services.harness_authorization_service import validate_harness_authorization
            try:
                validate_harness_authorization(
                    authorization.authorization_id,
                    expected_action="DEVELOPMENT",
                    expected_subject=f"capability:{CAPABILITY_ID}",
                )
            except PermissionError:
                pass
            else:
                raise RuntimeError("Consumed authorization unexpectedly replayable")
            canonical = observed.to_canonical_result(
                authorization_id=authorization.authorization_id,
                routing_id=routing.routing_id,
                tool="br_rea_investigation_harness_e2e",
                operation="reverse-engineering.evidence.inspect",
                executor=routing.selected_executor_binding,
            )
            if not canonical.success or canonical.authority != "deepseek_harness":
                raise RuntimeError("Canonical Harness result not successful")
            return {
                "schema": "BRReaInvestigationHarnessE2E/v1",
                "status": "PASS",
                "execution": canonical.status,
                "authority": canonical.authority,
                "routing_id": routing.routing_id,
                "executor": routing.selected_executor_binding,
                "source_count": evidence["source_count"],
                "unresolved_first_party_imports": evidence["unresolved_first_party_imports"],
                "receipt_sha256": evidence["receipt_sha256"],
                "single_use": "PASS",
                "fallback": "FORBIDDEN",
                "issuer_signature_verification": "PASS_TEST_KEY_ONLY",
                "production_trusted_issuer": "UNVERIFIED",
                "third_party_runtime": "NOT_INSTALLED",
            }
        finally:
            os.environ.pop("BR_TEST_DATABASE", None)
            os.environ.pop(PUBLIC_KEY_ENV, None)


if __name__ == "__main__":
    result = run()
    print(json.dumps(result, sort_keys=True))
    print("BR_REA_HARNESS_REAL_E2E=PASS")
