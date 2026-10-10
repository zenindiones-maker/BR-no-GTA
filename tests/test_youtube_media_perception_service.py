import unittest
from app.services.youtube_media_perception_service import (
    parse_youtube_video_id, build_perception_manifest, classify_acquisition_error,
)

class YouTubeMediaPerceptionTests(unittest.TestCase):
    def test_video_urls_and_ids(self):
        self.assertEqual(parse_youtube_video_id("https://www.youtube.com/watch?v=f8IZhKcuEts"), "f8IZhKcuEts")
        self.assertEqual(parse_youtube_video_id("https://youtu.be/K6rVM6gn6k4"), "K6rVM6gn6k4")
        self.assertEqual(parse_youtube_video_id("K6rVM6gn6k4"), "K6rVM6gn6k4")
    def test_rejects_non_youtube_or_injection(self):
        for url in ("https://evil.test/watch?v=f8IZhKcuEts", "https://youtube.com.evil.test/watch?v=f8IZhKcuEts", "bad;rm -rf /", "https://youtu.be/invalid"):
            with self.assertRaises(ValueError):
                parse_youtube_video_id(url)
    def test_manifest_separates_playback_from_perception(self):
        manifest = build_perception_manifest("https://youtu.be/f8IZhKcuEts")
        self.assertEqual(manifest["playback"]["method"], "youtube-iframe")
        self.assertEqual(manifest["audio_perception"]["status"], "NOT_OBSERVED")
        self.assertFalse(manifest["audio_perception"]["lexicon_activation"])
    def test_diagnostics_are_typed(self):
        self.assertEqual(classify_acquisition_error("HTTP Error 403: Forbidden"), "ACCESS_DENIED")
        self.assertEqual(classify_acquisition_error("Temporary failure in name resolution"), "NETWORK_DNS")
        self.assertEqual(classify_acquisition_error("PO Token required"), "PLAYBACK_TOKEN_REQUIRED")
