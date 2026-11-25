"""2-Phase Contrast HSV Solver & Off-Thread Lighting-Drift Guard.

Pure-NumPy / OpenCV helpers for calibrating HSV bounds without affecting the
144Hz detection hot path.
"""

from __future__ import annotations

from typing import Iterable, Optional, Tuple

import cv2
import numpy as np


def solve_contrast_hsv(
    target_hsv_samples: Iterable[Tuple[int, int, int]],
    bg_hsv_samples: Optional[Iterable[Tuple[int, int, int]]] = None,
) -> Tuple[int, int, int, int, int, int]:
    """Compute tight (h_lo, h_hi, s_lo, s_hi, v_lo, v_hi) from target & background samples.

    Maximizes coverage of target HSV samples while trimming S/V lower bounds
    if background samples overlap, preventing wall/sky false positives.
    """
    pts = np.asarray(list(target_hsv_samples), dtype=np.int32)
    if pts.size == 0:
        return (120, 160, 95, 255, 90, 255)
    if pts.ndim == 1:
        pts = pts.reshape(1, 3)

    h_vals = pts[:, 0]
    s_vals = pts[:, 1]
    v_vals = pts[:, 2]

    h_lo = int(max(0, np.percentile(h_vals, 5) - 6))
    h_hi = int(min(179, np.percentile(h_vals, 95) + 6))
    s_lo = int(max(20, np.percentile(s_vals, 10) - 25))
    s_hi = int(min(255, max(s_lo + 20, np.percentile(s_vals, 98) + 30)))
    v_lo = int(max(20, np.percentile(v_vals, 10) - 25))
    v_hi = int(min(255, max(v_lo + 20, np.percentile(v_vals, 98) + 30)))

    if bg_hsv_samples:
        bg = np.asarray(list(bg_hsv_samples), dtype=np.int32)
        if bg.size > 0:
            if bg.ndim == 1:
                bg = bg.reshape(1, 3)
            # Push S/V floor above overlapping background samples that fall inside [h_lo, h_hi]
            in_hue = bg[(bg[:, 0] >= h_lo) & (bg[:, 0] <= h_hi)]
            if in_hue.size > 0:
                bg_s_max = int(np.percentile(in_hue[:, 1], 90))
                bg_v_max = int(np.percentile(in_hue[:, 2], 90))
                target_s_med = int(np.median(s_vals))
                target_v_med = int(np.median(v_vals))
                if bg_s_max + 8 < target_s_med:
                    s_lo = max(s_lo, min(target_s_med - 5, bg_s_max + 8))
                if bg_v_max + 8 < target_v_med:
                    v_lo = max(v_lo, min(target_v_med - 5, bg_v_max + 8))

    h_lo = max(0, min(179, h_lo))
    h_hi = max(h_lo, min(179, h_hi))
    s_lo = max(0, min(255, s_lo))
    s_hi = max(s_lo, min(255, s_hi))
    v_lo = max(0, min(255, v_lo))
    v_hi = max(v_lo, min(255, v_hi))
    return (h_lo, h_hi, s_lo, s_hi, v_lo, v_hi)


def compute_lighting_v_floor(
    bgr_img: np.ndarray,
    base_v_min: int,
    min_floor: int = 60,
    max_floor: int = 140,
) -> int:
    """Compute a gentle V-floor compensation from ambient border brightness.

    Dark indoor scenes lower the V floor slightly to keep thin outlines visible;
    bright outdoor scenes raise it to suppress washed-out glare.
    """
    if bgr_img is None or bgr_img.size == 0:
        return int(base_v_min)
    h, w = bgr_img.shape[:2]
    # Sample top/bottom 8px strips (fast, avoids central target bias)
    strip = np.concatenate(
        [bgr_img[: min(8, h), ::4], bgr_img[max(0, h - 8) :, ::4]],
        axis=0,
    )
    hsv_strip = cv2.cvtColor(strip, cv2.COLOR_BGR2HSV)
    median_v = float(np.median(hsv_strip[:, :, 2]))
    # Neutral ambient ~110 -> 0 offset; dark (<70) -> -15; bright (>170) -> +18
    offset = int(round((median_v - 110.0) * 0.25))
    offset = max(-18, min(20, offset))
    return int(max(min_floor, min(max_floor, int(base_v_min) + offset)))
