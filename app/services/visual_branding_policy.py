from __future__ import annotations

from typing import Any

WATERMARK_WIDTH_FRACTION = 0.16
WATERMARK_OPACITY = 0.78
WATERMARK_MARGIN_X_FRACTION = 0.025
WATERMARK_MARGIN_Y_FRACTION = 0.04


def watermark_geometry(
    *,
    canvas_width: int,
    canvas_height: int,
    source_width: int,
    source_height: int,
) -> dict[str, Any]:
    if min(canvas_width, canvas_height, source_width, source_height) <= 0:
        raise ValueError("watermark geometry requires positive dimensions")
    target_width = max(64, int(round(canvas_width * WATERMARK_WIDTH_FRACTION)))
    scale = target_width / float(source_width)
    target_height = source_height * scale
    margin_x = max(16, int(round(canvas_width * WATERMARK_MARGIN_X_FRACTION)))
    margin_y = max(16, int(round(canvas_height * WATERMARK_MARGIN_Y_FRACTION)))
    return {
        "scale": scale,
        "opacity": WATERMARK_OPACITY,
        "target_width": target_width,
        "target_height": target_height,
        "margin_x": margin_x,
        "margin_y": margin_y,
        "x_offset_from_center": (canvas_width - target_width) / 2.0 - margin_x,
        "y_offset_from_center": (canvas_height - target_height) / 2.0 - margin_y,
        "position": "BOTTOM_RIGHT",
    }
