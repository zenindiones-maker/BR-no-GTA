"""Adversarial exact-source negative VM gate, no upstream runtime or socket."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch
import unittest

from scripts.br_v24_office_telemetry_loopback_patch import (
    ORIGINAL_ASSIGNMENT, EXPECTED_LISTEN, REPLACEMENT,
)
from scripts.br_v24_office_telemetry_negative_vm import (
    checked_source, test_guard, NODE_TEST_JS,
)


class ExactNegativeHostGate(unittest.TestCase):
    SAMPLE = (
        "class Telemetry {\n"
        "  constructor(opts) {\n"
        + ORIGINAL_ASSIGNMENT + "\n"
        "  }\n"
        "  listen(server) {\n"
        + EXPECTED_LISTEN + "\n"
        "  }\n"
        "}\n"
    )

    def test_exact_patched_source_is_accepted(self):
        original = self.SAMPLE
        patched = original.replace(ORIGINAL_ASSIGNMENT, REPLACEMENT)
        result = checked_source(patched.encode())
        self.assertTrue(result["exact_guard_match"])
        self.assertEqual(64, len(result["source_sha256"]))

    def test_original_unpatched_wildcard_host_rejected(self):
        with self.assertRaisesRegex(ValueError, "PATCH_NOT_EXACT"):
            checked_source(self.SAMPLE.encode())

    def test_duplicate_guard_rejected(self):
        patched = self.SAMPLE.replace(ORIGINAL_ASSIGNMENT, REPLACEMENT)
        with self.assertRaisesRegex(ValueError, "PATCH_NOT_EXACT"):
            checked_source((patched + REPLACEMENT).encode())

    def test_no_listener_rejected(self):
        patched = self.SAMPLE.replace(ORIGINAL_ASSIGNMENT, REPLACEMENT)
        with self.assertRaisesRegex(ValueError, "PATCH_NOT_EXACT"):
            checked_source(patched.replace(EXPECTED_LISTEN, "server.listen(80);").encode())

    def test_source_bounds_and_non_utf8_rejected(self):
        for data in (b"", b"x" * 250_001, b"\\xff"):
            with self.subTest(n=len(data)):
                with self.assertRaises((ValueError, UnicodeError)):
                    checked_source(data)

    def test_run_is_only_an_isolated_guard_not_an_upstream_import(self):
        self.assertNotIn("require('net')", NODE_TEST_JS)
        self.assertNotIn("require('http')", NODE_TEST_JS)
        self.assertNotIn("server.listen(", NODE_TEST_JS)
        self.assertIn("vm.createContext", NODE_TEST_JS)

    def test_real_node_vm_allowed_denied_host_cases(self):
        # Tests only BR-owned exact guard snippet, never untrusted upstream.
        report = test_guard()
        self.assertEqual(4, report["allowed"])
        self.assertEqual(11, report["denied"])
        self.assertFalse(report["vendor_runtime_started"])
        self.assertEqual(0, report["network_listeners_opened"])


if __name__ == "__main__":
    unittest.main()
