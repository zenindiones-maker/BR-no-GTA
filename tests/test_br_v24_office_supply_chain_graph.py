"""Adversarial first-party tests for npm vendor supply-chain reachability."""
import unittest

from scripts.br_v24_office_supply_chain_graph import (
    _dep_path, production_reachability, high_dependency_paths,
)


def fixture():
    return {"packages":{
        "":{"dependencies":{"web-server":"1","safe-lib":"1"},
            "devDependencies":{"jest":"1"}},
        "node_modules/web-server":{"version":"1","dependencies":{"micromatch":"4"}},
        "node_modules/micromatch":{"version":"4","dependencies":{"braces":"3"}},
        "node_modules/braces":{"version":"3.0.3"},
        "node_modules/safe-lib":{"version":"1"},
        "node_modules/jest":{"version":"1","dependencies":{"test-only":"1"}},
        "node_modules/test-only":{"version":"1"},
    }}


class BRVendorGraphTests(unittest.TestCase):
    def test_production_graph_traces_direct_and_transitive(self):
        report=production_reachability(fixture())
        self.assertEqual([
            "node_modules/web-server",
            "node_modules/micromatch",
            "node_modules/braces",
        ],report["reachable"]["node_modules/braces"])
        self.assertNotIn("node_modules/jest",report["reachable"])

    def test_high_vulnerability_chain_is_evidence_not_approval(self):
        audit={"vulnerabilities":{"braces":{
            "severity":"high","nodes":["node_modules/braces"]}}}
        result=high_dependency_paths(fixture(),audit)
        self.assertEqual("3.0.3",result["high"][0]["nodes"][0]["lock_version"])
        self.assertTrue(result["high"][0]["nodes"][0]["reachable_by_static_production_edges"])
        self.assertFalse(result["source_execution_authorized"])

    def test_nested_hoisting_prefers_local_and_then_ancestor(self):
        packages=fixture()["packages"]
        packages["node_modules/web-server/node_modules/braces"]={"version":"3.0.3"}
        self.assertEqual("node_modules/web-server/node_modules/braces",
            _dep_path("node_modules/web-server","braces",packages))
        self.assertEqual("node_modules/braces",
            _dep_path("node_modules/micromatch","braces",packages))

    def test_invalid_paths_fail_closed(self):
        x=fixture()
        x["packages"]["../escaped"]={"version":"0"}
        with self.assertRaisesRegex(ValueError,"UNTRUSTED_PATH"):
            production_reachability(x)

    def test_missing_audit_data_fails(self):
        with self.assertRaisesRegex(ValueError,"VULNERABILITIES_MISSING"):
            high_dependency_paths(fixture(),{})

    def test_unknown_dependency_does_not_fabricate_reachability(self):
        x=fixture()
        x["packages"]["node_modules/web-server"]["dependencies"]["absent"]="1"
        z=production_reachability(x)
        self.assertEqual(1,len(z["missing"]))


if __name__=="__main__":
    unittest.main()
