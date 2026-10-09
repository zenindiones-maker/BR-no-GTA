"""Negative and bounded tests of the BR Agent Office third-party source inventory."""
import unittest

from scripts.br_v24_office_network_boundary_review import FILES, inspect_sources


def sources():
    return {
        "src/main/hive.ts": (
            b"const server = createServer(handler);\nserver.listen(3314, '127.0.0.1');\n"
        ),
        "src/main/hooks.ts": (
            b"const sockPath = '/tmp/br-test.sock';\nserver.listen(sockPath);\n"
        ),
        "src/main/integrationBroker.ts": (
            b"const t = issueToken();\nserver.listen(103, '127.0.0.1');\n"
        ),
        "src/main/telemetry.ts": (
            b"this.host = opts.host ?? '127.0.0.1';\nserver.listen(this.port, this.host);\n"
        ),
    }


class ReadOnlyBoundaryEvidenceTests(unittest.TestCase):
    def test_every_known_source_and_risk_is_represented(self):
        report = inspect_sources(sources())
        self.assertEqual(len(FILES), report["sources_checked"])
        self.assertEqual("PASS" if report["source_inventory_completed"] else "FAIL", "PASS")
        self.assertEqual("PENDING", report["authenticated_independent_security_review"])
        self.assertEqual("NOT_PROVEN", report["host_origin_safety"])
        self.assertEqual("NOT_PROVEN", report["socket_path_safety"])
        self.assertEqual("BLOCKED", report["third_party_runtime_admission"])
        self.assertFalse(report["a15_compute"])
        self.assertEqual(64, len(report["receipt_sha256"]))
        self.assertEqual({"src/main/hive.ts", "src/main/hooks.ts",
                          "src/main/integrationBroker.ts", "src/main/telemetry.ts"},
                         {r["source_path"] for r in report["source_evidence"]})

    def test_missing_or_extra_source_fails(self):
        for altered in (
            {k:v for k,v in sources().items() if k != "src/main/hooks.ts"},
            {**sources(), "src/main/untrusted.ts": b"server.listen(0.0.0.0)"},
        ):
            with self.assertRaisesRegex(ValueError, "REQUIRED_SOURCE"):
                inspect_sources(altered)

    def test_removed_telemetry_listener_is_not_trusted(self):
        values=sources()
        values["src/main/telemetry.ts"]=b"this.host='127.0.0.1';"
        with self.assertRaisesRegex(ValueError, "TELEMETRY_LISTENER"):
            inspect_sources(values)

    def test_missing_explicit_broker_loopback_fails(self):
        values=sources()
        values["src/main/integrationBroker.ts"]=b"server.listen(103);"
        with self.assertRaisesRegex(ValueError, "BROKER_BOUNDARY"):
            inspect_sources(values)

    def test_missing_unix_socket_identification_fails(self):
        values=sources()
        values["src/main/hooks.ts"]=b"server.listen(130);"
        with self.assertRaisesRegex(ValueError, "UNIX_SOCKET"):
            inspect_sources(values)

    def test_invalid_file_payload_or_bounds_fails(self):
        for payload in (b"", b"\xff", b"x" * 200_001):
            values=sources()
            values["src/main/hooks.ts"]=payload
            with self.subTest(length=len(payload)):
                with self.assertRaises(ValueError):
                    inspect_sources(values)

    def test_no_raw_source_or_secrets_in_receipt(self):
        values=sources()
        values["src/main/hooks.ts"]+=b"const token='SENSITIVE_CANARY_FAKE';"
        report=inspect_sources(values)
        self.assertNotIn("SENSITIVE_CANARY_FAKE", str(report))
        self.assertIn("token_reference", report["source_evidence"][1]["pattern_occurrences"])


if __name__ == "__main__":
    unittest.main()
