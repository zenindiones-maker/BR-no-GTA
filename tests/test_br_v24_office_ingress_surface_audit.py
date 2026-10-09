"""Fail-closed regression contracts for complete pinned-source ingress inventory."""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.br_v24_office_ingress_surface_audit import (
    EXPECTED_SHA, survey,
)
from scripts.br_v24_agent_office_no_ingress_patch import patch_source

ORIGINAL = """export class Server {
  async start(): Promise<{ ok: boolean; url?: string; error?: string }> {
    await this.listen();
    return { ok: true };
  }
  private async openTunnel(): Promise<string> {
    const { tunnelmole } = await import('tunnelmole');
    return "https://untrusted.invalid";
  }
}
"""


class OfficeIngressSurfaceInventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        main = self.root / "src" / "main"
        main.mkdir(parents=True)
        for name in ("slack.ts", "webhook.ts"):
            (main / name).write_text(patch_source(ORIGINAL), encoding="utf-8")

    def test_two_original_sources_remain_guarded_but_review_required(self):
        result = survey(self.root, vendor_head=EXPECTED_SHA)
        self.assertEqual(2, result["files_scanned"])
        self.assertTrue(result["two_guarded_files_verified"])
        self.assertEqual(0, result["unreviewed_surface_count"])
        self.assertEqual("REQUIRED", result["independent_security_review"])
        self.assertFalse(result["runtime_authorized"])

    def test_detects_another_listener_in_unreviewed_entrypoint(self):
        path = self.root / "src/main/secondary.ts"
        path.write_text("const s = net.createServer(); s.listen(8080);\n")
        result = survey(self.root, vendor_head=EXPECTED_SHA)
        self.assertEqual("UNREVIEWED_INGRESS_FOUND", result["status"])
        self.assertEqual(2, result["unreviewed_surface_count"])
        self.assertTrue(any(f["path"] == "src/main/secondary.ts" for f in result["findings"]))

    def test_removed_static_guard_fails_closed(self):
        (self.root / "src/main/slack.ts").write_text(ORIGINAL)
        with self.assertRaisesRegex(ValueError,"GUARD_DRIFT"):
            survey(self.root, vendor_head=EXPECTED_SHA)

    def test_missing_guarded_source_fails_closed(self):
        (self.root / "src/main/webhook.ts").unlink()
        with self.assertRaisesRegex(ValueError,"MISSING_GUARDED_SOURCE"):
            survey(self.root, vendor_head=EXPECTED_SHA)

    def test_symlink_source_is_denied(self):
        path = self.root / "src/main/injected.ts"
        path.symlink_to(self.root / "src/main/slack.ts")
        with self.assertRaisesRegex(ValueError,"SYMLINK"):
            survey(self.root, vendor_head=EXPECTED_SHA)

    def test_wrong_vendor_commit_denied(self):
        with self.assertRaisesRegex(ValueError,"UNTRUSTED_VENDOR"):
            survey(self.root, vendor_head="a"*40)

    def test_no_raw_source_text_in_result(self):
        result = survey(self.root, vendor_head=EXPECTED_SHA)
        self.assertNotIn("https://untrusted.invalid",repr(result))
        self.assertNotIn("server.listen(8080)",repr(result))


if __name__ == "__main__":
    unittest.main()
