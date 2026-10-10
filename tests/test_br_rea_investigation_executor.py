"""Adversarial real-filesystem and persisted Harness authorization regression.

No mocks, no network, no ARTEX runtime, no paid models.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from app.services.br_rea_issuer_attestation_service import (
    SCHEMA, PUBLIC_KEY_ENV, canonical_message,
)
from hashlib import sha256
import time
import os
from pathlib import Path
import tempfile
import unittest

from app.database.schema import initialize_schema
from app.services.br_rea_investigation_executor import (
    CAPABILITY_ID,
    InvestigationBlocked,
    InvestigationRequest,
    ROOT,
    _read_scoped,
    execute_br_rea_investigation,
    inspect_first_party_sources,
)
from app.services.harness_authorization_service import (
    issue_harness_authorization,
    revoke_harness_authorization,
)
from app.services.harness_capability_service import (
    authorize_capability,
    execute_capability,
)
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest,
    route_harness_request,
)


class ReaInvestigationAdversarialTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="rea-adversarial-")
        self.old_public_key = os.environ.get(PUBLIC_KEY_ENV)
        self.private_key = Ed25519PrivateKey.generate()
        os.environ[PUBLIC_KEY_ENV] = base64.b64encode(
            self.private_key.public_key().public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
        ).decode("ascii")
        self.old_database = os.environ.get("BR_TEST_DATABASE")
        os.environ["BR_TEST_DATABASE"] = str(Path(self.temp.name) / "harness.sqlite")
        initialize_schema()

    def tearDown(self):
        if self.old_database is None:
            os.environ.pop("BR_TEST_DATABASE", None)
        else:
            os.environ["BR_TEST_DATABASE"] = self.old_database
        if self.old_public_key is None:
            os.environ.pop(PUBLIC_KEY_ENV, None)
        else:
            os.environ[PUBLIC_KEY_ENV] = self.old_public_key
        self.temp.cleanup()

    def grant(self, action="DEVELOPMENT", subject=None):
        return issue_harness_authorization(
            authorized_action=action,
            subject=subject or f"capability:{CAPABILITY_ID}",
        )

    def payload(self, auth, paths=None):
        paths = paths or ["app/services/harness_capability_service.py"]
        issued_at = int(time.time())
        expires_at = issued_at + 60
        proof = {
            "schema": SCHEMA,
            "issued_at": issued_at,
            "expires_at": expires_at,
        }
        proof["signature_b64"] = base64.b64encode(
            self.private_key.sign(
                canonical_message(auth, tuple(paths), issued_at=issued_at, expires_at=expires_at)
            )
        ).decode("ascii")
        return {
            "authorization_id": auth.authorization_id,
            "harness_decision_id": auth.harness_decision_id,
            "execution_id": auth.execution_id,
            "paths": paths,
            "issuer_attestation": proof,
        }

    def test_real_harness_capability_executes_and_hashes_actual_file(self):
        auth = self.grant()
        routing = route_harness_request(HarnessRoutingRequest(
            intent="reverse engineering source dependency",
            authorized_action="DEVELOPMENT",
            required_capability_id=CAPABILITY_ID,
            fallback_allowed=False,
        ))
        evidence = execute_capability(
            capability_id=CAPABILITY_ID,
            authorization=auth,
            payload=self.payload(auth),
            routing_decision=routing,
            executor=execute_br_rea_investigation,
        )
        self.assertEqual(evidence.status, "EXECUTED")
        result = evidence.result
        self.assertEqual(result["schema"], "BRReaInvestigationEvidence/v1")
        actual = (ROOT / result["sources"][0]["path"]).read_bytes()
        self.assertEqual(result["sources"][0]["sha256"], sha256(actual).hexdigest())
        self.assertNotIn("source_text", result)
        canonical = evidence.to_canonical_result(authorization_id=auth.authorization_id)
        self.assertTrue(canonical.success)

    def test_replay_is_denied_after_single_success(self):
        auth = self.grant()
        first = execute_capability(
            capability_id=CAPABILITY_ID, authorization=auth,
            payload=self.payload(auth), executor=execute_br_rea_investigation,
        )
        self.assertEqual(first.status, "EXECUTED")
        with self.assertRaises(PermissionError):
            execute_capability(
                capability_id=CAPABILITY_ID, authorization=auth,
                payload=self.payload(auth), executor=execute_br_rea_investigation,
            )

    def test_wrong_action_and_subject_denied_before_executor(self):
        for action, subject in [
            ("PUBLICATION", f"capability:{CAPABILITY_ID}"),
            ("DEVELOPMENT", "capability:another"),
        ]:
            with self.subTest(action=action, subject=subject):
                auth = self.grant(action=action, subject=subject)
                with self.assertRaises(PermissionError):
                    execute_capability(
                        capability_id=CAPABILITY_ID, authorization=auth,
                        payload=self.payload(auth), executor=execute_br_rea_investigation,
                    )

    def test_fabricated_grant_rejected(self):
        with self.assertRaises(PermissionError):
            authorize_capability(CAPABILITY_ID, "nonexistent-authorization")

    def test_cross_auth_payload_rejected_before_any_consumption(self):
        real = self.grant()
        other = self.grant()
        with self.assertRaises(PermissionError):
            execute_capability(
                capability_id=CAPABILITY_ID, authorization=real,
                payload=self.payload(other), executor=execute_br_rea_investigation,
            )
        evidence = execute_capability(
            capability_id=CAPABILITY_ID, authorization=real,
            payload=self.payload(real), executor=execute_br_rea_investigation,
        )
        self.assertEqual(evidence.status, "EXECUTED")

    def test_revocation_denied(self):
        auth = self.grant()
        revoke_harness_authorization(auth)
        with self.assertRaises(PermissionError):
            execute_capability(
                capability_id=CAPABILITY_ID, authorization=auth,
                payload=self.payload(auth), executor=execute_br_rea_investigation,
            )

    def test_wrong_executor_override_denied(self):
        auth = self.grant()
        def attacker_executor(capability, payload):
            raise RuntimeError("UNAUTHORIZED_EXECUTOR_CALLED")
        with self.assertRaises(PermissionError):
            execute_capability(
                capability_id=CAPABILITY_ID, authorization=auth,
                payload=self.payload(auth), executor=attacker_executor,
            )

    def test_invalid_payload_injection_denied(self):
        auth = self.grant()
        payload = self.payload(auth)
        payload["command"] = "curl https://external.example"
        evidence = execute_capability(
            capability_id=CAPABILITY_ID, authorization=auth,
            payload=payload, executor=execute_br_rea_investigation,
        )
        self.assertEqual(evidence.status, "FAILED")
        self.assertEqual(evidence.result.get("error_type"), "InvestigationBlocked")

    def test_scope_escapes_and_credentials_denied(self):
        auth = self.grant()
        for path in (
            "../../etc/passwd", "/etc/passwd", "app/services/../../.env",
            "app/services//data.py", "app/services/.git/config.py",
            "app/services/credentials.py", "app/services/harness.py/../secret.py",
            "integrations/rea/private.py", "app/services/test.yaml",
        ):
            with self.subTest(path=path), self.assertRaises(InvestigationBlocked):
                _read_scoped(ROOT, path)
        self.assertIsNotNone(auth.authorization_id)

    def test_symlink_scoped_read_denied_without_following(self):
        fixture = Path(self.temp.name)
        (fixture / "app/services").mkdir(parents=True)
        private = fixture / "outside.py"
        private.write_text("private_key = 'not-for-reading'")
        (fixture / "app/services/visible.py").symlink_to(private)
        with self.assertRaises(InvestigationBlocked):
            _read_scoped(fixture, "app/services/visible.py")

    def test_nested_symlink_scoped_read_denied(self):
        fixture = Path(self.temp.name)
        (fixture / "outside").mkdir()
        (fixture / "outside/demo.py").write_text("x=1")
        (fixture / "app").mkdir()
        (fixture / "app/services").symlink_to(fixture / "outside")
        with self.assertRaises(InvestigationBlocked):
            _read_scoped(fixture, "app/services/demo.py")

    def test_denies_oversized_source_and_corrupt_python(self):
        fixture = Path(self.temp.name)
        (fixture / "app/services").mkdir(parents=True)
        (fixture / "app/services/large.py").write_bytes(b"#" * (256 * 1024 + 1))
        with self.assertRaises(InvestigationBlocked):
            _read_scoped(fixture, "app/services/large.py")
        (fixture / "app/services/bad.py").write_text("def broken(: pass")
        request = InvestigationRequest(
            "auth", "decision", "execution", ("app/services/bad.py",), {}
        )
        with self.assertRaises(InvestigationBlocked):
            inspect_first_party_sources(request, root=fixture)

    def test_does_not_return_source_content_or_emit_side_effects(self):
        auth = self.grant()
        evidence = execute_capability(
            capability_id=CAPABILITY_ID, authorization=auth,
            payload=self.payload(auth), executor=execute_br_rea_investigation,
        )
        observed = evidence.result
        self.assertNotIn("content", str(observed).lower())
        self.assertNotIn("source_text", str(observed).lower())
        self.assertEqual(observed["status"], "OBSERVED")
        self.assertTrue(observed["receipt_sha256"])

    def test_import_edge_grounded_in_ast(self):
        auth = self.grant()
        request = InvestigationRequest.from_payload(
            self.payload(auth, paths=["app/services/harness_capability_service.py"])
        )
        observed = inspect_first_party_sources(request)
        imports = observed["sources"][0]["first_party_imports"]
        self.assertTrue(any(
            e["module"] == "app.services.harness_authorization_service" and e["status"] == "PRESENT"
            for e in imports
        ))


    def test_unsigned_sqlite_grant_cannot_execute(self):
        auth = self.grant()
        unsigned = self.payload(auth)
        del unsigned["issuer_attestation"]
        result = execute_capability(
            capability_id=CAPABILITY_ID,
            authorization=auth, payload=unsigned,
            executor=execute_br_rea_investigation,
        )
        self.assertEqual(result.status, "FAILED")
        self.assertNotEqual(result.result.get("error_type"), None)

    def test_signature_rejects_path_scope_tampering_and_wrong_key(self):
        auth = self.grant()
        valid = self.payload(auth)
        altered = {**valid, "paths": ["app/database/harness_authorization_repository.py"]}
        observed = execute_capability(
            capability_id=CAPABILITY_ID, authorization=auth,
            payload=altered, executor=execute_br_rea_investigation,
        )
        self.assertEqual(observed.status, "FAILED")
        alternate = Ed25519PrivateKey.generate()
        os.environ[PUBLIC_KEY_ENV] = base64.b64encode(
            alternate.public_key().public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
        ).decode("ascii")
        observed2 = execute_capability(
            capability_id=CAPABILITY_ID, authorization=auth,
            payload=valid, executor=execute_br_rea_investigation,
        )
        self.assertEqual(observed2.status, "FAILED")

    def test_no_trust_anchor_fail_closed(self):
        auth = self.grant()
        valid = self.payload(auth)
        os.environ.pop(PUBLIC_KEY_ENV, None)
        result = execute_capability(
            capability_id=CAPABILITY_ID, authorization=auth,
            payload=valid, executor=execute_br_rea_investigation,
        )
        self.assertEqual(result.status, "FAILED")

    def test_expired_proof_denied_even_with_valid_signature(self):
        auth = self.grant()
        valid = self.payload(auth)
        expired = int(time.time()) - 12
        issued = expired - 20
        valid["issuer_attestation"] = {
            "schema": SCHEMA,
            "issued_at": issued, "expires_at": expired,
            "signature_b64": base64.b64encode(
                self.private_key.sign(
                    canonical_message(auth, tuple(valid["paths"]), issued_at=issued, expires_at=expired)
                )
            ).decode("ascii"),
        }
        result = execute_capability(
            capability_id=CAPABILITY_ID, authorization=auth,
            payload=valid, executor=execute_br_rea_investigation,
        )
        self.assertEqual(result.status, "FAILED")


if __name__ == "__main__":
    unittest.main()
