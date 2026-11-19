import threading
import queue
import time
import math
import numpy as np
import cv2
import ctypes
import sys
import os

# 瑷疆 AppUserModelID 浠ヤ究鍦?Windows 浠诲嫏娆勬纰洪’绀哄湒妯?
try:
    myappid = 'mycompany.colorbot.v2.0' # 浠绘剰鍞竴鐨勫瓧绗︿覆
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
except Exception:
    pass

from src.utils.config import config
from src.utils.debug_logger import log_print
from src.utils.mouse import Mouse, is_button_pressed
from src.utils.activation import get_active_aim_fov, get_active_trigger_fov
from src.utils.detection import load_model, analyze
from src.utils.ai_detection import TARGET_CLASS_NAMES
from src.capture.capture_service import CaptureService
from src.aim_system.normal import process_normal_mode
from src.aim_system.anti_smoke_detector import AntiSmokeDetector
from src.aim_system.target_smoother import TargetSmoother
from src.utils import preview_throttle

HEAD_CLASS_NAME = "head"
BODY_CLASS_NAMES = frozenset(TARGET_CLASS_NAMES - {HEAD_CLASS_NAME})

# A distant head is only a handful of pixels across: a 5x5 box is 25 px² and is
# a real target, while a 5x5 ``body`` is noise. ``head`` therefore gets its own
# floor instead of the body-sized ``min_bbox_area`` (40-100 px² on a 320x320
# frame), which used to delete every small head before it could become a target.
HEAD_MIN_BBOX_AREA = 9


def _set_pixel(img, x, y, color):
    """Paint exactly one pixel, clipped to the image.

    ``cv2.circle(..., radius=0, ...)`` is the idiomatic way to draw a single
    pixel, but the guarantee that a zero radius still marks the centre has
    varied between OpenCV builds. Assigning the pixel directly keeps the compact
    marker reproducible and cannot raise when the point is on the frame edge.
    """
    try:
        xi, yi = int(x), int(y)
        if 0 <= yi < img.shape[0] and 0 <= xi < img.shape[1]:
            img[yi, xi] = color
    except Exception:
        pass


class FrameInfo:
    """绨″柈鐨勫箑淇℃伅椤烇紝鐢ㄦ柤鍏煎鐝炬湁浠ｇ⒓"""
    def __init__(self, width, height):
        self.xres = width
        self.yres = height


def _pacing_deadline(next_at, now, period):
    """Return the absolute deadline to pace against for the next iteration.

    Resyncs to ``now`` when the previous iteration overran by more than one
    period (slow work must not build a backlog of missed deadlines) or when the
    deadline is further out than one period (target_fps was just raised).
    """
    if next_at < now - period or next_at > now + period:
        return now
    return next_at


def min_aim_bbox_area(frame_w, frame_h):
    """Minimum bbox area (px²) a **body** detection must have to become a target.

    Legacy morphology keeps the stricter configured floor, while the stable
    mode allows smaller boxes; both scale with the frame area.

    This is the body/player/enemy floor. A ``head`` box is filtered by its own
    floor (``HEAD_MIN_BBOX_AREA``) instead, so a distant small head is not
    discarded by a threshold tuned to reject body-sized noise.
    """
    frame_area = max(1, int(frame_w) * int(frame_h))
    min_area = int(
        getattr(config, "min_detection_bbox_area", max(120, int(frame_area * 0.0015)))
    )
    morph_mode = str(getattr(config, "detection_morph_mode", "legacy")).strip().lower()
    if morph_mode != "stable":
        min_area = min(min_area, max(40, int(frame_area * 0.00035)))
    return min_area


def _head_matches_body(body_box, head_box, pad_ratio=0.15):
    """True when ``head_box`` is the head of the player detected in ``body_box``.

    Two export flavours exist and both must pair:

    * ``body`` includes the head: the head box is *inside* the body box (the
      original case, matched by the centre-in-body test).
    * ``body`` is the torso only: the head box sits *on top of* the body box,
      its bottom edge roughly level with (or slightly above) the body's top
      edge. A centre test rejects this pair, which used to emit two targets for
      one player -- the real head and the 22 % estimate inside the chest.

    The test is therefore "over the body horizontally, and either inside it or
    directly above its top edge". Horizontal padding keeps a slightly
    off-centre head attached; the vertical slacks are proportional to the body
    height so the rule scales with distance from the camera.
    """
    bx, by, bw, bh = body_box
    hx, hy, hw, hh = head_box
    if bw <= 0 or bh <= 0 or hw <= 0 or hh <= 0:
        return False

    head_cx = hx + hw / 2.0
    head_top = float(hy)
    head_bottom = float(hy + hh)
    pad_x = max(2.0, bw * pad_ratio)
    if not (bx - pad_x <= head_cx <= bx + bw + pad_x):
        return False

    # How far above the body top a head may float and still belong to it.
    top_slack = max(4.0, bh * 0.35)
    if head_bottom < by - top_slack:
        return False
    # A head whose top edge starts below most of the body is not this body's
    # head (it is another player behind/below, or a mis-detection).
    if head_top > by + bh * 0.5:
        return False
    return True


def build_aim_targets(detections, aim_type, frame_w, frame_h, min_bbox_area,
                      estimate_head_positions=None):
    """Turn detection dicts into the tracker's aim targets.

    Detections may carry a dedicated ``head`` class (the ONNX model exports
    ``body``/``head`` as separate boxes). A head box that belongs to a body box
    becomes that player's aim point *as-is*: re-estimating a head inside the
    body (the 22 % heuristic) would be both redundant and wrong, and emitting a
    body target as well would give the aimer two points for one player.

    A body box with no matching head box (or any body box when the model
    exports no head class at all, as in HSV mode) still falls back to
    ``estimate_head_positions``. ``body``/``enemy``/``player`` boxes are aimed
    at directly for ``aim_type == "body"``.

    ``min_bbox_area`` is the floor for ``body``-class boxes only; ``head`` boxes
    use ``min(HEAD_MIN_BBOX_AREA, min_bbox_area)`` so a distant few-pixel head
    is not deleted by a threshold tuned against body-sized noise.

    ``estimate_head_positions`` is a callable ``(x1, y1, x2, y2) -> [(cx, cy,
    rect), ...]``; without it no head is estimated.

    Returns ``(targets, target_bboxes, body_overlays, head_overlays,
    head_rects)`` where ``targets`` entries are
    ``(cx, cy, distance, head_y_min, body_y_max)``.
    """
    targets = []
    target_bboxes = []
    body_overlays = []
    head_overlays = []
    head_rects = []

    body_dets = []
    head_dets = []
    body_floor = int(min_bbox_area)
    # ``head`` keeps its own (much lower) floor, but never a stricter one than
    # the caller asked for: with ``min_bbox_area=1`` (real-model tests) the
    # behaviour is byte-identical to before.
    head_floor = min(HEAD_MIN_BBOX_AREA, body_floor)
    for det in detections or []:
        try:
            x, y, w, h = [int(round(float(v))) for v in det["bbox"][:4]]
        except Exception:
            continue
        if w <= 0 or h <= 0:
            continue
        conf = float(det.get("confidence", 1.0))
        name = str(det.get("class", "player")).strip().lower()
        # The class must be read *before* the area test: a single shared floor
        # cannot tell a far-away head from a body-sized noise blob.
        if name == HEAD_CLASS_NAME:
            # Ignore tiny head blobs, but well below the body floor.
            if w * h < head_floor:
                continue
            head_dets.append((x, y, w, h, conf))
        elif name in BODY_CLASS_NAMES:
            # Ignore tiny body blobs to reduce per-frame target flicker.
            if w * h < body_floor:
                continue
            body_dets.append((x, y, w, h, conf))
        # Anything else (teammate, breakable, dodge, ...) is not a target.

    center_x = float(frame_w) / 2.0
    center_y = float(frame_h) / 2.0

    for x, y, w, h, conf in body_dets:
        body_overlays.append((x, y, x + w, y + h, conf))

    if aim_type == "body":
        # Body mode aims at whatever body box exists; a lone head box is still
        # a better target than none.
        for x, y, w, h, _conf in (body_dets or head_dets):
            cx = x + w / 2.0
            cy = y + h / 2.0
            d = math.hypot(cx - center_x, cy - center_y)
            targets.append((cx, cy, d, None, None))
            target_bboxes.append(((cx, cy), (x, y, w, h)))
        return targets, target_bboxes, body_overlays, head_overlays, head_rects

    def _add_head(head, anchor_body):
        x, y, w, h, _conf = head
        cx = x + w / 2.0
        cy = y + h / 2.0
        d = math.hypot(cx - center_x, cy - center_y)
        head_overlays.append((int(round(cx)), int(round(cy))))
        head_rects.append((x, y, x + w, y + h))
        if aim_type == "nearest":
            body_y_max = (
                anchor_body[1] + anchor_body[3] if anchor_body is not None else y + h
            )
            target = (cx, cy, d, y, body_y_max)
        else:
            target = (cx, cy, d, None, None)
        targets.append(target)
        # Anti-smoke keeps checking the body area around the head box.
        anchor = anchor_body if anchor_body is not None else (x, y, w, h)
        target_bboxes.append(((cx, cy), anchor))

    remaining_heads = list(head_dets)
    bodies_needing_estimate = []
    for body in body_dets:
        box = body[:4]
        matched = [head for head in remaining_heads if _head_matches_body(box, head[:4])]
        if not matched:
            # No head left to pair: estimate one, unless this body is a second
            # box for a player whose head another body already claimed (that
            # would emit a duplicate target).
            if not any(_head_matches_body(box, head[:4]) for head in head_dets):
                bodies_needing_estimate.append(body)
            continue
        for head in matched:
            remaining_heads.remove(head)
            _add_head(head, box)

    # Heads the model placed outside any body box are players on their own.
    for head in remaining_heads:
        _add_head(head, None)

    if estimate_head_positions is None:
        return targets, target_bboxes, body_overlays, head_overlays, head_rects

    for x, y, w, h, _conf in bodies_needing_estimate:
        x1, y1, x2, y2 = x, y, x + w, y + h
        try:
            head_positions = estimate_head_positions(x1, y1, x2, y2)
        except Exception as e:
            log_print(f"[Track] head estimation failed for bbox {(x1, y1, x2, y2)}: {e}")
            continue
        for head_cx, head_cy, bbox in head_positions:
            head_overlays.append((head_cx, head_cy))
            head_rects.append(bbox)
            d = math.hypot(head_cx - center_x, head_cy - center_y)
            if aim_type == "nearest":
                # The dead zone starts at the top of the head ROI the estimator
                # returned, the same way the real-head branch uses the head
                # box's own top edge. A fixed 30 px constant was wrong at any
                # other distance or FOV: too tall up close, too short far away.
                head_y_min = head_cy
                try:
                    head_y_min = int(min(int(head_cy), int(bbox[1])))
                except Exception:
                    head_y_min = int(head_cy)
                target = (head_cx, head_cy, d, head_y_min, y2)
            else:
                target = (head_cx, head_cy, d, None, None)
            targets.append(target)
            target_bboxes.append(((head_cx, head_cy), (x1, y1, w, h)))

    return targets, target_bboxes, body_overlays, head_overlays, head_rects


class AimTracker:
    """
    鐩杩借工鍣ㄩ
    
    璨犺铂铏曠悊瑕栭牷骞€鐨勬崟鐛层€佺洰妯欐娓€佺瀯婧栬▓绠楀拰婊戦紶绉诲嫊鎺у埗銆?    鏀寔澶氱ó妯″紡锛圢ormal銆丼ilent锛夊拰閰嶇疆閬搁爡銆?    """
    
    RAW_STREAM_NDI_WINDOW = "NDI Raw Stream"
    RAW_STREAM_UDP_WINDOW = "UDP Raw Stream"

    def __init__(self, app, target_fps=200):
        """
        初始化 AimTracker
        
        Args:
            app: 應用程式實例，需要包含 capture 屬性（CaptureService）
            target_fps: 目標幀率，預設為 200 FPS
        """
        self.app = app
        # --- Params (avec valeurs fallback) ---
        self.normal_x_speed = float(getattr(config, "normal_x_speed", 0.5))
        self.normal_y_speed = float(getattr(config, "normal_y_speed", 0.5))
        self.normalsmooth = float(getattr(config, "normalsmooth", 10))
        self.normalsmoothfov = float(getattr(config, "normalsmoothfov", 10))
        self.mouse_dpi = float(getattr(config, "mouse_dpi", 800))
        self.fovsize = float(getattr(config, "fovsize", 300))
        self.ads_fov_enabled = bool(getattr(config, "ads_fov_enabled", False))
        self.ads_fovsize = float(getattr(config, "ads_fovsize", self.fovsize))
        self.ads_key = getattr(config, "ads_key", "Right Mouse Button")
        self.tbfovsize = float(getattr(config, "tbfovsize", 70))
        self.trigger_ads_fov_enabled = bool(getattr(config, "trigger_ads_fov_enabled", False))
        self.trigger_ads_fovsize = float(getattr(config, "trigger_ads_fovsize", self.tbfovsize))
        self.trigger_ads_key = getattr(config, "trigger_ads_key", "Right Mouse Button")
        self.trigger_ads_key_type = getattr(config, "trigger_ads_key_type", "hold")
        # Triggerbot delay range
        self.tbdelay_min = float(getattr(config, "tbdelay_min", 0.08))
        self.tbdelay_max = float(getattr(config, "tbdelay_max", 0.15))
        # Triggerbot hold range
        self.tbhold_min = float(getattr(config, "tbhold_min", 40))
        self.tbhold_max = float(getattr(config, "tbhold_max", 60))
        # Triggerbot 閫ｇ櫦瑷疆锛堢瘎鍦嶏級
        self.tbcooldown_min = float(getattr(config, "tbcooldown_min", 0.0))
        self.tbcooldown_max = float(getattr(config, "tbcooldown_max", 0.0))
        self.tbburst_count_min = int(getattr(config, "tbburst_count_min", 1))
        self.tbburst_count_max = int(getattr(config, "tbburst_count_max", 1))
        self.tbburst_interval_min = float(getattr(config, "tbburst_interval_min", 0.0))
        self.tbburst_interval_max = float(getattr(config, "tbburst_interval_max", 0.0))
        self.trigger_roi_size = int(getattr(config, "trigger_roi_size", 8))
        self.trigger_min_pixels = int(getattr(config, "trigger_min_pixels", 4))
        self.trigger_min_ratio = float(getattr(config, "trigger_min_ratio", 0.03))
        self.trigger_confirm_frames = int(getattr(config, "trigger_confirm_frames", 2))
        # 娉ㄦ剰锛歭ast_tb_click_time 鐝惧湪鐢?Triggerbot.py 涓殑鍏ㄥ眬鐙€鎱嬬鐞?        
        # RCS (Recoil Control System) 瑷疆
        self.rcs_pull_speed = int(getattr(config, "rcs_pull_speed", 10))
        self.rcs_activation_delay = int(getattr(config, "rcs_activation_delay", 100))
        self.rcs_rapid_click_threshold = int(getattr(config, "rcs_rapid_click_threshold", 200))
        
        # Silent Mode 瑷疆
        self.silent_distance = float(getattr(config, "silent_distance", 1.0))
        self.silent_delay = float(getattr(config, "silent_delay", 100.0))
        self.silent_move_delay = float(getattr(config, "silent_move_delay", 500.0))
        self.silent_return_delay = float(getattr(config, "silent_return_delay", 500.0))
        self.last_silent_click_time = 0  # 鐢ㄦ柤杩借工鏈€寰屼竴娆￠枊妲嶆檪闁?
        self.in_game_sens = float(getattr(config, "in_game_sens", 0.235))
        self.color = getattr(config, "color", "yellow")
        self.mode = getattr(config, "mode", "Normal")
        self.mode_sec = getattr(config, "mode_sec", "Normal")
        self.selected_mouse_button = getattr(config, "selected_mouse_button", 3)
        self.selected_tb_btn= getattr(config, "selected_tb_btn", 3)
        self.max_speed = float(getattr(config, "max_speed", 1000.0))

        # --- Main Aimbot Offset & Aim Type ---
        self.aim_offsetX = float(getattr(config, "aim_offsetX", 0))
        self.aim_offsetY = float(getattr(config, "aim_offsetY", 0))
        self.aim_type = getattr(config, "aim_type", "head")

        # --- Secondary Aimbot Parameters ---
        self.normal_x_speed_sec = float(getattr(config, "normal_x_speed_sec", 2))
        self.normal_y_speed_sec = float(getattr(config, "normal_y_speed_sec", 2))
        self.normalsmooth_sec = float(getattr(config, "normalsmooth_sec", 20))
        self.normalsmoothfov_sec = float(getattr(config, "normalsmoothfov_sec", 20))
        self.fovsize_sec = float(getattr(config, "fovsize_sec", 150))
        self.ads_fov_enabled_sec = bool(getattr(config, "ads_fov_enabled_sec", False))
        self.ads_fovsize_sec = float(getattr(config, "ads_fovsize_sec", self.fovsize_sec))
        self.ads_key_sec = getattr(config, "ads_key_sec", "Right Mouse Button")
        self.selected_mouse_button_sec = getattr(config, "selected_mouse_button_sec", 2)
        
        # --- Secondary Aimbot Offset & Aim Type ---
        self.aim_offsetX_sec = float(getattr(config, "aim_offsetX_sec", 0))
        self.aim_offsetY_sec = float(getattr(config, "aim_offsetY_sec", 0))
        self.aim_type_sec = getattr(config, "aim_type_sec", "head")

        self.controller = Mouse()
        self._stop_event = threading.Event()
        self._raw_stream_window_visible = {
            self.RAW_STREAM_NDI_WINDOW: False,
            self.RAW_STREAM_UDP_WINDOW: False,
        }
        self.move_queue = queue.Queue(maxsize=50)
        self._move_batch_size = 4
        self._move_batch_small_step = 3.0
        self._move_thread = threading.Thread(target=self._process_move_queue, daemon=True)
        self._move_thread.start()

        self.model, self.class_names = load_model()
        print("Classes:", self.class_names)
        self._target_fps = target_fps
        # Publish sequence of the last frame handed to detection. None means
        # "nothing processed yet" (and is also what non-UDP modes report).
        self._last_frame_seq = None
        # Per-frame latency numbers for the last processed frame. Written only by
        # the track thread, read by UI/debug callers, so no lock is needed for
        # the shallow dict swap.
        self.perf = {}
        # AI + UDP crop guard state: the metrics stashed before ``perf`` is
        # rebuilt, and the last bypass flag used to log only on transitions.
        self._ai_udp_crop_metrics = None
        self._ai_udp_bypass_active = None
        self._track_thread = threading.Thread(target=self._track_loop, daemon=True)
        self._track_thread.start()
        
        # 骞€瑷堟暩鍣紙鐢ㄦ柤瑾胯│锛?
        self._frame_count = 0
        self._last_frame_log_time = time.time()
        
        # --- Anti-Smoke Detector 鍒濆鍖?---
        self.anti_smoke_detector = AntiSmokeDetector()
        self.anti_smoke_detector.set_enabled(getattr(config, "anti_smoke_enabled", False))
        
        self.anti_smoke_detector_sec = AntiSmokeDetector()
        self.anti_smoke_detector_sec.set_enabled(getattr(config, "anti_smoke_enabled_sec", False))
        
        self.ema_alpha = float(getattr(config, "ema_alpha", 0.35))
        self.switch_confirm_frames = int(getattr(config, "switch_confirm_frames", 3))
        smoother_type = str(getattr(config, "smoother_type", "one_euro")).strip().lower()
        self._target_smoother = TargetSmoother(
            ema_alpha=self.ema_alpha,
            switch_confirm_frames=self.switch_confirm_frames,
            use_one_euro=(smoother_type == "one_euro"),
            min_cutoff=float(getattr(config, "one_euro_min_cutoff", 1.0)),
            beta=float(getattr(config, "one_euro_beta", 0.05)),
            d_cutoff=float(getattr(config, "one_euro_d_cutoff", 1.0)),
        )
        self.last_target = None
        self.stable_candidate = None
        self.stable_count = 0
        self._last_engine_toggle_key_state = False
        

    def stop(self):
        """
        鍋滄杩借工鍣?        
        瑷疆鍋滄浜嬩欢涓︾瓑寰呰拷韫ょ窔绋嬬祼鏉燂紝鐢ㄦ柤娓呯悊璩囨簮銆?        """
        self._stop_event.set()
        try:
            self._track_thread.join(timeout=1.0)
        except Exception:
            pass
        try:
            self._move_thread.join(timeout=1.0)
        except Exception:
            pass
        self._close_raw_stream_windows()
        # Drain and join the preview renderer before the UI destroys windows,
        # so only one thread ever drives HighGUI.
        try:
            preview_throttle.shutdown()
        except Exception:
            pass

    def _process_move_queue(self):
        """
        铏曠悊绉诲嫊闅婂垪
        
        鍦ㄥ緦鍙扮窔绋嬩腑鎸佺簩寰炵Щ鍕曢殜鍒椾腑鐛插彇绉诲嫊鎸囦护涓﹀煼琛屻€?        鏀寔寤堕伈鎺у埗锛岀⒑淇濈Щ鍕曟搷浣滅殑骞虫粦鍩疯銆?        
        閫欐槸涓€鍊嬬劇闄愬惊鐠帮紝鐩村埌绶氱▼琚祩姝€?        """
        drain_budget = None
        while True:
            if self._stop_event.is_set():
                # Shutdown requested: keep going only while there is already
                # queued work and the budget lasts. A producer that keeps
                # refilling the queue must not hold this thread past stop.
                if drain_budget is None:
                    drain_budget = max(1, self.move_queue.qsize())
                if drain_budget <= 0 or self.move_queue.empty():
                    break
                drain_budget -= 1
            try:
                dx, dy, delay = self.move_queue.get(timeout=0.1)
                latest_only = bool(getattr(config, "aim_latest_frame_priority", True))
                if latest_only:
                    # Keep only the newest N commands, then merge them.
                    # This preserves immediate latest-frame behavior while avoiding
                    # dropped Bezier/WindMouse sub-steps that cause jitter.
                    max_batch = max(
                        1,
                        int(getattr(config, "move_queue_merge_batch", self._move_batch_size)),
                    )
                    pending = [(dx, dy, delay)]
                    # Bounded drain: a producer that keeps refilling the queue
                    # must not turn this into an endless inner loop (the batch is
                    # capped anyway), and the stop event has to be honoured.
                    while len(pending) < 2 * max_batch and not self._stop_event.is_set():
                        try:
                            pending.append(self.move_queue.get_nowait())
                        except queue.Empty:
                            break
                    if len(pending) > max_batch:
                        pending = pending[-max_batch:]
                    merged_dx = float(sum(float(item[0]) for item in pending))
                    merged_dy = float(sum(float(item[1]) for item in pending))
                    merged_delay = min(
                        (max(0.0, float(item[2])) for item in pending),
                        default=0.0,
                    )
                else:
                    merged_dx = float(dx)
                    merged_dy = float(dy)
                    merged_delay = float(delay) if delay else 0.0

                try:
                    if merged_dx != 0.0 or merged_dy != 0.0:
                        self.controller.move(merged_dx, merged_dy)
                except Exception as e:
                    print("[Mouse.move error]", e)
                if merged_delay > 0:
                    # Slice the inter-step delay so a 5 s queued step cannot
                    # keep the thread alive through shutdown.
                    deadline = time.perf_counter() + merged_delay
                    while not self._stop_event.is_set():
                        remaining = deadline - time.perf_counter()
                        if remaining <= 0:
                            break
                        time.sleep(min(0.005, remaining))
            except queue.Empty:
                time.sleep(0.001)
                continue
            except Exception as e:
                print(f"[Move Queue Error] {e}")
                time.sleep(0.01)

    def _clip_movement(self, dx, dy):
        """
        闄愬埗绉诲嫊閫熷害
        
        灏囩Щ鍕曡窛闆㈤檺鍒跺湪鏈€澶ч€熷害绡勫湇鍏э紝闃叉绉诲嫊閬庡揩銆?        
        Args:
            dx: X 鏂瑰悜鐨勭Щ鍕曡窛闆?            dy: Y 鏂瑰悜鐨勭Щ鍕曡窛闆?            
        Returns:
            tuple: (clipped_dx, clipped_dy) 闄愬埗寰岀殑绉诲嫊璺濋洟
        """
        clipped_dx = -abs(self.max_speed) if dx < -abs(self.max_speed) else (
            abs(self.max_speed) if dx > abs(self.max_speed) else dx
        )
        clipped_dy = -abs(self.max_speed) if dy < -abs(self.max_speed) else (
            abs(self.max_speed) if dy > abs(self.max_speed) else dy
        )
        return float(clipped_dx), float(clipped_dy)

    def _track_loop(self):
        """
        Main tracking loop: frame-driven when the capture has a sequence.

        time.sleep() on Windows rounds up to the next timer tick, so pacing with
        ``sleep(period - elapsed)`` loses a whole tick every frame (measured:
        127.7 fps at target 144). Here the deadline is absolute and the last
        sub-millisecond of each period is spun, which keeps the configured rate
        while still sleeping most of the wait. The frame wait inside
        track_once() also wakes us as soon as a new frame lands.

        Two pacing modes:

        * ``track_wait_mode="frame"`` (default): a frame that arrives mid-period
          is handed to detection immediately instead of waiting for the next
          poll slot. ``frame_timeout`` must therefore cover the rest of the
          current period *plus* a full period, otherwise wait_for_new_frame()
          returns instantly and detection spins on a stale seq.
        * ``track_wait_mode="grid"``: the previous behaviour, kept as a rollback
          switch (``frame_timeout`` equal to the remaining budget).
        """
        has_timer_period = False
        if sys.platform == "win32":
            try:
                import ctypes
                ctypes.windll.winmm.timeBeginPeriod(1)
                has_timer_period = True
            except Exception:
                pass

        try:
            next_at = time.perf_counter()
            while not self._stop_event.is_set():
                # One bad frame (config reload mid-flight, a detector raising
                # from a shutting-down dependency) must cost one iteration, not
                # the whole thread: everything after this loop runs only at
                # shutdown, so an escaping exception ends aim for good.
                try:
                    period = 1.0 / max(1.0, float(self._target_fps))
                    now = time.perf_counter()
                    next_at = _pacing_deadline(next_at, now, period)
                    budget = max(0.0, next_at - now)
                    wait_mode = str(getattr(config, "track_wait_mode", "frame")).strip().lower()
                    frame_driven = wait_mode != "grid"
                    if frame_driven:
                        # Any frame landing inside this period must be able to wake
                        # the wait, so the wait covers the remainder plus one period.
                        frame_timeout = min(2.0 * period, budget + period)
                    else:
                        frame_timeout = budget
                    got_frame = False
                    try:
                        got_frame = bool(self.track_once(frame_timeout=frame_timeout))
                    except Exception as e:
                        print("[Track error]", e)
                    next_at += period
                except Exception as e:
                    print("[Track loop error]", e)
                    time.sleep(0.005)
                    next_at = time.perf_counter()
                    continue

                # A fresh frame was just processed: skip the tail sleep and go
                # straight back to wait_for_new_frame(), which is the real gate.
                # Only in frame mode, and only for sequenced sources (UDP);
                # NDI/MSS/CaptureCard report seq=None and would otherwise spin
                # at 100% CPU.
                if frame_driven and got_frame and getattr(self, "_last_frame_seq", None) is not None:
                    continue

                remaining = next_at - time.perf_counter()
                spin = min(0.0015, period * 0.25)
                if remaining > spin:
                    time.sleep(remaining - spin)
                while time.perf_counter() < next_at and not self._stop_event.is_set():
                    pass
        finally:
            if has_timer_period:
                try:
                    ctypes.windll.winmm.timeEndPeriod(1)
                except Exception:
                    pass

    def set_target_fps(self, fps):
        """
        Dynamically update target FPS
        
        Args:
            fps: New target FPS value
        """
        if fps < 1 or fps > 1000:
            print(f"[AimTracker] Invalid FPS: {fps}, using default 200")
            fps = 200
        self._target_fps = float(fps)
        print(f"[AimTracker] Target FPS updated to: {fps}")
    
    def _release_masked_buttons_once(self):
        if not hasattr(self, "_current_masked_buttons"):
            self._current_masked_buttons = set()
        if getattr(self, "_locks_unlocked_idle", False) and not self._current_masked_buttons:
            return
        try:
            from src.utils.mouse import is_connected, unlock_all_locks

            if not is_connected:
                self._current_masked_buttons.clear()
                self._locks_unlocked_idle = False
                return
            unlock_all_locks()
            self._current_masked_buttons.clear()
            self._locks_unlocked_idle = True
        except Exception:
            pass

    def _handle_button_mask(self):
        """
        铏曠悊鎸夐垥閬僵閭忚集
        
        鏍规摎閰嶇疆姹哄畾鏄惁閹栧畾鐗瑰畾鐨勬粦榧犳寜閳曪紝闃叉鍦ㄧ瀯婧栨檪瑾よЦ銆?        """
        # 濡傛灉鏈暉鐢?Button Mask锛岃В閹栨墍鏈夋寜閳?
        if not getattr(config, "button_mask_enabled", False):
            self._release_masked_buttons_once()
            return
        
        # 妾㈡煡鏄惁鏈変换浣?aimbot 姝ｅ湪閬嬭
        aimbot_running = (
            getattr(config, "enableaim", False) or 
            getattr(config, "enableaim_sec", False) or 
            getattr(config, "enabletb", False)
        )
        
        if not aimbot_running:
            self._release_masked_buttons_once()
            return
        
        # 妲嬪缓闇€瑕侀伄缃╃殑鎸夐垥闆嗗悎
        mask_set = set()
        
        button_mapping = {
            "mask_left_button": 0,    # L
            "mask_right_button": 1,   # R
            "mask_middle_button": 2,  # M
            "mask_side4_button": 3,   # S4
            "mask_side5_button": 4,   # S5
        }
        
        for config_key, button_idx in button_mapping.items():
            if getattr(config, config_key, False):
                mask_set.add(button_idx)
        
        # 鎳夌敤閬僵
        try:
            from src.utils.mouse import lock_button_idx, unlock_button_idx, is_connected
            
            if not is_connected:
                if hasattr(self, "_current_masked_buttons"):
                    self._current_masked_buttons.clear()
                self._locks_unlocked_idle = False
                return
            
            # 杩借釜鐣跺墠宸查帠瀹氱殑鎸夐垥
            if not hasattr(self, '_current_masked_buttons'):
                self._current_masked_buttons = set()
            
            # 瑙ｉ帠涓嶅啀闇€瑕侀伄缃╃殑鎸夐垥
            for idx in list(self._current_masked_buttons - mask_set):
                unlock_button_idx(idx)
            
            # 閹栧畾鏂伴渶瑕侀伄缃╃殑鎸夐垥
            for idx in list(mask_set - self._current_masked_buttons):
                lock_button_idx(idx)
            
            # 鏇存柊鐣跺墠鐙€鎱?
            self._current_masked_buttons = mask_set
            self._locks_unlocked_idle = False
            
        except Exception as e:
            print(f"[Button Mask Error] {e}")

    def _draw_fovs(self, img, frame):
        """Draw aimbot/triggerbot FOV circles onto the preview image."""
        center_x = int(frame.xres / 2)
        center_y = int(frame.yres / 2)
        if getattr(config, "enableaim", False):
            mode_main = getattr(config, "mode", "Normal")
            if mode_main != "NCAF":
                main_fov = int(get_active_aim_fov(is_sec=False, fallback=self.fovsize))
                cv2.circle(img, (center_x, center_y), main_fov, (255, 255, 255), 2)
                cv2.circle(img, (center_x, center_y), int(getattr(config, "normalsmoothfov", self.normalsmoothfov)), (51, 255, 255), 2)
            if mode_main == "NCAF":
                snap_r = int(getattr(config, "ncaf_snap_radius", 150))
                near_r = int(getattr(config, "ncaf_near_radius", 50))
                self._draw_dashed_circle(img, center_x, center_y, snap_r, (180, 180, 180), 1)
                cv2.circle(img, (center_x, center_y), near_r, (255, 200, 100), 1)
        if getattr(config, "enabletb", False):
            tb_fov = int(get_active_trigger_fov(fallback=self.tbfovsize))
            cv2.circle(img, (center_x, center_y), tb_fov, (255, 255, 255), 2)

    def _update_raw_stream_windows(self, raw_img):
        """Show or close raw-stream windows for NDI/UDP based on settings."""
        mode = getattr(self.app.capture, "mode", "")
        show_windows = bool(getattr(config, "show_opencv_windows", True))
        show_ndi = show_windows and mode == "NDI" and bool(getattr(config, "show_ndi_raw_stream_window", False))
        show_udp = show_windows and mode == "UDP" and bool(getattr(config, "show_udp_raw_stream_window", False))

        try:
            if show_ndi:
                if preview_throttle.render_if_due(self.RAW_STREAM_NDI_WINDOW):
                    preview_throttle.imshow(self.RAW_STREAM_NDI_WINDOW, raw_img)
                self._raw_stream_window_visible[self.RAW_STREAM_NDI_WINDOW] = True
            elif self._raw_stream_window_visible.get(self.RAW_STREAM_NDI_WINDOW, False):
                preview_throttle.destroy(self.RAW_STREAM_NDI_WINDOW)
                self._raw_stream_window_visible[self.RAW_STREAM_NDI_WINDOW] = False
        except Exception:
            pass

        try:
            if show_udp:
                if preview_throttle.render_if_due(self.RAW_STREAM_UDP_WINDOW):
                    preview_throttle.imshow(self.RAW_STREAM_UDP_WINDOW, raw_img)
                self._raw_stream_window_visible[self.RAW_STREAM_UDP_WINDOW] = True
            elif self._raw_stream_window_visible.get(self.RAW_STREAM_UDP_WINDOW, False):
                preview_throttle.destroy(self.RAW_STREAM_UDP_WINDOW)
                self._raw_stream_window_visible[self.RAW_STREAM_UDP_WINDOW] = False
        except Exception:
            pass

        # HighGUI is driven by the preview render worker, never by this thread.

    def _close_raw_stream_windows(self):
        """Close raw-stream windows."""
        try:
            if self._raw_stream_window_visible.get(self.RAW_STREAM_NDI_WINDOW, False):
                preview_throttle.destroy(self.RAW_STREAM_NDI_WINDOW)
                self._raw_stream_window_visible[self.RAW_STREAM_NDI_WINDOW] = False
        except Exception:
            pass
        try:
            if self._raw_stream_window_visible.get(self.RAW_STREAM_UDP_WINDOW, False):
                preview_throttle.destroy(self.RAW_STREAM_UDP_WINDOW)
                self._raw_stream_window_visible[self.RAW_STREAM_UDP_WINDOW] = False
        except Exception:
            pass

    def _compute_detection_roi(self, frame_shape):
        """Union of the aim/trigger FOV circles, padded and clamped.

        Returns ``None`` when ROI cropping is off or meaningless, which makes
        ``analyze`` run on the full frame. The caller's frame is already the
        post-`apply_mode_fov` image, so this is the *only* offset applied here;
        ``analyze`` adds it to every bbox exactly once.
        """
        if not bool(getattr(config, "detection_roi_enabled", False)):
            return None
        aim_on = bool(getattr(config, "enableaim", False) or getattr(config, "enableaim_sec", False))
        trigger_on = bool(getattr(config, "enabletb", False))
        if not aim_on and not trigger_on:
            return None

        h, w = int(frame_shape[0]), int(frame_shape[1])
        if h <= 0 or w <= 0:
            return None

        radii = []
        if aim_on:
            try:
                radii.append(float(get_active_aim_fov(is_sec=False, fallback=self.fovsize)))
            except Exception:
                radii.append(float(self.fovsize))
            if bool(getattr(config, "enableaim_sec", False)):
                try:
                    radii.append(
                        float(get_active_aim_fov(is_sec=True, fallback=self.fovsize_sec))
                    )
                except Exception:
                    radii.append(float(self.fovsize_sec))
        if trigger_on:
            try:
                radii.append(float(get_active_trigger_fov(fallback=self.tbfovsize)))
            except Exception:
                radii.append(float(self.tbfovsize))

        if not radii:
            return None
        radius = max(1.0, max(radii))
        pad = max(0, int(getattr(config, "detection_roi_padding", 64)))

        cx, cy = w / 2.0, h / 2.0
        x0 = int(max(0, math.floor(cx - radius - pad)))
        y0 = int(max(0, math.floor(cy - radius - pad)))
        x1 = int(min(w, math.ceil(cx + radius + pad)))
        y1 = int(min(h, math.ceil(cy + radius + pad)))

        if bool(getattr(config, "dynamic_micro_roi_enabled", True)) and self.last_target is not None:
            tx, ty = float(self.last_target[0]), float(self.last_target[1])
            target_pad = max(16, int(getattr(config, "dynamic_micro_roi_padding", 64)))
            x0 = min(x0, int(max(0, math.floor(tx - target_pad))))
            y0 = min(y0, int(max(0, math.floor(ty - target_pad))))
            x1 = max(x1, int(min(w, math.ceil(tx + target_pad))))
            y1 = max(y1, int(min(h, math.ceil(ty + target_pad))))

        if x1 <= x0 or y1 <= y0:
            return None

        try:
            max_fraction = float(getattr(config, "detection_roi_max_fraction", 0.70))
        except Exception:
            max_fraction = 0.70
        if ((x1 - x0) * (y1 - y0)) / float(max(1, w * h)) >= max_fraction:
            # Cropping a near-full frame only adds border noise; run full-frame.
            return None
        return (x0, y0, x1, y1)

    def _nearest_bbox_index(self, target, target_bboxes):
        tx, ty = float(target[0]), float(target[1])
        best_idx, best_d2 = -1, None
        for idx, (center, _bbox) in enumerate(target_bboxes):
            d2 = (float(center[0]) - tx) ** 2 + (float(center[1]) - ty) ** 2
            if best_d2 is None or d2 < best_d2:
                best_idx, best_d2 = idx, d2
        return best_idx

    def _build_target_features(self, targets, target_bboxes, mask, frame_shape, roi):
        """Compute each target's bbox/contour features once, keyed by bbox index.

        ``mask`` may be ROI-sized, hence the ``roi`` offset. Features are cached
        for one frame only: the mask changes every frame (and ``HSV_MIN/MAX`` can
        change between frames), so nothing here survives a frame boundary.
        """
        cache = {}
        if mask is None or not target_bboxes:
            return cache
        if not (
            self.anti_smoke_detector.is_enabled()
            or self.anti_smoke_detector_sec.is_enabled()
        ):
            # Neither detector will ask: do not pay for the contours at all.
            return cache

        # One detector is enough to compute features: the thresholds live in
        # is_bbox_plausible, not in the feature extraction. Both are the same
        # class, so either works even when only the secondary one is enabled.
        worker = self.anti_smoke_detector
        if not worker.is_enabled() and self.anti_smoke_detector_sec.is_enabled():
            worker = self.anti_smoke_detector_sec
        for idx, (_center, bbox) in enumerate(target_bboxes):
            try:
                cache[idx] = worker.compute_bbox_features(
                    bbox, mask, frame_shape, roi=roi
                )
            except Exception:
                cache[idx] = None
        return cache

    def _filter_targets_with_anti_smoke(self, targets, target_bboxes, mask, frame_shape,
                                        detector, features=None, roi=None):
        """Filter targets using nearest bbox contour checks from anti-smoke detector."""
        if not targets or not target_bboxes or detector is None:
            return targets
        if not detector.is_enabled() or mask is None:
            return targets

        filtered_targets = []
        for target in targets:
            if len(target) < 2:
                continue
            nearest_idx = self._nearest_bbox_index(target, target_bboxes)
            if nearest_idx < 0:
                continue
            nearest_bbox = target_bboxes[nearest_idx][1]
            cached = None if features is None else features.get(nearest_idx)
            if detector.is_bbox_plausible(
                nearest_bbox, mask, frame_shape, features=cached, roi=roi
            ):
                filtered_targets.append(target)
        return filtered_targets

    def track_once(self, frame_timeout=0.0):
        """
        Run one full tracking iteration.

        Returns True when a *new* frame was processed, False when the loop only
        did housekeeping (no connected capture, no frame yet, or the same frame
        the previous iteration already processed). Frame freshness comes from
        the capture sequence number: the UDP receiver increments it once per
        decoded frame, so an unchanged seq means nothing new arrived.
        """
        if not self.app.capture.is_connected():
            self._close_raw_stream_windows()
            self._last_frame_seq = None
            return False

        # Button Mask management
        self._handle_button_mask()

        # Mouse lock manager tick
        try:
            from src.utils.mouse import tick_movement_lock_manager
            tick_movement_lock_manager()
        except Exception:
            pass

        # Wait (bounded by the frame budget) for a frame newer than the last
        # one processed. Non-UDP modes report seq=None and never wait.
        raw_bgr_img, frame_seq = self.app.capture.read_frame_with_seq(
            apply_fov=False,
            after_seq=self._last_frame_seq,
            timeout=frame_timeout,
        )
        if frame_seq is None:
            # No freshness signal for this capture mode: process every read
            # so NDI/MSS/CaptureCard keep their previous behaviour.
            self._last_frame_seq = None
        else:
            if raw_bgr_img is None:
                # Nothing decoded yet (or the stream just stopped). Remember the
                # seq so the next iteration waits for a newer frame instead of
                # re-reading in a tight loop.
                self._last_frame_seq = frame_seq
                return False
            if frame_seq == self._last_frame_seq:
                # Already processed this frame: skip detection instead of
                # re-running it on a stale image.
                return False
            if self._last_frame_seq is not None and frame_seq < self._last_frame_seq:
                # The counter went backwards: the UDP receiver was rebuilt and
                # restarts its publish sequence at 0. Adopt the new epoch and
                # process this frame instead of waiting for a watermark the new
                # receiver may never reach.
                log_print(
                    f"[Track] Frame sequence reset {self._last_frame_seq} -> {frame_seq} "
                    "(capture source rebuilt)."
                )
            self._last_frame_seq = frame_seq

        if raw_bgr_img is None:
            return False

        # Callers downstream require a contiguous buffer
        if not raw_bgr_img.flags['C_CONTIGUOUS']:
            raw_bgr_img = np.ascontiguousarray(raw_bgr_img)

        self._update_raw_stream_windows(raw_bgr_img)

        # Preview submission is asynchronous, so there is no HighGUI pump (and
        # no blocking waitKey) on this thread any more.
        self._track_frame(raw_bgr_img)
        return True

    def _log_ai_udp_crop_guard_once(self):
        """Surface the AI UDP crop guard without spamming the log every frame.

        ``get_udp_crop_state()`` is optional (other capture modes, and MagicMock
        services in tests, do not provide it), so a non-dict answer is ignored.
        The warning is emitted once per transition into (and out of) the bypass.
        """
        try:
            state = self.app.capture.get_udp_crop_state()
        except Exception:
            return
        if not isinstance(state, dict) or not state:
            # Not in UDP mode (or the service cannot answer): never report a
            # stale bypass left over from an earlier mode.
            self._ai_udp_crop_metrics = None
            return
        bypass = bool(state.get("bypass"))
        reason = str(state.get("reason", ""))
        # ``perf`` is rebuilt later in this frame, so the numbers are stashed
        # here and copied into the new dict after detection finishes.
        self._ai_udp_crop_metrics = {"active": bypass, "reason": reason}
        previous = getattr(self, "_ai_udp_bypass_active", None)
        self._ai_udp_bypass_active = bypass
        if bypass == previous:
            return
        try:
            if bypass:
                print(
                    "[Track] AI UDP crop guard: skipping udp_fov crop "
                    f"({state.get('total_px')}px < {state.get('min_px')}px model input)"
                )
            elif previous:
                print("[Track] AI UDP crop guard released: udp_fov crop is active again")
        except Exception:
            pass

    def _track_frame(self, raw_bgr_img):
        """Body of track_once; all exits are covered by the caller's finally."""
        # Check Engine Mode Toggle Hotkey
        toggle_key = getattr(config, "ai_toggle_key", "")
        if toggle_key and str(toggle_key).strip().lower() != "none":
            try:
                from src.utils.activation import is_binding_pressed
                pressed = is_binding_pressed(toggle_key)
                if pressed and not getattr(self, "_last_engine_toggle_key_state", False):
                    new_ai = not bool(getattr(config, "ai_detection_enabled", False))
                    config.ai_detection_enabled = new_ai
                    config.detection_engine = "ai_detection" if new_ai else "colorbot"
                    print(f"[Engine] Hotkey: switched detection engine to {config.detection_engine.upper()}")
                    try:
                        from src.utils.network_feedback import send_toggle_feedback
                        send_toggle_feedback(new_ai)
                    except Exception:
                        pass
                    if hasattr(self.app, "after") and hasattr(self.app, "_sync_engine_ui_from_config"):
                        try:
                            self.app.after(0, self.app._sync_engine_ui_from_config)
                        except Exception:
                            pass
                self._last_engine_toggle_key_state = pressed
            except Exception:
                pass

        bgr_img = self.app.capture.apply_mode_fov(raw_bgr_img)
        if bgr_img is None:
            return
        self._log_ai_udp_crop_guard_once()
        if not bgr_img.flags['C_CONTIGUOUS']:
            bgr_img = np.ascontiguousarray(bgr_img)

        # 骞€瑷堟暩锛堜緵 UI 璁€鍙栵紝涓嶅啀鍙嶈鎵撳嵃锛?
        self._frame_count += 1
        current_time = time.time()
        if current_time - self._last_frame_log_time >= 5.0:
            self._frame_count = 0
            self._last_frame_log_time = current_time
        
        # 椹楄瓑骞€鐨勬湁鏁堟€?
        if bgr_img.size == 0:
            print("[Track] Empty frame received")
            return

        # 鍓靛缓铏涙摤骞€灏嶈薄浠ュ吋瀹硅垔浠ｇ⒓
        h, w = bgr_img.shape[:2]
        if w == 0 or h == 0: 
            print(f"[Track] Invalid frame dimensions: {w}x{h}")
            return
        frame = FrameInfo(w, h)
        
        # Check if OpenCV detection preview is actively requested
        show_detection = bool(getattr(config, "show_opencv_windows", True) and 
                              getattr(config, "show_opencv_detection", True))

        # Zero-copy: bgr_img stays pristine for the whole frame. Every debug
        # overlay (body/head boxes, FOV circles, enhanced overlay) is deferred
        # and painted onto the display copy only, so Triggerbot can read
        # bgr_img in place with no copy and no risk of detecting its own
        # overlay colours (a red head marker would self-trigger a red target).
        trigger_source_img = bgr_img

        body_overlays = []
        head_overlays = []
        head_rects = []

        # Publish -> detection handoff, measured on the frame actually used.
        frame_meta = {}
        try:
            meta_candidate = self.app.capture.get_frame_meta()
            if isinstance(meta_candidate, dict):
                frame_meta = meta_candidate
        except Exception:
            frame_meta = {}
        publish_to_detect_ms = None
        published_at = frame_meta.get("published_at")
        if isinstance(published_at, (int, float)):
            publish_to_detect_ms = max(
                0.0, (time.perf_counter() - float(published_at)) * 1000.0
            )

        engine = "ai" if bool(getattr(config, "ai_detection_enabled", False)) else "hsv"
        # AI ONNX models always run on their fixed tensor size, so cropping a
        # narrow FOV/ADS ROI gives zero speedup while cutting enemy bodies and
        # adding upscale blur.
        roi = None if engine == "ai" else self._compute_detection_roi(bgr_img.shape)
        detect_start = time.perf_counter()
        detection = None
        try:
            # The engine is chosen here, not inside analyze(): the colour model
            # is still handed over so ``analyze`` can fall back to it when the
            # AI detector is enabled but unusable (no onnxruntime, model file
            # missing) -- exactly what models/README.md promises.
            detection = analyze(self.model, bgr_img, roi=roi, engine=engine)
            detection_results = detection.detections
            # Only a colour pass has a measured mask. An AI frame rasterises its
            # boxes on demand, so merely reading ``detection.mask`` here would
            # pay a full-frame allocation plus a full-frame countNonZero on
            # every frame, including frames where nothing consumes the mask.
            mask = detection.mask if getattr(detection, "source", "hsv") == "hsv" else None
            # MASK preview: full_mask() builds the frame-sized image only when
            # this consumer is actually due, not on every frame.
            if (getattr(config, "show_opencv_windows", True) and 
                getattr(config, "show_opencv_mask", True) and 
                detection.has_mask):
                if preview_throttle.render_if_due("MASK"):
                    preview_throttle.imshow("MASK", detection.full_mask())
        except Exception as e:
            print("[perform_detection error]", e)
            detection_results = []
            mask = None
            # 鍗充娇妾㈡脯澶辨晽锛屼篃椤ず鍘熷鍦栧儚锛堝鏋滃暉鐢級
            if show_detection:
                try:
                    if preview_throttle.render_if_due("Detection"):
                        preview_throttle.imshow("Detection", bgr_img)
                except:
                    pass
        detect_ms = (time.perf_counter() - detect_start) * 1000.0

        targets = []
        target_bboxes = []
        # Whether ``mask`` describes real pixels or was rasterised from AI
        # boxes. Colour-statistics consumers (anti-smoke, head refinement) are
        # only meaningful on a measured mask.
        mask_is_measured = detection is None or getattr(detection, "source", "hsv") == "hsv"
        if detection_results:
            # 鐛插彇鐣跺墠 aim_type锛圡ain Aimbot锛?
            aim_type = getattr(config, "aim_type", "head")
            dynamic_min_area = min_aim_bbox_area(frame.xres, frame.yres)

            # Target selection lives in build_aim_targets(): a 'head' box is
            # aimed at directly, and only bodies without one are estimated.
            mask_roi = detection.roi if detection is not None and detection.roi_used else None
            # Head refinement reads the colour mask to find where the head
            # pixels actually are. An AI mask is the detected box filled in, so
            # it holds no head information: feeding it in would centre the
            # estimate on the middle of the box. Geometry only in that case.
            estimate_mask = mask if mask_is_measured else None

            def _estimate(x1, y1, x2, y2):
                return self._estimate_head_positions(
                    x1, y1, x2, y2, bgr_img, estimate_mask, mask_roi=mask_roi
                )

            (
                targets,
                target_bboxes,
                body_overlays,
                head_overlays,
                head_rects,
            ) = build_aim_targets(
                detection_results,
                aim_type,
                frame.xres,
                frame.yres,
                dynamic_min_area,
                estimate_head_positions=_estimate,
            )
            if not show_detection:
                # Overlays are display-only; skip building them entirely.
                body_overlays = []
                head_overlays = []
                head_rects = []

        targets_all = targets
        use_temporal_smoothing = bool(getattr(config, "enable_target_temporal_smoothing", False))
        if targets_all and use_temporal_smoothing:
            targets_all = self._target_smoother.stabilize(targets_all, frame.xres / 2.0, frame.yres / 2.0)
            self.last_target = self._target_smoother.last_target
            self.stable_candidate = self._target_smoother.stable_candidate
            self.stable_count = self._target_smoother.stable_count

        targets_main = list(targets_all)
        targets_sec = list(targets_all)
        shared_features = {}
        detection_roi = detection.roi if detection is not None and detection.roi_used else None
        # Anti-smoke decides from colour statistics of the mask (fill ratio,
        # solidity, density). An AI mask is the rasterised bbox itself, i.e.
        # perfectly filled, so every heuristic would classify the detection as
        # smoke and drop it. The classifier only makes sense on a colour mask.
        if targets_all and target_bboxes and mask_is_measured:
            frame_shape = bgr_img.shape
            # One contour analysis per bbox, shared by both detectors: they keep
            # their own thresholds, so decisions stay independent while the
            # expensive part stops being paid twice.
            shared_features = self._build_target_features(
                targets_all, target_bboxes, mask, frame_shape, detection_roi
            )
            targets_main = self._filter_targets_with_anti_smoke(
                targets_all, target_bboxes, mask, frame_shape,
                self.anti_smoke_detector,
                features=shared_features, roi=detection_roi,
            )
            targets_sec = self._filter_targets_with_anti_smoke(
                targets_all, target_bboxes, mask, frame_shape,
                self.anti_smoke_detector_sec,
                features=shared_features, roi=detection_roi,
            )

        try:
            # The trigger mask is only read by ``process_triggerbot``, which
            # returns "DISABLED" before touching it when ``enabletb`` is off.
            # Passing ``None`` there keeps a deferred AI mask from being built
            # just to be thrown away (the magnet trigger uses colour matching,
            # not this mask). The colour model is still handed to ``analyze`` so
            # an enabled-but-unusable AI detector can fall back to it.
            trigger_mask = None
            if detection is not None and bool(getattr(config, "enabletb", False)):
                trigger_mask = detection.raw_mask
            self._aim_and_move(
                targets_main,
                frame,
                bgr_img,
                targets_sec=targets_sec,
                targets_trigger=targets_all,
                trigger_img=trigger_source_img,
                trigger_mask=trigger_mask,
                trigger_mask_roi=detection_roi,
            )
        except Exception as e:
            print("[Aim error]", e)

        track_elapsed_ms = (time.perf_counter() - detect_start) * 1000.0
        self.perf = {
            "frame_seq": self._last_frame_seq,
            "publish_to_detect_ms": publish_to_detect_ms,
            "detect_ms": detect_ms,
            "detect_track_ms": track_elapsed_ms,
            "roi": detection_roi,
            "roi_used": bool(detection is not None and detection.roi_used),
            "targets": len(targets_all),
            "frame_start_time": frame_meta.get("frame_start_time"),
        }
        crop_metrics = getattr(self, "_ai_udp_crop_metrics", None)
        if isinstance(crop_metrics, dict):
            self.perf["ai_udp_crop_bypass"] = bool(crop_metrics.get("active"))
            self.perf["ai_udp_crop_reason"] = crop_metrics.get("reason")
        try:
            from src.aim_system.Triggerbot import _triggerbot_state as _tb_state
            decision_ms = _tb_state.get("last_decision_ms")
        except Exception:
            decision_ms = None
        if decision_ms is not None:
            self.perf["trigger_decision_ms"] = float(decision_ms)

        # FOV circles, tracking boxes and the enhanced overlay are all painted
        # here, on the display copy, after the aim/trigger pass has already read
        # the clean frame. Drawing them onto bgr_img earlier forced a full-frame
        # copy every frame just to keep Triggerbot's ROI unpolluted.

        # 顯示 Detection 視窗（根據設定）
        if show_detection and preview_throttle.render_if_due("Detection"):
            try:
                display_img = bgr_img.copy()
                # Same layering as the original: body/head markers, then FOV
                # circles, then the enhanced overlay on top.
                for bx1, by1, bx2, by2, conf in body_overlays:
                    self._draw_body(display_img, bx1, by1, bx2, by2, conf)
                for hx, hy in head_overlays:
                    self._draw_head_bbox(display_img, hx, hy)
                for rx1, ry1, rx2, ry2 in head_rects:
                    cv2.rectangle(display_img, (rx1, ry1), (rx2, ry2), (0, 255, 255), 1)
                self._draw_fovs(display_img, frame)
                display_img = self._draw_enhanced_detection(display_img, targets_all, frame)
                # Handed to the render worker; this thread never touches HighGUI.
                preview_throttle.imshow("Detection", display_img)
            except Exception as e:
                print(f"[OpenCV display error] {e}")

    def _draw_enhanced_detection(self, img, targets, frame):
        """
        绻＝澧炲挤鐨勬娓瑕哄寲
        
        Args:
            img: BGR 鍦栧儚
            targets: 鐩鍒楄〃 [(cx, cy, distance), ...]
            frame: 骞€淇℃伅灏嶈薄
            
        Returns:
            绻＝寰岀殑鍦栧儚
        """
        center_x = int(frame.xres / 2)
        center_y = int(frame.yres / 2)
        
        # 1. 绻＝鍗佸瓧婧栨槦锛堜腑蹇冿級- 鏍规摎瑷疆
        if getattr(config, "show_crosshair", True):
            crosshair_size = 20
            crosshair_color = (0, 255, 0)  # 缍犺壊
            cv2.line(img, (center_x - crosshair_size, center_y), 
                    (center_x + crosshair_size, center_y), crosshair_color, 2)
            cv2.line(img, (center_x, center_y - crosshair_size), 
                    (center_x, center_y + crosshair_size), crosshair_color, 2)
            cv2.circle(img, (center_x, center_y), 3, crosshair_color, -1)
        
        # 2. 绻＝ FOV 鍦撳湀
        if getattr(config, "enableaim", False):
            mode_main = getattr(config, "mode", "Normal")
            # NCAF 鏅備笉绻＝鍘熸湰鐨?FOV 鍦?
            if mode_main != "NCAF":
                # Main Aimbot FOV
                main_fov = int(get_active_aim_fov(is_sec=False, fallback=self.fovsize))
                cv2.circle(img, (center_x, center_y), main_fov, (255, 255, 255), 2)
                
                # Smooth FOV
                smooth_fov = int(getattr(config, "normalsmoothfov", self.normalsmoothfov))
                cv2.circle(img, (center_x, center_y), smooth_fov, (0, 255, 255), 1)
            
            # NCAF Radius 鍦?(Main Aimbot)
            if mode_main == "NCAF":
                snap_r = int(getattr(config, "ncaf_snap_radius", 150))
                near_r = int(getattr(config, "ncaf_near_radius", 50))
                # Snap Radius (outer) 鈥?铏涚窔棰ㄦ牸
                self._draw_dashed_circle(img, center_x, center_y, snap_r, (180, 180, 180), 1, dash_len=12)
                # Near Radius (inner) 鈥?娣鸿棈鑹?
                cv2.circle(img, (center_x, center_y), near_r, (255, 200, 100), 1)
            
            # Sec Aimbot FOV (濡傛灉鍟熺敤)
            if getattr(config, "enableaim_sec", False):
                mode_sec = getattr(config, "mode_sec", "Normal")
                if mode_sec != "NCAF":
                    sec_fov = int(get_active_aim_fov(is_sec=True, fallback=self.fovsize_sec))
                    # 鑸囦富鐬勬簴涓嶅悓鑹诧紝鎺＄敤闈掕壊
                    cv2.circle(img, (center_x, center_y), sec_fov, (255, 255, 0), 2)
                
                # NCAF Radius 鍦?(Sec Aimbot)
                if mode_sec == "NCAF":
                    snap_r_sec = int(getattr(config, "ncaf_snap_radius_sec", 150))
                    near_r_sec = int(getattr(config, "ncaf_near_radius_sec", 50))
                    self._draw_dashed_circle(img, center_x, center_y, snap_r_sec, (200, 100, 200), 1, dash_len=12)
                    cv2.circle(img, (center_x, center_y), near_r_sec, (200, 150, 255), 1)
        
        # Triggerbot FOV
        if getattr(config, "enabletb", False):
            tb_fov = int(get_active_trigger_fov(fallback=self.tbfovsize))
            cv2.circle(img, (center_x, center_y), tb_fov, (0, 165, 255), 2)
        
        # 3. 绻＝鐩淇℃伅
        if targets:
            # 鎵惧埌鏈€浣崇洰妯欙紙璺濋洟涓績鏈€杩戠殑锛?
            best_target = min(targets, key=lambda t: t[2])
            
            for i, target in enumerate(targets):
                # targets 绲愭: (cx, cy, distance, head_y_min, body_y_max)
                if len(target) >= 5:
                    tx, ty, dist, _, _ = target
                else:
                    # 鍏煎鑸婃牸寮?
                    tx, ty, dist = target[:3]
                
                is_best = target == best_target
                
                # 鐩榛為鑹诧紙鏈€浣崇洰妯欑敤涓嶅悓椤忚壊锛?
                # Compact marker: a thin ring, never a filled disc. The old filled
                # r=8 disc was 17 px across and covered a distant head completely,
                # hiding the very thing being aimed at.
                if is_best:
                    target_color = (0, 0, 255)  # 绱呰壊
                else:
                    target_color = (255, 0, 0)  # 钘嶈壊
                circle_radius = 3
                thickness = 1
                
                # 绻＝鐩榛?
                # LINE_8 (not LINE_AA) on purpose: the marker must stay inside a
                # 7x7 box so it cannot bleed onto a distant head.
                cv2.circle(img, (int(tx), int(ty)), circle_radius, target_color,
                           thickness, cv2.LINE_8)
                
                # 绻＝寰炰腑蹇冨埌鐩鐨勯€ｇ窔锛堝儏鏈€浣崇洰妯欙級
                if is_best:
                    cv2.line(img, (center_x, center_y), (int(tx), int(ty)), 
                            (0, 255, 0), 1, cv2.LINE_AA)
                    # Redrawn after the line: the guide line's endpoint would
                    # otherwise paint over the marker's centre pixel.
                    _set_pixel(img, tx, ty, target_color)
                
                # 绻＝璺濋洟鏂囧瓧 - 鏍规摎瑷疆
                if getattr(config, "show_distance_text", True):
                    dist_text = f"{int(dist)}px"
                    cv2.putText(img, dist_text, (int(tx) + 10, int(ty) - 10),
                               cv2.FONT_HERSHEY_SIMPLEX, 0.5, target_color, 1, cv2.LINE_AA)
        
        # 4. 绻＝鐙€鎱嬩俊鎭紙宸︿笂瑙掞級- 鏍规摎瑷疆
        y_offset = 30
        line_height = 25
        
        # 妯″紡淇℃伅
        if getattr(config, "show_mode_text", True):
            mode = getattr(config, "mode", "Normal")
            cv2.putText(img, f"Mode: {mode}", (10, y_offset),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2, cv2.LINE_AA)
            y_offset += line_height
            engine_name = "AI (DirectML)" if getattr(config, "ai_detection_enabled", False) else f"Colorbot ({getattr(config, 'color', 'yellow').upper()})"
            engine_col = (0, 255, 255) if getattr(config, "ai_detection_enabled", False) else (255, 180, 0)
            cv2.putText(img, f"Engine: {engine_name}", (10, y_offset),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.55, engine_col, 2, cv2.LINE_AA)
            y_offset += line_height
        
        # Aimbot 鐙€鎱?& Visual Toggle Banner
        if getattr(config, "show_aimbot_status", True):
            from src.utils.activation import get_aimbot_toggle_state
            act_type = getattr(config, "aimbot_activation_type", "hold_enable")
            if act_type == "toggle":
                is_main_active = get_aimbot_toggle_state(is_sec=False) and getattr(config, "enableaim", False)
            else:
                is_main_active = getattr(config, "enableaim", False)

            # Draw Prominent HUD Banner at the top-right corner
            h, w = img.shape[:2]
            banner_w = 170
            banner_h = 32
            bx1 = w - banner_w - 10
            by1 = 10
            bx2 = w - 10
            by2 = by1 + banner_h

            if is_main_active:
                # Active: Vibrant Green Box with white text
                cv2.rectangle(img, (bx1, by1), (bx2, by2), (0, 180, 0), -1)
                cv2.rectangle(img, (bx1, by1), (bx2, by2), (255, 255, 255), 1, cv2.LINE_AA)
                cv2.putText(img, "AIM: ACTIVE", (bx1 + 14, by1 + 22),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2, cv2.LINE_AA)
            else:
                # Standby: Dark Red Box with muted white text
                cv2.rectangle(img, (bx1, by1), (bx2, by2), (30, 30, 160), -1)
                cv2.rectangle(img, (bx1, by1), (bx2, by2), (100, 100, 200), 1, cv2.LINE_AA)
                cv2.putText(img, "AIM: STANDBY", (bx1 + 10, by1 + 22),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.65, (200, 200, 200), 2, cv2.LINE_AA)

            if getattr(config, "enableaim", False):
                main_status = "ACTIVE" if is_main_active else "STANDBY"
                status_color = (0, 255, 0) if is_main_active else (0, 0, 255)
                cv2.putText(img, f"Main Aim: {main_status}", (10, y_offset),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.6, status_color, 2, cv2.LINE_AA)
                y_offset += line_height
            
            if getattr(config, "enableaim_sec", False):
                sec_status = "ON" if getattr(config, "enableaim_sec", False) else "OFF"
                status_color = (255, 0, 255) if sec_status == "ON" else (128, 128, 128)
                cv2.putText(img, f"Sec Aim: {sec_status}", (10, y_offset),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.6, status_color, 2, cv2.LINE_AA)
                y_offset += line_height
        
        # Triggerbot 鐙€鎱?
        if getattr(config, "show_triggerbot_status", True) and getattr(config, "enabletb", False):
            tb_status = "ON" if getattr(config, "enabletb", False) else "OFF"
            status_color = (0, 165, 255) if tb_status == "ON" else (128, 128, 128)
            cv2.putText(img, f"Trigger: {tb_status}", (10, y_offset),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, status_color, 2, cv2.LINE_AA)
            y_offset += line_height
        
        # 鐩鏁搁噺
        if getattr(config, "show_target_count", True):
            cv2.putText(img, f"Targets: {len(targets)}", (10, y_offset),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2, cv2.LINE_AA)
        
        return img

    @staticmethod
    def _draw_dashed_circle(img, cx, cy, radius, color, thickness=1, dash_len=10):
        """
        绻＝铏涚窔鍦撳湀

        Args:
            img: BGR 鍦栧儚
            cx, cy: 鍦撳績
            radius: 鍗婂緫 (px)
            color: BGR 椤忚壊
            thickness: 绶氱矖
            dash_len: 姣忔寮х殑瑙掑害 (搴?
        """
        import numpy as np
        if radius <= 0:
            return
        for angle_start in range(0, 360, dash_len * 2):
            angle_end = min(angle_start + dash_len, 360)
            cv2.ellipse(img, (cx, cy), (radius, radius), 0,
                        angle_start, angle_end, color, thickness, cv2.LINE_AA)

    def _draw_head_bbox(self, img, headx, heady):
        """
        绻＝闋儴浣嶇疆妯欒锛堝劒鍖栫増鏈級
        
        鍦ㄥ湒鍍忎笂绻＝涓€鍊嬪付澶栧湀鐨勯牠閮ㄦ瑷橈紝鏇村鏄撹瓨鍒ャ€?        
        Args:
            img: BGR 鍦栧儚闄ｅ垪
            headx: 闋儴 X 搴ф
            heady: 闋儴 Y 搴ф
        """
        # 澶栧湀锛堢櫧鑹诧級- thin ring so a 5 px head stays visible inside it
        cv2.circle(img, (int(headx), int(heady)), 3, (255, 255, 255), 1, cv2.LINE_8)
        # 鍏у湀锛堢磪鑹诧級- single centre pixel instead of a filled r=3 disc
        _set_pixel(img, headx, heady, (0, 0, 255))

    def _estimate_head_positions(self, x1, y1, x2, y2, img, mask=None, mask_roi=None):
        """
        Estimate head position from body bbox geometry only.

        Returns ``[(head_cx, head_cy, head_roi_rect), ...]``. The head ROI
        rectangle is *returned* rather than painted on ``img``: ``img`` is the
        frame the receiver still owns and the one Triggerbot reads, so drawing a
        yellow marker into it would mutate shared state and, with
        ``config.color == "yellow"``, feed the detector its own overlay.

        ``mask_roi`` maps a ROI-sized ``mask`` back into frame coordinates; the
        bbox arguments are always in frame space.
        """
        if not img.flags['C_CONTIGUOUS']:
            img = np.ascontiguousarray(img)

        offset_y = float(getattr(config, "offsetY", 0))
        offset_x = float(getattr(config, "offsetX", 0))

        width = max(1, int(x2) - int(x1))
        height = max(1, int(y2) - int(y1))

        top_crop_factor = 0.10
        side_crop_factor = 0.10

        effective_y1 = float(y1) + float(height) * top_crop_factor
        effective_height = float(height) * (1.0 - top_crop_factor)
        effective_x1 = float(x1) + float(width) * side_crop_factor
        effective_x2 = float(x2) - float(width) * side_crop_factor
        effective_width = max(1.0, effective_x2 - effective_x1)

        center_x = (effective_x1 + effective_x2) / 2.0
        headx_base = center_x + effective_width * (offset_x / 100.0)
        # Keep Y estimate deterministic (no mask-driven jitter).
        base_head_ratio = float(getattr(config, "head_estimate_ratio", 0.22))
        heady_base = float(y1) + float(height) * base_head_ratio + effective_height * (offset_y / 100.0)

        # Optional one-pass refinement from the already computed global mask.
        # Use only the upper body band and median X to reduce left/right arm jitter.
        if mask is not None:
            rx0, ry0 = (0, 0)
            if mask_roi is not None:
                try:
                    rx0, ry0 = int(mask_roi[0]), int(mask_roi[1])
                except Exception:
                    rx0, ry0 = 0, 0
            mx1 = max(0, min(int(x1) - rx0, mask.shape[1] - 1))
            my1 = max(0, min(int(y1) - ry0, mask.shape[0] - 1))
            mx2 = max(mx1 + 1, min(int(x2) - rx0, mask.shape[1]))
            my2 = max(my1 + 1, min(int(y2) - ry0, mask.shape[0]))
            band_ratio = float(getattr(config, "head_refine_band_ratio", 0.25))
            upper_h = max(6, int((my2 - my1) * band_ratio))
            upper_y2 = min(my2, my1 + upper_h)
            upper_mask = mask[my1:upper_y2, mx1:mx2]
            if upper_mask.size > 0:
                ys, xs = np.where(upper_mask > 0)
                if len(xs) >= int(getattr(config, "head_refine_min_pixels", 20)):
                    headx_base = float(mx1 + rx0 + int(np.median(xs)))
                    if bool(getattr(config, "head_refine_y_enabled", True)):
                        heady_mask = float(my1 + ry0 + int(np.median(ys)))
                        heady_base = 0.60 * heady_mask + 0.40 * heady_base

        pixel_marginx = max(12, int(width * 0.20))
        pixel_marginy = max(8, int(height * 0.10))
        x1_roi = int(max(headx_base - pixel_marginx, 0))
        y1_roi = int(max(heady_base - pixel_marginy, 0))
        x2_roi = int(min(headx_base + pixel_marginx, img.shape[1]))
        y2_roi = int(min(heady_base + pixel_marginy, img.shape[0]))

        if x2_roi <= x1_roi or y2_roi <= y1_roi:
            return [(int(round(headx_base)), int(round(heady_base)), (x1_roi, y1_roi, x2_roi, y2_roi))]

        return [(int(round(headx_base)), int(round(heady_base)), (x1_roi, y1_roi, x2_roi, y2_roi))]

    def _draw_body(self, img, x1, y1, x2, y2, conf):
        """
        绻＝韬珨妾㈡脯妗嗭紙鍎寲鐗堟湰锛?        
        鍦ㄥ湒鍍忎笂绻＝韬珨妾㈡脯妗嗗拰缃俊搴︽绫わ紝浣跨敤鏇村ソ鐨勮瑕烘晥鏋溿€?        
        Args:
            img: BGR 鍦栧儚闄ｅ垪
            x1, y1: 妾㈡脯妗嗗乏涓婅搴ф
            x2, y2: 妾㈡脯妗嗗彸涓嬭搴ф
            conf: 妾㈡脯缃俊搴?        """
        # 绻＝鐭╁舰妗嗭紙钘嶈壊锛岃純绮楋級
        cv2.rectangle(img, (int(x1), int(y1)), (int(x2), int(y2)), (255, 0, 0), 2)
        
        # 绻＝瑙掓锛堜娇鍏舵洿鏄庨’锛?
        corner_len = 20
        thickness = 3
        # 宸︿笂瑙?
        cv2.line(img, (int(x1), int(y1)), (int(x1 + corner_len), int(y1)), (0, 255, 0), thickness)
        cv2.line(img, (int(x1), int(y1)), (int(x1), int(y1 + corner_len)), (0, 255, 0), thickness)
        # 鍙充笂瑙?
        cv2.line(img, (int(x2), int(y1)), (int(x2 - corner_len), int(y1)), (0, 255, 0), thickness)
        cv2.line(img, (int(x2), int(y1)), (int(x2), int(y1 + corner_len)), (0, 255, 0), thickness)
        # 宸︿笅瑙?
        cv2.line(img, (int(x1), int(y2)), (int(x1 + corner_len), int(y2)), (0, 255, 0), thickness)
        cv2.line(img, (int(x1), int(y2)), (int(x1), int(y2 - corner_len)), (0, 255, 0), thickness)
        # 鍙充笅瑙?
        cv2.line(img, (int(x2), int(y2)), (int(x2 - corner_len), int(y2)), (0, 255, 0), thickness)
        cv2.line(img, (int(x2), int(y2)), (int(x2), int(y2 - corner_len)), (0, 255, 0), thickness)
        
        # 绻＝妯欑堡鑳屾櫙锛堝崐閫忔槑榛戣壊鐭╁舰锛?
        label_text = f"Body {conf:.2f}"
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 0.6
        font_thickness = 2
        (text_width, text_height), baseline = cv2.getTextSize(label_text, font, font_scale, font_thickness)
        
        # 妯欑堡浣嶇疆
        label_x1 = int(x1)
        label_y1 = int(y1) - text_height - 10
        label_x2 = int(x1) + text_width + 10
        label_y2 = int(y1)
        
        # 绻＝鑳屾櫙鐭╁舰
        cv2.rectangle(img, (label_x1, label_y1), (label_x2, label_y2), (0, 0, 0), -1)
        
        # 绻＝鏂囧瓧
        cv2.putText(img, label_text, (int(x1) + 5, int(y1) - 5), 
                   font, font_scale, (255, 255, 255), font_thickness, cv2.LINE_AA)

    def _aim_and_move(
        self,
        targets_main,
        frame,
        img,
        targets_sec=None,
        targets_trigger=None,
        trigger_img=None,
        trigger_mask=None,
        trigger_mask_roi=None,
    ):
        """
        铏曠悊鐬勬簴鍜岀Щ鍕曢倧杓?        
        绲变竴瑾垮害鍣細Main Aimbot 鍜?Sec Aimbot 鍚勮嚜浣跨敤鐛ㄧ珛鐨?Operation Mode銆?        鏀寔 Normal銆丼ilent銆丯CAF銆乄indMouse 鍥涚ó妯″紡銆?        
        Args:
            targets_main: Main Aimbot target list
            frame: 瑕栭牷骞€鐗╀欢
            img: BGR 鍦栧儚闄ｅ垪
            targets_sec: Secondary Aimbot target list
            targets_trigger: Triggerbot target list
            trigger_img: Source frame for Triggerbot detection (without overlay drawings)
            trigger_mask: Raw HSV mask of ``trigger_img`` from the current frame
            trigger_mask_roi: ROI ``trigger_mask`` was produced from, if any
        """
        try:
            process_normal_mode(
                targets_main,
                frame,
                img,
                self,
                targets_sec=targets_sec,
                targets_trigger=targets_trigger,
                trigger_img=trigger_img,
                trigger_mask=trigger_mask,
                trigger_mask_roi=trigger_mask_roi,
            )
        except Exception as e:
            print("[Aim dispatch error]", e)


if __name__ == "__main__":
    """
    涓荤▼搴忓叆鍙?    
    鍒濆鍖栨墍鏈夊繀瑕佺殑绲勪欢涓﹀暉鍕曟噳鐢ㄧ▼寮忥細
    1. 鍒濆鍖?Capture Service
    2. 鍓靛缓 AimTracker 瀵︿緥
    3. 瑷疆 UI 澶栬
    4. 鍓靛缓涓﹀暉鍕?UI 鎳夌敤
    """
    import customtkinter as ctk
    from src.ui import ViewerApp

    # OpenCV's own thread pool competes with the capture/decode/track threads for
    # the same cores; on small ROIs it usually makes p95 worse. 0 keeps OpenCV's
    # default, which is the rollback value.
    try:
        _cv_threads = int(getattr(config, "cv2_num_threads", 0))
        if _cv_threads > 0:
            cv2.setNumThreads(_cv_threads)
    except Exception:
        pass
    
    # 鍒濆鍖栨崟鐛叉湇鍕?
    capture_service = CaptureService()
    
    # 鍓靛缓涓€鍊嬭嚚鏅傛噳鐢ㄥ渚嬬敤鏂?AimTracker
    class TempApp:
        """鑷ㄦ檪鎳夌敤椤?"""
        def __init__(self, capture):
            self.capture = capture
    
    temp_app = TempApp(capture_service)
    
    # 創建 AimTracker (use config value if available)
    target_fps = getattr(config, "target_fps", 200)
    tracker = AimTracker(app=temp_app, target_fps=target_fps)
    
    # 設置外觀
    ctk.set_appearance_mode("Dark")
    try:
        config.load_from_file()
    except Exception:
        pass
    base_dir = os.path.dirname(os.path.abspath(__file__))
    theme_name = getattr(config, "ui_theme", "nord")
    theme_file = os.path.join(base_dir, "themes", f"{theme_name}.json")
    if not os.path.exists(theme_file):
        theme_file = os.path.join(base_dir, "themes", "metal.json")
    try:
        ctk.set_default_color_theme(theme_file)
    except Exception:
        pass
    
    # 鍓靛缓 UI 鎳夌敤
    app = ViewerApp(tracker=tracker, capture_service=capture_service)
    
    # 鏇存柊 tracker 鐨?app 寮曠敤
    tracker.app = app
    
    # 杓夊叆涓︽噳鐢ㄩ厤缃紙纰轰繚鎵€鏈夎ō缃兘姝ｇ⒑锛?
    config.load_from_file()
    app._sync_config_to_tracker()
    
    print("[Main] Application initialized")
    
    # Print version info
    from src.utils.updater import get_update_checker
    updater = get_update_checker()
    print(f"[Main] Current version: v{updater.get_current_version()}")
    
    app.protocol("WM_DELETE_WINDOW", app._on_close)
    
    # Update check disabled per user configuration
    # app.after(2000, app._check_for_updates)
    
    app.mainloop()


