"""REA V4/V24 first-party source comparison; no REA execution."""
from pathlib import Path
import tempfile
import unittest
from scripts.br_v24_rea_cross_branch_compatibility import compare, FILES, _source


class NativeREACompatibilityTests(unittest.TestCase):
    def test_manifest_only_br_native_sources(self):
        self.assertEqual(len(FILES),len(set(FILES)))
        self.assertTrue(all(s.startswith(("app/services/reverse_engineering_", "scripts/br_reverse_engineering_", "tests/test_reverse_engineering_")) for s in FILES))
        self.assertFalse(any("hazewave" in s.lower() for s in FILES))

    def test_identical_changed_and_missing_are_distinct(self):
        with tempfile.TemporaryDirectory() as t:
            base=Path(t)
            v4=base/"v4"
            v24=base/"v24"
            v4.mkdir();v24.mkdir()
            for name in FILES:
                p=v4/name
                p.parent.mkdir(parents=True,exist_ok=True)
                p.write_text("def native():\n    return 'real'\n",encoding="utf-8")
            for name in FILES[:2]:
                p=v24/name
                p.parent.mkdir(parents=True,exist_ok=True)
                p.write_text("def native():\n    return 'real'\n",encoding="utf-8")
            change=v24/FILES[1]
            change.write_text("def native():\n    return 'changed'\n",encoding="utf-8")
            receipt=compare(v4,v24)
            self.assertEqual(1,receipt["status_counts"]["IDENTICAL_IN_V24"])
            self.assertEqual(1,receipt["status_counts"]["DIFF_REVIEW_REQUIRED"])
            self.assertEqual(len(FILES)-2,receipt["status_counts"]["HISTORICAL_ONLY_NOT_IN_V24"])
            self.assertFalse(receipt["source_reintroduced"])
            self.assertFalse(receipt["runtime_invoked"])

    def test_symlink_not_read_as_firstparty_source(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            external=root/"private.txt"
            external.write_text("sensitive")
            link=root/"app/services/reverse_engineering_foo.py"
            link.parent.mkdir(parents=True)
            link.symlink_to(external)
            self.assertFalse(_source(link,root)["present"])

    def test_no_code_executed_during_ast(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            src=root/"app/services/reverse_engineering_harness_service.py"
            src.parent.mkdir(parents=True)
            sentinel=root/"sentinel"
            src.write_text(
                f"from pathlib import Path\nPath({str(sentinel)!r}).write_text('bad')\ndef native(): pass\n",
                encoding="utf-8",
            )
            record=_source(src,root)
            self.assertTrue(record["present"])
            self.assertIn("native",record["public_top_level_symbols"])
            self.assertFalse(sentinel.exists())


if __name__ == "__main__":
    unittest.main()
