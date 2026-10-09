"""Negative controls for actual npm audit security gate; no network or install."""
import unittest

from scripts.br_v24_agent_office_untrusted_npm_gate import reconcile


def audit(*, high=True):
    return {
        "metadata": {
            "vulnerabilities": {"critical":0,"high":int(high),"moderate":0,
                                "low":0,"info":0,"total":int(high)},
        },
        "vulnerabilities": ({"braces":{
            "severity":"high","nodes":["node_modules/braces"],
            "fixAvailable":False,
            "via":[{"url":"https://github.com/advisories/GHSA-real"}],
        }} if high else {}),
    }


class AgentOfficeNoAllowlistBypassTests(unittest.TestCase):
    def setUp(self):
        self.legacy={"commit":"a"*40,"audit_review":{
            "runtime_reachable_from_br":False,"allowed_high_packages":["braces"],
        }}
        self.lock={"packages":{"node_modules/braces":{"version":"3.0.3"}}}

    def test_stale_review_and_exact_allowlist_never_admit_high(self):
        out=reconcile(audit(),self.legacy,self.lock)
        self.assertEqual("BLOCKED_UNRESOLVED_HIGH",out["status"])
        self.assertTrue(out["historical_waiver_present"])
        self.assertFalse(out["historical_waiver_grants_admission"])
        self.assertEqual(["braces"],out["unresolved_high_packages"])

    def test_clean_upstream_fails_open_only_when_really_clean(self):
        out=reconcile(audit(high=False),self.legacy,self.lock)
        self.assertEqual("PASS_NO_HIGH_CRITICAL",out["status"])
        self.assertFalse(out["execution_authorized"])

    def test_truncated_summary_rejected(self):
        bad=audit()
        bad["metadata"]["vulnerabilities"]["high"]=0
        with self.assertRaises(ValueError):
            reconcile(bad,self.legacy,self.lock)

    def test_unexpected_severity_rejected(self):
        bad=audit()
        bad["vulnerabilities"]["braces"]["severity"]="unknown"
        with self.assertRaises(ValueError):
            reconcile(bad,self.legacy,self.lock)

    def test_path_traversal_vulnerability_node_rejected(self):
        bad=audit()
        bad["vulnerabilities"]["braces"]["nodes"]=["node_modules/../../private"]
        with self.assertRaises(ValueError):
            reconcile(bad,self.legacy,self.lock)


if __name__=="__main__":
    unittest.main()
