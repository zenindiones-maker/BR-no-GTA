"""Proof that a disposable Agent Office ingress patch always refuses sockets."""
import tempfile
from pathlib import Path
import unittest

from scripts.br_v24_agent_office_no_ingress_patch import (
    GUARD, SOURCES, apply_to_disposable_source, patch_source,
)


SAMPLE="""export class WebhookServer {
  async start(): Promise<{ ok: boolean; url?: string; error?: string }> {
    await this.listen();
    return { ok: true };
  }
  private async openTunnel(): Promise<string> {
    const { tunnelmole } = await import('tunnelmole');
    return new Promise<string>((resolve) => {
      resolve('https://untrusted.example');
    });
  }
}
"""


class ExternalIngressGuardTests(unittest.TestCase):
    def test_inserts_fails_closed_guard_before_socket_bind(self):
        changed=patch_source(SAMPLE)
        self.assertLess(changed.index("BR security policy: external ingress disabled"),
                        changed.index("await this.listen()"))
        self.assertIn(GUARD,changed)
        self.assertNotIn("import('tunnelmole')",changed)
        self.assertIn("throw new Error('BR security policy: external tunnels disabled')",changed)

    def test_missing_explicit_entrypoint_never_gets_approved(self):
        with self.assertRaisesRegex(ValueError,"START_SIGNATURE_DRIFT"):
            patch_source(SAMPLE.replace("async start()", "async boot()"))

    def test_duplicate_entrypoint_is_unsafe(self):
        with self.assertRaisesRegex(ValueError,"START_SIGNATURE_DRIFT"):
            patch_source(SAMPLE+SAMPLE)

    def test_missing_upstream_dynamic_tunnel_prevents_patch(self):
        with self.assertRaisesRegex(ValueError,"PINNED_TUNNEL_NOT_FOUND"):
            patch_source(SAMPLE.replace("import('tunnelmole')","no_tunnel_code"))

    def test_two_original_source_paths_only(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            for name in SOURCES:
                p=root/name
                p.parent.mkdir(parents=True,exist_ok=True)
                p.write_text(SAMPLE)
            report=apply_to_disposable_source(root)
            self.assertEqual(2,len(report["files"]))
            self.assertFalse(report["runtime_authority_granted"])
            self.assertTrue(all(
                "import('tunnelmole')" not in (root / row["file"]).read_text()
                for row in report["files"]
            ))


if __name__ == "__main__":
    unittest.main()
