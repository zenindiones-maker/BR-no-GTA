from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.services.shared_pronunciation_knowledge import (
    SharedPronunciationKnowledgeError,
    load_shared_pronunciation_sources,
    shared_pronunciation_source_by_id,
)


class SharedPronunciationKnowledgeTests(unittest.TestCase):
    def test_canonical_registry_exposes_both_reference_candidates_as_pending(self) -> None:
        payload = load_shared_pronunciation_sources()
        sources = {row["source_id"]: row for row in payload["sources"]}

        self.assertIn("youtube-ptbr-reference-f8IZhKcuEts", sources)
        self.assertIn("youtube-ptbr-reference-K6rVM6gn6k4", sources)
        for source in sources.values():
            self.assertEqual(source["acoustic_analysis_status"], "PENDING")
            self.assertEqual(source["human_pronunciation_approval_status"], "PENDING")

    def test_unknown_source_fails_closed(self) -> None:
        with self.assertRaises(SharedPronunciationKnowledgeError):
            shared_pronunciation_source_by_id("unknown-source")

    def test_duplicate_source_ids_are_rejected(self) -> None:
        payload = {
            "schema": "br-no-gta-shared-pronunciation-sources/v1",
            "version": "test",
            "sources": [
                {"source_id": "same", "url": "https://example.invalid/a", "sha256": "a",
                 "acoustic_analysis_status": "PENDING", "human_pronunciation_approval_status": "PENDING"},
                {"source_id": "same", "url": "https://example.invalid/b", "sha256": "b",
                 "acoustic_analysis_status": "PENDING", "human_pronunciation_approval_status": "PENDING"},
            ],
            "required_pipeline": ["verify_source_identity"],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "registry.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(SharedPronunciationKnowledgeError):
                load_shared_pronunciation_sources(path)


if __name__ == "__main__":
    unittest.main()
