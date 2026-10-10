"""Synthetic media and fail-closed FilmCraft/EffectCraft adapter contracts.

Mock CLIs validate argument construction only, never upstream runtime parity.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import artcraft_film_effect_interop as bridge
from artcraft_make_synthetic_interop_fixtures import generate


def fake_pinned_manifest() -> dict:
    names = ['photocraft', 'vectorcraft', 'filmcraft', 'lightcraft', 'pdfcraft', 'effectcraft', 'designcraft']
    return {'schema': 'BRArtCraftPinnedSourceStudy/v1', 'projects': [
        {'name': n, 'repository': 'storytold/' + n,
         'commit_sha': bridge.ALLOWED.get(n, 'a' * 40)} for n in names]}


class TestInterop(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='artcraft-interop-')
        cls.root = Path(cls.tmp.name)
        cls.fixtures = cls.root / 'synthetic'
        generate(cls.fixtures)
        cls.manifest = cls.root / 'pinned.json'
        cls.manifest.write_text(json.dumps(fake_pinned_manifest()))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_manifest_exact_sha_accepts(self):
        self.assertEqual(len(bridge.check_manifest(self.manifest)['projects']), 7)

    def test_manifest_wrong_sha_denied(self):
        f = fake_pinned_manifest()
        f['projects'][2]['commit_sha'] = 'b' * 40
        p = self.root / 'wrong.json'
        p.write_text(json.dumps(f))
        with self.assertRaisesRegex(bridge.BoundaryError, 'PINNED_SOURCE_MISMATCH'):
            bridge.check_manifest(p)

    def test_ticks_exact_both_engines(self):
        self.assertEqual(bridge.TICKS_PER_SECOND, 254_016_000_000)
        self.assertEqual(bridge.ticks_for_frame(1), 8_467_200_000)
        self.assertEqual(bridge.ticks_for_frame(150), bridge.TICKS_PER_SECOND * 5)
        self.assertEqual(bridge.ticks_for_frame(1, 30000, 1001), 8_475_667_200)

    def test_invalid_rates_denied(self):
        for values in [(-1, 30, 1), (1, 0, 1), (1, 30, 0), (1, 29, 1), (True, 30, 1)]:
            with self.subTest(values=values), self.assertRaises(bridge.BoundaryError):
                bridge.ticks_for_frame(*values)

    def test_real_synthetic_5s_decodes_150_frames(self):
        p = bridge.check_fixture_pack(self.fixtures)
        self.assertEqual(p['integrity'], 'PASS')
        self.assertEqual(p['files'], 9)
        self.assertEqual(p['profile']['frames'], 150)
        self.assertEqual(p['profile']['last_frame_tick'], bridge.ticks_for_frame(149))

    def test_corrupted_fixture_fails(self):
        victim = self.fixtures / 'frame_00.png'
        original = victim.read_bytes()
        try:
            victim.write_bytes(original[:-1] + bytes([original[-1] ^ 5]))
            with self.assertRaisesRegex(bridge.BoundaryError, 'FIXTURE_HASH_MISMATCH'):
                bridge.check_fixture_pack(self.fixtures)
        finally:
            victim.write_bytes(original)

    def test_manifest_extra_file_not_masked(self):
        doc = json.loads((self.fixtures / 'MANIFEST.json').read_text())
        doc['files'].append(dict(doc['files'][0]))
        bad = self.root / 'bad-nine'
        bad.mkdir(exist_ok=True)
        (bad / 'MANIFEST.json').write_text(json.dumps(doc))
        with self.assertRaisesRegex(bridge.BoundaryError, 'FIXTURE_FILES_INCOMPLETE'):
            bridge.check_fixture_pack(bad)

    def test_output_png_checks(self):
        p = bridge.check_png(self.fixtures / 'frame_00.png')
        self.assertEqual((p['width'], p['height']), (320, 180))
        self.assertEqual(len(p['sha256']), 64)

    def test_corrupt_png_denied(self):
        f = self.root / 'not.png'
        f.write_bytes(b'A' * 60)
        with self.assertRaisesRegex(bridge.BoundaryError, 'RENDER_NOT_PNG'):
            bridge.check_png(f)

    def test_symlink_traversal_denied(self):
        s = self.fixtures / 'fake_test.png'
        try:
            s.symlink_to(self.root / 'not.png')
            with self.assertRaisesRegex(bridge.BoundaryError, 'FIXTURE_NOT_REGULAR_FILE'):
                bridge.safe_fixture(s, self.fixtures)
        finally:
            s.unlink(missing_ok=True)

    def test_binary_mismatch_denied(self):
        b = self.root / 'dummy-cli'
        b.write_text('#!/bin/sh\nexit 0\n')
        b.chmod(0o700)
        with self.assertRaisesRegex(bridge.BoundaryError, 'BINARY_DIGEST_MISMATCH'):
            bridge.verify_binary(b, '0' * 64)

    def test_cli_rejects_nonzero(self):
        with self.assertRaisesRegex(bridge.BoundaryError, 'CHILD_PROCESS_EXIT_NONZERO'):
            bridge.run([sys.executable, '-c', 'raise SystemExit(42)'], cwd=self.root, timeout=1)

    def test_no_binaries_is_baseline_only_not_native_pass(self):
        receipt = self.root / 'receipt.json'
        result = bridge.main(['--manifest', str(self.manifest), '--fixtures', str(self.fixtures),
                              '--receipt', str(receipt)])
        p = json.loads(receipt.read_text())
        self.assertEqual(result, 0)
        self.assertEqual(p['gate'], 'BASELINE_ONLY')
        self.assertIs(p['native_executed'], False)
        self.assertIs(p['production_approved'], False)

    def test_native_without_attestations_fails_closed(self):
        receipt = self.root / 'failed-receipt.json'
        result = bridge.main(['--manifest', str(self.manifest), '--fixtures', str(self.fixtures),
                              '--receipt', str(receipt), '--native'])
        self.assertEqual(result, 1)
        self.assertEqual(json.loads(receipt.read_text())['gate'], 'FAIL')

    def test_standin_cli_only_proves_wrapper_contract(self):
        # These stand-ins copy frames and are NOT upstream FilmCraft/EffectCraft.
        binpaths = []
        for name in ('filmcraft', 'effectcraft'):
            p = self.root / ('mock-' + name)
            frame = self.fixtures / 'frame_00.png'
            p.write_text(f'#!{sys.executable}\nimport shutil,sys\na=sys.argv\n'
                         f'assert ("render-frame" in a) == {name == "effectcraft"}\n'
                         f'assert "mcp" not in a and "script" not in a\n'
                         f'shutil.copyfile({str(frame)!r}, a[a.index("--out")+1])\n')
            p.chmod(0o700)
            binpaths.append(p)
        output = self.root / 'dry-mock'
        result = bridge.cli_frame_probes(binpaths[0], binpaths[1],
                                         bridge.sha256(binpaths[0]), bridge.sha256(binpaths[1]), output)
        self.assertEqual(result['native_execution'], 'PASS')
        self.assertEqual(result['filmcraft']['frame']['width'], 320)
        self.assertEqual(result['effectcraft']['frame']['height'], 180)
        self.assertNotIn('production_approved', result)


if __name__ == '__main__':
    unittest.main()
