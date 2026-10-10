import unittest
from app.services.run001_script_to_screen_contract import verify_script_to_screen, ScreenContractError

class ScriptToScreenTests(unittest.TestCase):
    def setUp(self):
        self.script = {"segments": [{"id":"s1","text":"Vice City","start_ms":0,"end_ms":2000}]}
        self.plan = {"shots":[{"segment_id":"s1","asset_id":"a1","source_ref":"rockstar-official","evidence_ref":"claim-1","visual_purpose":"show Vice City","rights_status":"CLEARED","start_ms":0,"end_ms":2000}]}
    def test_complete_coverage_is_not_render_authorization(self):
        result=verify_script_to_screen(self.script,self.plan)
        self.assertEqual(result["status"],"PASS")
        self.assertFalse(result["render_authorized"])
        self.assertEqual(result["semantic_alignment"],"REQUIRES_INDEPENDENT_PERCEPTUAL_QA")
    def test_missing_visual_interval_fails(self):
        self.plan["shots"][0]["end_ms"]=1000
        with self.assertRaises(ScreenContractError):
            verify_script_to_screen(self.script,self.plan)
    def test_missing_source_fails(self):
        self.plan["shots"][0]["source_ref"]=""
        with self.assertRaises(ScreenContractError):
            verify_script_to_screen(self.script,self.plan)
    def test_uncleared_rights_fails(self):
        self.plan["shots"][0]["rights_status"]="UNKNOWN"
        with self.assertRaises(ScreenContractError):
            verify_script_to_screen(self.script,self.plan)
    def test_duplicate_segment_ids_fail(self):
        self.script["segments"].append(dict(self.script["segments"][0]))
        with self.assertRaises(ScreenContractError):
            verify_script_to_screen(self.script,self.plan)

if __name__ == "__main__":
    unittest.main()
