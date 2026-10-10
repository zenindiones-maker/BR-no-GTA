"""CPU color oracle tests, not evidence of native Film/Effect executable output."""
import math
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import artcraft_color_reference_bridge as cb


class ReferenceColor(unittest.TestCase):
    def test_transfer_srgb_midgray(self):
        self.assertAlmostEqual(cb.linear_to_srgb(0.21404114048223255), 0.5, places=8)
        self.assertAlmostEqual(cb.srgb_to_linear(0.5), 0.21404114048223255, places=8)

    def test_alpha_half_roundtrip(self):
        linear = (0.21404114048223255 * 0.5, 0.08, 0.0, 0.5)
        effect = cb.film_to_effect(linear)
        self.assertAlmostEqual(effect[0], 0.25, places=8)
        for actual, expected in zip(cb.effect_to_film(effect), linear):
            self.assertAlmostEqual(actual, expected, places=8)

    def test_transparent_is_zero(self):
        self.assertEqual(cb.film_to_effect((0, 0, 0, 0)), (0, 0, 0, 0))
        self.assertEqual(cb.effect_to_film((0, 0, 0, 0)), (0, 0, 0, 0))

    def test_opaque_primary_is_stable(self):
        self.assertEqual(cb.film_to_effect((1, 0, 0, 1)), (1, 0, 0, 1))
        self.assertEqual(cb.effect_to_film((0, 1, 0, 1)), (0, 1, 0, 1))

    def test_nonpremul_or_hdr_rejected(self):
        invalid = [(0.7, 0, 0, 0.4), (-0.1, 0, 0, 1), (2, 0, 0, 1),
                   (0, 0, 0, -0.2), (0, 0, 0, 1.5), (math.nan, 0, 0, 1),
                   (math.inf, 0, 0, 1)]
        for px in invalid:
            with self.subTest(px=px), self.assertRaises(cb.ColorContractError):
                cb.film_to_effect(px)

    def test_unknown_effect_color_space_blocked(self):
        for transfer in ('linear', 'acescg', 'rec2020', 'unknown'):
            with self.subTest(transfer=transfer), self.assertRaises(cb.ColorContractError):
                cb.effect_to_film((0.1, 0.2, 0.3, 1.0), effect_transfer=transfer)


if __name__ == '__main__':
    unittest.main()
