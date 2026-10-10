import ast
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
DISPATCH = ROOT / "scripts/run001_final_product_dispatch.py"

class DispatchScreenGateTests(unittest.TestCase):
    def test_dispatch_requires_screen_coverage_before_application_initialization(self):
        tree = ast.parse(DISPATCH.read_text(encoding="utf-8"))
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "build_render_job")
        calls = [n.func.id for n in ast.walk(function) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
        self.assertIn("verify_script_to_screen", calls)
        self.assertIn("initialize_application", calls)
        body = ast.get_source_segment(DISPATCH.read_text(encoding="utf-8"), function)
        self.assertLess(body.index("verify_script_to_screen("), body.index("initialize_application("))
    def test_dispatch_does_not_print_unsupported_research_pass(self):
        src = DISPATCH.read_text(encoding="utf-8")
        self.assertNotIn('_RESEARCH=PASS', src)
        self.assertNotIn('_FACT_CHECK=PASS', src)
        self.assertIn('_SEMANTIC_QA=PENDING', src)

if __name__ == "__main__":
    unittest.main()
