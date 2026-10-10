import unittest
from app.services.run001_editorial_candidate_selection import select_shots, CandidateSelectionError
from app.services.run001_script_to_screen_contract import verify_script_to_screen

class CandidateSelectionTests(unittest.TestCase):
    def setUp(self):
        self.script={"segments":[{"id":"s1","text":"Vice City","start_ms":0,"end_ms":1000}]}
        self.candidates=[{"segment_id":"s1","asset_id":"a1","source_ref":"official","evidence_ref":"claim-1","visual_purpose":"show Vice City","rights_status":"CLEARED","evidence_status":"VERIFIED","semantic_verdict":"ACCEPT","reviewer_id":"reviewer-1","asset_kind":"video","source_in_ms":250}]
    def test_approved_unique_candidate_produces_covered_plan_without_release(self):
        plan=select_shots(self.script,self.candidates)
        self.assertEqual(plan["shots"][0]["source_in_ms"],250)
        self.assertEqual(verify_script_to_screen(self.script,plan)["status"],"PASS")
        self.assertFalse(plan["render_authorized"])
    def test_unknown_rights_rejected(self):
        self.candidates[0]["rights_status"]="UNKNOWN"
        with self.assertRaises(CandidateSelectionError):
            select_shots(self.script,self.candidates)
    def test_unverified_evidence_rejected(self):
        self.candidates[0]["evidence_status"]="PENDING"
        with self.assertRaises(CandidateSelectionError):
            select_shots(self.script,self.candidates)
    def test_missing_semantic_review_rejected(self):
        self.candidates[0]["semantic_verdict"]="PENDING"
        with self.assertRaises(CandidateSelectionError):
            select_shots(self.script,self.candidates)
    def test_ambiguous_candidate_rejected(self):
        self.candidates.append(dict(self.candidates[0],asset_id="a2"))
        with self.assertRaises(CandidateSelectionError):
            select_shots(self.script,self.candidates)

if __name__=="__main__":
    unittest.main()
