"""Regression contracts: telemetry cannot bind nonloopback in V24 candidate."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.br_v24_office_telemetry_loopback_patch import (
    ORIGINAL_ASSIGNMENT, EXPECTED_LISTEN, REPLACEMENT, patch_source, apply,
)

SAMPLE = """
export class Telemetry {
  constructor(opts: TelemetryCollectorOptions = {}) {
    this.host = opts.host ?? '127.0.0.1';
    this.port = opts.port ?? 0;
  }
  private listen(): Promise<void> {
    return new Promise((resolve) => {
      server.listen(this.port, this.host, () => { resolve(); });
    });
  }
}
"""


class TelemetryLoopbackTests(unittest.TestCase):
    def test_patched_constructor_uses_exact_allowlist(self):
        fixed = patch_source(SAMPLE)
        self.assertIn(REPLACEMENT, fixed)
        self.assertNotIn(ORIGINAL_ASSIGNMENT, fixed)
        self.assertIn(EXPECTED_LISTEN, fixed)
        self.assertEqual(1, fixed.count("requestedHost !== '127.0.0.1'"))
        self.assertEqual(1, fixed.count("requestedHost !== '::1'"))
        self.assertEqual(1, fixed.count("this.host = requestedHost;"))

    def test_no_duplicate_or_prepatched_source(self):
        with self.assertRaisesRegex(ValueError, "ORIGINAL_CONTRACT_DRIFT"):
            patch_source(SAMPLE + SAMPLE)
        with self.assertRaisesRegex(ValueError, "ORIGINAL_CONTRACT_DRIFT"):
            patch_source(SAMPLE.replace(ORIGINAL_ASSIGNMENT, "this.host = opts.host;"))
        with self.assertRaises(ValueError):
            patch_source(patch_source(SAMPLE))

    def test_source_without_expected_listen_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "ORIGINAL_CONTRACT_DRIFT"):
            patch_source(SAMPLE.replace(EXPECTED_LISTEN, "server.listen(8080, () => {"))

    def test_real_disposable_write_is_bounded_and_receipted(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            file = root / "src/main/telemetry.ts"
            file.parent.mkdir(parents=True)
            file.write_text(SAMPLE)
            receipt = apply(root)
            self.assertEqual("LOOPBACK_ONLY", receipt["bind_authority"])
            self.assertEqual(64, len(receipt["original_sha256"]))
            self.assertEqual(64, len(receipt["candidate_sha256"]))
            self.assertNotEqual(receipt["candidate_sha256"],receipt["original_sha256"])
            self.assertFalse(receipt["network_listener_started"])
            self.assertEqual("REQUIRED",receipt["independent_security_review"])

    def test_symlink_target_refused(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = root / "src/main/telemetry.ts"
            a.parent.mkdir(parents=True)
            target = root / "source.ts"
            target.write_text(SAMPLE)
            a.symlink_to(target)
            with self.assertRaisesRegex(ValueError,"SOURCE_MISSING"):
                apply(root)


if __name__ == "__main__":
    unittest.main()
