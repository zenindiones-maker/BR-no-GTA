import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest

from scripts.br_v24_executor_binding_audit import inspect_binding, check_all


class ExecutorBindingASTTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        module = self.root / "app/services/existing.py"
        module.parent.mkdir(parents=True, exist_ok=True)
        module.write_text("def run():\n    return 3\n\nclass Agent:\n    def process(self):\n        return None\n",
                          encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_existing_real_function_and_class_method(self):
        self.assertEqual("STATIC_SYMBOL_FOUND", inspect_binding(self.root, "app.services.existing.run"))
        self.assertEqual("STATIC_SYMBOL_FOUND", inspect_binding(self.root, "app.services.existing.Agent.process"))

    def test_missing_module_is_not_pass(self):
        self.assertEqual("SOURCE_MODULE_NOT_FOUND", inspect_binding(self.root, "app.services.missing.run"))

    def test_module_only_binding_is_not_falsely_reported_missing(self):
        self.assertEqual(
            "SOURCE_MODULE_ONLY_NOT_CALLABLE",
            inspect_binding(self.root, "app.services.existing"),
        )

    def test_missing_symbol_is_not_pass(self):
        self.assertEqual("STATIC_SYMBOL_NOT_FOUND", inspect_binding(self.root, "app.services.existing.missing"))

    def test_untrusted_non_firstparty_binding_does_not_call_imports(self):
        self.assertEqual("NON_SERVICE_OR_NONPYTHON_BINDING", inspect_binding(self.root, "foreign.package.run"))
        self.assertEqual("UNRESOLVED_BINDING_SYNTAX", inspect_binding(self.root, "something;rm -rf ."))

    def test_all_records_counted_including_misconfigured_executor(self):
        def r(i, binding):
            return SimpleNamespace(capability_id=i, execution_enabled=True, executor_binding=binding)
        records=(r("good","app.services.existing.run"), r("bad","app.services.missing.run"))
        got = check_all(self.root, records)
        self.assertEqual(2,got["declared_executors"])
        self.assertEqual(1,got["binding_status_counts"]["STATIC_SYMBOL_FOUND"])
        self.assertEqual(1,got["binding_status_counts"]["SOURCE_MODULE_NOT_FOUND"])
        self.assertFalse(got["runtime_proven"])


if __name__ == "__main__":
    unittest.main()
