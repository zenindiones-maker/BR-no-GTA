"""Fail-closed test matrix for exact Agent Office isolated review bundle."""
from __future__ import annotations

from hashlib import sha256
import copy
import unittest

from scripts.br_v24_office_review_bundle import CHANGES, verify_candidate
from scripts.br_v24_agent_office_no_ingress_patch import SOURCES, patch_source


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


def scenario():
    originals={name: ORIGINAL.encode() for name in SOURCES}
    current={name: patch_source(ORIGINAL).encode() for name in SOURCES}
    patches=[{
        "file":name,
        "old_sha256":sha256(originals[name]).hexdigest(),
        "candidate_sha256":sha256(current[name]).hexdigest(),
        "external_tunnel_import_present":False,
        "start_guard_static":True,
        "real_server_started":False,
    } for name in SOURCES]
    pkg={"dependencies":{"express":"^4.0.0"},"overrides":{"proxy-addr":"2.0.8"}}
    lock={"lockfileVersion":3,"packages":{
        "":{"dependencies":dict(pkg["dependencies"])},
        "node_modules/express":{"version":"4.20.0"},
    }}
    audit={"vulnerabilities":{},"metadata":{"vulnerabilities":{
        "critical":0,"high":0,"moderate":0,"low":0,"info":0,"total":0,
    }}}
    receipt={"schema":"BRV24AgentOfficeNoIngressSourcePatch/v1",
             "files":patches,"runtime_authority_granted":False}
    return {"originals":originals,"candidate_sources":current,
            "package":pkg,"lock":lock,"audit":audit,
            "patch_receipt":receipt,"changed_paths":set(CHANGES)}


class ReviewBundleTests(unittest.TestCase):
    def test_two_original_sources_exactly_reconstructed_no_runtime_authority(self):
        out=verify_candidate(**scenario())
        self.assertTrue(out["source_exact_patch_reconstruction"])
        self.assertEqual(2,len(out["source_digests"]))
        self.assertEqual("REQUIRED",out["independent_security_review"])
        self.assertFalse(out["runtime_authorized"])
        self.assertFalse(out["mcp_connected"])
        self.assertFalse(out["a15_compute"])
        self.assertEqual(64,len(out["receipt_sha256"]))

    def test_changed_source_body_fails_even_if_compilable(self):
        x=scenario()
        p=SOURCES[0]
        x["candidate_sources"][p]+=b"\nexport const unsafe = true;\n"
        with self.assertRaisesRegex(ValueError,"NOT_REPRODUCIBLE"):
            verify_candidate(**x)

    def test_fake_receipt_digest_does_not_grant_pass(self):
        x=scenario()
        x["patch_receipt"]["files"][0]["candidate_sha256"]="f"*64
        with self.assertRaisesRegex(ValueError,"RECEIPT_HASH_MISMATCH"):
            verify_candidate(**x)

    def test_non_whitelisted_file_mutation_is_denied(self):
        x=scenario()
        x["changed_paths"].add("src/main/index.ts")
        with self.assertRaisesRegex(ValueError,"UNEXPECTED_CHANGED_PATHS"):
            verify_candidate(**x)

    def test_high_severity_cannot_be_silenced_by_summary(self):
        x=scenario()
        x["audit"]["vulnerabilities"]["bad"]={
            "severity":"critical","nodes":["node_modules/bad"]
        }
        with self.assertRaisesRegex(ValueError,"HIGH_CRITICAL"):
            verify_candidate(**x)

    def test_nonzero_metadata_severity_fails(self):
        x=scenario()
        x["audit"]["metadata"]["vulnerabilities"].update({"high":1,"total":1})
        with self.assertRaisesRegex(ValueError,"HIGH_CRITICAL"):
            verify_candidate(**x)

    def test_inconsistent_audit_counts_are_not_accepted(self):
        x=scenario()
        x["audit"]["metadata"]["vulnerabilities"]["total"]=3
        with self.assertRaisesRegex(ValueError,"SUMMARY_INCONSISTENT"):
            verify_candidate(**x)

    def test_bad_untrusted_npm_audit_is_rejected(self):
        x=scenario()
        x["audit"]["vulnerabilities"]="ERROR"
        with self.assertRaisesRegex(ValueError,"AUDIT_UNTRUSTED"):
            verify_candidate(**x)

    def test_tunnel_dependency_and_transitive_lock_reappearance_are_denied(self):
        for kind in ("direct","transitive"):
            with self.subTest(kind=kind):
                x=scenario()
                if kind=="direct":
                    x["package"]["dependencies"]["tunnelmole"]="1.0.0"
                    x["lock"]["packages"][""]["dependencies"]["tunnelmole"]="1.0.0"
                else:
                    x["lock"]["packages"]["node_modules/localtunnel"]={"version":"2.0.0"}
                with self.assertRaisesRegex(ValueError,"TUNNEL"):
                    verify_candidate(**x)

    def test_lock_drift_and_missing_patch_are_denied(self):
        x=scenario()
        x["lock"]["packages"][""]["dependencies"]["express"]="^3.0.0"
        with self.assertRaisesRegex(ValueError,"LOCK_PACKAGE_DRIFT"):
            verify_candidate(**x)
        x=scenario()
        x["patch_receipt"]["files"]=[]
        with self.assertRaisesRegex(ValueError,"PATCH_RECEIPT_INCOMPLETE"):
            verify_candidate(**x)


if __name__ == "__main__":
    unittest.main()
