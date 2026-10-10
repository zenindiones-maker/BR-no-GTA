"""Bounded CPU reference: linear FilmCraft premultiplied RGBA <-> explicit EffectCraft sRGB SDR.

This is NOT a connection to the real ArtCraft renderers. Unsupported HDR,
linear-working-space EffectCraft and unknown color profiles fail closed.
"""
from __future__ import annotations
import math


class ColorContractError(ValueError):
    pass


def _require(px: tuple[float, float, float, float], transfer: str) -> None:
    if transfer != 'srgb':
        raise ColorContractError('UNSUPPORTED_EFFECTCRAFT_TRANSFER')
    if len(px) != 4 or any(not isinstance(x, (int, float)) or not math.isfinite(x) for x in px):
        raise ColorContractError('PIXEL_MUST_BE_FINITE_RGBA')
    r, g, b, a = px
    if not 0.0 <= a <= 1.0:
        raise ColorContractError('ALPHA_OUT_OF_RANGE')
    if any(v < 0.0 or v > a + 1e-7 for v in (r, g, b)):
        raise ColorContractError('EXPECTED_PREMULTIPLIED_SDR')


def linear_to_srgb(v: float) -> float:
    if not 0 <= v <= 1:
        raise ColorContractError('SDR_RANGE_REQUIRED')
    if v in (0, 1):
        return float(v)
    return 12.92 * v if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055


def srgb_to_linear(v: float) -> float:
    if not 0 <= v <= 1:
        raise ColorContractError('SDR_RANGE_REQUIRED')
    if v in (0, 1):
        return float(v)
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def film_to_effect(px: tuple[float, float, float, float], *, effect_transfer: str = 'srgb') -> tuple[float, float, float, float]:
    """Premultiplied linear-light SDR -> explicitly sRGB-encoded premultiplied SDR."""
    _require(px, effect_transfer)
    *rgb, alpha = px
    if alpha == 0:
        return (0.0, 0.0, 0.0, 0.0)
    return (*(linear_to_srgb(min(1, c / alpha)) * alpha for c in rgb), alpha)


def effect_to_film(px: tuple[float, float, float, float], *, effect_transfer: str = 'srgb') -> tuple[float, float, float, float]:
    """Explicit sRGB SDR premultiplied -> FilmCraft linear-light premultiplied SDR."""
    _require(px, effect_transfer)
    *rgb, alpha = px
    if alpha == 0:
        return (0.0, 0.0, 0.0, 0.0)
    return (*(srgb_to_linear(min(1, c / alpha)) * alpha for c in rgb), alpha)
