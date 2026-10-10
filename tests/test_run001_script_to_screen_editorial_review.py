import unittest
from app.services.run001_script_to_screen_editorial_review import verify_independent_editorial_review, EditorialReviewError

class EditorialReviewTests(unittest.TestCase):
    def setUp(self):
        self.evidence={"schema":"BRScriptToScreenFrameEvidence/v1","master_sha256":"a"*64,"frames":[{"segment_id":"s1","frame_sha256":"b"*64,"visual_purpose":"show Vice City skyline","evidence_ref":"official-trailer-1"}]}
        self.review={"schema":"BRScriptToScreenEditorialReview/v1","master_sha256":"a"*64,"reviewer_id":"independent-reviewer","decisions":[{"segment_id":"s1","frame_sha256":"b"*64,"visual_purpose":"show Vice City skyline","evidence_ref":"official-trailer-1","verdict":"ACCEPT","reason":"Visible scene depicts the cited skyline."}]}
    def test_complete_review_is_not_release_permission(self):
        r=verify_independent_editorial_review(self.evidence,self.review)
        self.assertEqual(r["status"],"REVIEW_RECORD_COMPLETE")
        self.assertFalse(r["release_authorized"])
        self.assertEqual(r["review_authenticity"],"NOT_INDEPENDENTLY_ATTESTED")
    def test_mismatched_master_fails(self):
        self.review["master_sha256"]="c"*64
        with self.assertRaises(EditorialReviewError):
            verify_independent_editorial_review(self.evidence,self.review)
    def test_unreviewed_frame_fails(self):
        self.review["decisions"]=[]
        with self.assertRaises(EditorialReviewError):
            verify_independent_editorial_review(self.evidence,self.review)
    def test_rejected_visual_fails(self):
        self.review["decisions"][0]["verdict"]="REJECT"
        with self.assertRaises(EditorialReviewError):
            verify_independent_editorial_review(self.evidence,self.review)
    def test_wrong_evidence_reference_fails(self):
        self.review["decisions"][0]["evidence_ref"]="other"
        with self.assertRaises(EditorialReviewError):
            verify_independent_editorial_review(self.evidence,self.review)

if __name__=="__main__":
    unittest.main()
