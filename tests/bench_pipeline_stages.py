"""Stage-by-stage latency table for the UDP -> detection -> decision path.

Plan section 3.2 (P0) requires measuring five stages separately instead of one
aggregate number, so a regression can be attributed to a stage. This script
prints that table; it is not a unittest (no ``test_`` prefix on purpose) and is
run by hand:

    python tests/bench_pipeline_stages.py
    python tests/bench_pipeline_stages.py --frames 400 --roi
    python tests/bench_pipeline_stages.py --size 1280

Columns are milliseconds: median, p95 and max per stage, plus the fraction of
sent frames that reached detection.
"""
import argparse
import os
import statistics
import sys
import threading
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import numpy as np


def _percentile(samples, fraction):
    ordered = sorted(samples)
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))
    return ordered[index]


def _row(name, samples, budget_ms):
    if not samples:
        return f"{name:<16} {'-':>9} {'-':>9} {'-':>9}"
    median = statistics.median(samples)
    p95 = _percentile(samples, 0.95)
    worst = max(samples)
    flag = "" if p95 <= budget_ms else "  OVER"
    return f"{name:<16} {median:9.3f} {p95:9.3f} {worst:9.3f}{flag}"


def _encode(size, count):
    import turbojpeg

    tj = turbojpeg.TurboJPEG()
    base = np.zeros((size, size, 3), np.uint8)
    base[:, :] = (26, 26, 26)
    out = []
    for i in range(count):
        img = base.copy()
        x = 20 + (i * 3) % max(1, size - 100)
        y = 30 + (i * 2) % max(1, size - 120)
        img[y:y + 52, x:x + 30] = (163, 69, 161)
        out.append(tj.encode(img))
    return out


def main():
    parser = argparse.ArgumentParser(description="Per-stage latency table")
    parser.add_argument("--frames", type=int, default=200)
    parser.add_argument("--size", type=int, default=640, help="square frame size")
    parser.add_argument("--fps", type=float, default=144.0)
    parser.add_argument("--roi", action="store_true", help="detect on a centre ROI")
    parser.add_argument("--budget-ms", type=float, default=1000.0 / 144.0)
    args = parser.parse_args()

    from src.utils import detection
    from src.capture.OBS_UDP import OBS_UDP_Receiver

    detection.load_model()
    model = detection._model
    if model is None:
        print("HSV model unavailable", file=sys.stderr)
        return 2

    jpegs = _encode(args.size, args.frames)
    receiver = OBS_UDP_Receiver(ip="127.0.0.1", port=13399, target_fps=int(args.fps))
    receiver.is_connected = True
    receiver.stop_event.clear()

    roi = None
    if args.roi:
        half = args.size // 4
        centre = args.size // 2
        roi = (centre - half, centre - half, centre + half, centre + half)

    decode_ms, handoff_ms, detect_ms, total_ms = [], [], [], []
    consumed = [0]
    done = threading.Event()

    worker = threading.Thread(target=receiver._decode_worker_loop, daemon=True)
    worker.start()

    def feed():
        period = 1.0 / args.fps
        start = time.perf_counter()
        for index, jpeg in enumerate(jpegs):
            target = start + index * period
            now = time.perf_counter()
            if target > now:
                time.sleep(target - now)
            receiver._deliver_jpeg(jpeg, time.perf_counter())
        done.set()

    feeder = threading.Thread(target=feed, daemon=True)
    feeder.start()

    last_seq = 0
    idle = 0
    deadline = time.perf_counter() + 120.0
    while time.perf_counter() < deadline:
        frame, seq = receiver.wait_for_new_frame(last_seq, timeout=0.05)
        if frame is None or seq == last_seq:
            if done.is_set():
                idle += 1
                if idle >= 2:
                    break
            continue
        idle = 0
        last_seq = seq

        meta = receiver.get_last_frame_meta()
        published_at = meta.get("published_at")
        t0 = time.perf_counter()
        if published_at is not None:
            handoff_ms.append(max(0.0, (t0 - published_at) * 1000.0))
        decode_ms.append(float(meta.get("decode_ms", 0.0)))
        detection.analyze(model, frame, roi=roi)
        detect_ms.append((time.perf_counter() - t0) * 1000.0)
        if published_at:
            total_ms.append((time.perf_counter() - published_at) * 1000.0)
        consumed[0] += 1
        if consumed[0] >= len(jpegs):
            break

    receiver.stop_event.set()
    worker.join(timeout=2.0)
    feeder.join(timeout=2.0)
    receiver.disconnect()

    print(
        f"frames {args.size}x{args.size}  requested {args.frames}  "
        f"processed {consumed[0]}  target {args.fps:.0f} Hz  "
        f"budget {args.budget_ms:.3f} ms/frame  roi {'on' if roi else 'off'}"
    )
    print(f"{'stage':<16} {'median':>9} {'p95':>9} {'max':>9}")
    print(_row("decode", decode_ms, args.budget_ms))
    print(_row("handoff", handoff_ms, 1.0))
    print(_row("detect", detect_ms, args.budget_ms))
    print(_row("publish->done", total_ms, args.budget_ms))
    ratio = consumed[0] / float(len(jpegs)) if jpegs else 0.0
    print(f"processed ratio  {ratio:.3f}  ({consumed[0]}/{len(jpegs)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
