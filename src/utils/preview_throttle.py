"""Async renderer + throttle for OpenCV debug preview windows.

cv2.imshow/waitKey drive the HighGUI message pump on the calling thread, and
each waitKey(1) blocks for ~2 ms even when timeBeginPeriod(1) is set (~16 ms
without). The tracker loop targets up to 200 fps (5 ms/frame), so pumping
HighGUI on the tracking thread is what actually caps the pipeline: measured,
preview rendering stole whole frames from tracking.

These windows are human-visible debug output, so rendering them at ~30 Hz is
indistinguishable. Frames are submitted from the tracking thread without
copying and land in a single slot per window; one dedicated daemon thread owns
every HighGUI call from then on. Older frames are overwritten rather than
queued, so the preview always shows the newest processed frame and never
replays a backlog.
"""

import threading
import time

from src.utils.config import config

_DEFAULT_FPS = 30
_last_render = {}

# How long the idle render worker sleeps before pumping HighGUI again. Small
# enough to keep the window responding to the OS, large enough to cost nothing.
_IDLE_PUMP_INTERVAL_S = 0.1

# Renderer state. A single condition guards the pending slots and the worker
# lifecycle so enqueue (tracking thread) and paint (worker) never interleave.
_cond = threading.Condition()
# Window name -> submitted image (or _CLOSE). An entry stays here until its
# frame has actually been painted, so a submit arriving while the worker is
# painting replaces it and is counted as a replacement. Clearing the slot at
# claim time made that case invisible: the worker had the frame, the slot looked
# empty, and `overwritten` stayed 0 even though a frame was superseded.
_pending = {}
_created = set()        # windows the renderer has shown at least once
_worker = None
_worker_stop = False
_CLOSE = object()
_stats = {
    "submitted": 0,
    "rendered": 0,
    "pumped": 0,
    "overwritten": 0,
    "closed": 0,
}


def _reset_counters_locked():
    """Zero the per-session counters. Caller holds ``_cond``.

    ``stats()`` describes one renderer session: how many frames *this* worker
    painted out of how many were submitted. Leaving the counters alive across
    ``shutdown()`` made the next session inherit the previous one's paints, so
    a fresh builder that submitted one frame could report eight renders — the
    "the worker is replaying stale frames" symptom, without any backlog.
    """
    for key in _stats:
        _stats[key] = 0


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


def render_if_due(key: str) -> bool:
    """True when window ``key`` is due for a repaint at the preview rate."""
    return should_render(key)


# --- HighGUI calls (all reached from the render worker only) ---

def _cv2_imshow(name, image):
    import cv2

    cv2.imshow(name, image)


def _cv2_wait_key(delay):
    import cv2

    return cv2.waitKey(delay)


def _cv2_destroy(name):
    import cv2

    cv2.destroyWindow(name)


def _ensure_worker_locked():
    """Start the render worker lazily. Caller holds ``_cond``."""
    global _worker, _worker_stop
    if _worker is not None and _worker.is_alive():
        return
    # A new worker is a new render session: its "rendered" counter must count
    # the frames *it* painted. Without this, counters accumulated across every
    # earlier session (tests, a stop/start cycle) and a single submitted frame
    # was reported as several replays.
    _reset_counters_locked()
    _worker_stop = False
    _worker = threading.Thread(target=_render_worker, name="PreviewRender", daemon=True)
    _worker.start()


def _render_worker():
    global _worker
    while True:
        with _cond:
            while not _pending and not _worker_stop:
                # A blocking wait() leaves the Win32 HighGUI message queue
                # unpumped for as long as no new frame is submitted, which is
                # exactly when the user drags/resizes the window and Windows
                # paints it as "Not Responding". Wake up periodically and pump
                # from outside the lock so a caller's imshow() never waits.
                timed_out = not _cond.wait(timeout=_IDLE_PUMP_INTERVAL_S)
                if _pending or _worker_stop:
                    break
                if timed_out and _created:
                    break
            if _worker_stop and not _pending:
                _worker = None
                _cond.notify_all()
                return
            if not _pending:
                # Idle with created windows: pump HighGUI, then loop back.
                batch = []
            else:
                # Snapshot without clearing: an entry must keep occupying its slot
                # until the frame is actually on screen, otherwise a submit that
                # arrives during the paint sees an empty slot and the frame it
                # replaced is never counted. The slot is released per window, under
                # the lock, only when it still holds the frame just painted.
                batch = list(_pending.items())

        if not batch:
            # Never hold _cond while calling into OpenCV: imshow() from the
            # tracking thread must stay non-blocking.
            try:
                _cv2_wait_key(1)
                with _cond:
                    _stats["pumped"] += 1
            except Exception:
                pass
            continue

        drew = False
        for name, image in batch:
            if image is _CLOSE:
                with _cond:
                    was_created = name in _created
                    if _pending.get(name) is _CLOSE:
                        _pending.pop(name, None)
                    _created.discard(name)
                    if was_created:
                        _stats["closed"] += 1
                    _cond.notify_all()
                if was_created:
                    try:
                        _cv2_destroy(name)
                    except Exception:
                        pass
                continue

            # Count the paint before blocking in OpenCV. The frame is already
            # committed to this worker at this point, and a stats() reader must
            # not see "0 painted" after the image is visibly on screen: the
            # high-frequency caller checks the first paint and reads the counter
            # immediately, so incrementing after imshow() returns left a window
            # in which a real paint looked like no paint at all. A failed paint
            # is rolled back below.
            with _cond:
                _stats["rendered"] += 1

            painted = False
            try:
                _cv2_imshow(name, image)
                painted = True
            except Exception:
                painted = False
            finally:
                with _cond:
                    if not painted:
                        # Clamp: a session reset (shutdown/reset) may have zeroed
                        # the counter between the optimistic bump and this
                        # rollback, and a negative paint count is meaningless.
                        _stats["rendered"] = max(0, _stats["rendered"] - 1)
                    # Only release the slot if it still holds this frame: a
                    # newer submit that landed meanwhile must stay queued.
                    if _pending.get(name) is image:
                        _pending.pop(name, None)
                    if painted:
                        _created.add(name)
                    _cond.notify_all()
            if painted:
                drew = True

        # One pump per batch: waitKey also lets HighGUI repaint every window.
        if drew:
            try:
                _cv2_wait_key(1)
                with _cond:
                    _stats["pumped"] += 1
            except Exception:
                pass


def imshow(name: str, image):
    """Queue ``image`` for window ``name`` without blocking (no copy).

    The caller must not modify ``image`` after submitting it. If a frame for
    the same window is still pending, it is replaced: the worker only ever
    paints the newest frame.
    """
    if image is None:
        return
    with _cond:
        _ensure_worker_locked()
        # A frame still queued or still being painted by the worker is
        # superseded by this newer one. Counting only the queued slot is what
        # made `overwritten` stay 0 at 144 Hz: the worker pops the slot, then
        # paints for 16 ms, and every submit during that paint replaced a frame
        # nobody had counted.
        if name in _pending:
            _stats["overwritten"] += 1
        _pending[name] = image
        _stats["submitted"] += 1
        _cond.notify()


def destroy(name: str):
    """Queue closing the window ``name`` (ignored when it was never shown)."""
    with _cond:
        _ensure_worker_locked()
        pending = _pending.get(name)
        if pending is _CLOSE:
            return
        if pending is None and name not in _created:
            return
        _pending.pop(name, None)
        _pending[name] = _CLOSE
        _cond.notify()


def shutdown(timeout: float = 2.0):
    """Flush pending frames, close windows created here and join the worker.

    A later ``imshow`` restarts the worker, so a harness that calls
    ``tracker.stop()`` and keeps tracking still gets previews.
    """
    global _worker, _worker_stop
    with _cond:
        worker = _worker
        if worker is None:
            created = list(_created)
            _created.clear()
            _pending.clear()
            _reset_counters_locked()
        else:
            _worker_stop = True
            _cond.notify_all()

    if worker is not None:
        worker.join(timeout)
        with _cond:
            if worker.is_alive():
                # Still draining: it owns HighGUI until it exits, so leave the
                # window teardown to the caller's destroyAllWindows().
                return
            if _worker is worker:
                _worker = None
            _worker_stop = False
            created = list(_created)
            _created.clear()
            _pending.clear()
            # The session is over: report no paints rather than leaving the
            # finished worker's totals to be mistaken for the next one's.
            _reset_counters_locked()

    for name in created:
        try:
            _cv2_destroy(name)
        except Exception:
            pass


def stats() -> dict:
    """Snapshot of renderer counters (used by tests and diagnostics)."""
    with _cond:
        snapshot = dict(_stats)
        snapshot["pending"] = len(_pending)
        snapshot["worker_alive"] = bool(_worker is not None and _worker.is_alive())
    return snapshot


def reset():
    """Forget timing state (called when previews are turned off/reset)."""
    _last_render.clear()
    with _cond:
        _reset_counters_locked()
