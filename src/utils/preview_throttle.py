"""Throttle for OpenCV debug preview windows.

cv2.imshow/waitKey drive the HighGUI message pump on the calling thread and each
waitKey(1) blocks for ~12-15 ms. The tracker loop targets 200 fps (5 ms/frame),
so pumping once per window per frame is what actually caps the pipeline, not the
detection work itself.

These windows are human-visible debug output, so rendering them at ~30 Hz is
indistinguishable while leaving the frame budget to tracking. Each frame renders
all its windows and then pumps exactly once via ``pump()``.
"""

import time

from src.utils.config import config

_DEFAULT_FPS = 30
_last_render = {}
_dirty = False


def _target_fps():
    try:
        return max(1, min(240, int(getattr(config, "opencv_preview_fps", _DEFAULT_FPS))))
    except Exception:
        return _DEFAULT_FPS


def should_render(key: str) -> bool:
    """True when the windowed preview for ``key`` is due for a repaint."""
    interval = 1.0 / _target_fps()
    now = time.perf_counter()
    last = _last_render.get(key)
    if last is not None and (now - last) < interval:
        return False
    _last_render[key] = now
    return True


def mark_shown():
    """Record that at least one window was updated this frame."""
    global _dirty
    _dirty = True


def render_if_due(key: str) -> bool:
    """Combine the throttle decision with dirty bookkeeping."""
    if not should_render(key):
        return False
    mark_shown()
    return True


def pump():
    """Process HighGUI events once for this frame, if anything was drawn."""
    global _dirty
    if not _dirty:
        return
    _dirty = False
    import cv2

    try:
        cv2.waitKey(1)
    except Exception:
        pass


def reset():
    """Forget timing state (called when previews are turned off/reset)."""
    global _dirty
    _last_render.clear()
    _dirty = False
