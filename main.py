import threading
import queue
import time
import math
import numpy as np
import cv2
import ctypes
import sys
import os

# AppUserModelID is a STABLE identity, deliberately NOT version-tagged.
# Including the version made Windows treat every release as a new app and create
# a duplicate taskbar icon / pinned entry that the user then had to clean up.
try:
    myappid = 'mycompany.colorbot'
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
except Exception:
    pass

from src.utils.config import config
from src.utils.mouse import Mouse, is_button_pressed
from src.utils.activation import get_active_aim_fov, get_active_trigger_fov
from src.utils.detection import load_model, perform_detection
from src.capture.capture_service import CaptureService
from src.aim_system.normal import process_normal_mode
from src.aim_system.anti_smoke_detector import AntiSmokeDetector
from src.aim_system.target_smoother import TargetSmoother

class FrameInfo:
    """绨″柈鐨勫箑淇℃伅椤烇紝鐢ㄦ柤鍏煎鐝炬湁浠ｇ⒓"""
    def __init__(self, width, height):
        self.xres = width
        self.yres = height

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
        # Real schema key now (config.py defines it). Never a phantom 1000.
        self.max_speed = float(getattr(config, "max_speed", 6000.0))

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
        self._move_thread = threading.Thread(target=self._process_move_queue, daemon=True)
        self._move_thread.start()
        # Flick V2 diagnostics published once per frame (see mode_flick).
        self.flick_status = {}
        # While a calibration session is open, the aim pipeline must not push
        # track/flick commands: the queue drops them anyway, and the impulse has
        # to be measured without any competing motion (plan 7.4 / C2).
        self.calibration_session = False
        # Preview throttling: imshow + waitKey on every 144-200 Hz frame meant up
        # to 600 GUI calls per second. A debug window needs 30.
        self._preview_last_time = 0.0

        self.model, self.class_names = load_model()
        print("Classes:", self.class_names)
        self._target_fps = target_fps
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
        self._target_smoother = TargetSmoother(
            ema_alpha=self.ema_alpha,
            switch_confirm_frames=self.switch_confirm_frames,
        )
        self.last_target = None
        self.stable_candidate = None
        self.stable_count = 0
        

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

    def _process_move_queue(self):
        """
        铏曠悊绉诲嫊闅婂垪
        
        鍦ㄥ緦鍙扮窔绋嬩腑鎸佺簩寰炵Щ鍕曢殜鍒椾腑鐛插彇绉诲嫊鎸囦护涓﹀煼琛屻€?        鏀寔寤堕伈鎺у埗锛岀⒑淇濈Щ鍕曟搷浣滅殑骞虫粦鍩疯銆?        
        閫欐槸涓€鍊嬬劇闄愬惊鐠帮紝鐩村埌绶氱▼琚祩姝€?        """
        while not self._stop_event.is_set() or not self.move_queue.empty():
            try:
                dx, dy, delay, tag = self._unpack_move_item(self.move_queue.get(timeout=0.1))
                per_tag = bool(getattr(config, "move_queue_per_tag_dispatch", True))
                latest_only = bool(getattr(config, "aim_latest_frame_priority", True))

                if not latest_only and not per_tag:
                    # Historical behaviour: one command at a time, as queued.
                    self._dispatch_move(dx, dy)
                    if delay > 0:
                        time.sleep(delay)
                    continue

                pending = [(dx, dy, delay, tag)]
                while True:
                    try:
                        pending.append(self._unpack_move_item(self.move_queue.get_nowait()))
                    except queue.Empty:
                        break

                max_batch = max(
                    1,
                    int(getattr(config, "move_queue_merge_batch", self._move_batch_size)),
                )

                if not per_tag:
                    # Rollback path: keep the old cross-tag merge behind the flag.
                    merged_dx, merged_dy, merged_delay = self._merge_all_tags(
                        pending, max_batch
                    )
                    self._dispatch_move(merged_dx, merged_dy)
                    if merged_delay > 0:
                        time.sleep(merged_delay)
                    continue

                groups = self._group_move_items(pending)
                sent_delay = self._dispatch_groups(groups, max_batch)
                if sent_delay > 0:
                    time.sleep(sent_delay)
            except queue.Empty:
                time.sleep(0.001)
                continue
            except Exception as e:
                print(f"[Move Queue Error] {e}")
                time.sleep(0.01)

    def _dispatch_move(self, dx, dy):
        """Send one command, swallowing backend errors (queue must keep running)."""
        try:
            if float(dx) != 0.0 or float(dy) != 0.0:
                self.controller.move(dx, dy)
                return True
        except Exception as e:
            print("[Mouse.move error]", e)
        return False

    @staticmethod
    def _merge_all_tags(pending, max_batch):
        """Legacy cross-tag merge (only used when the rollback flag is off)."""
        order = []
        for item in pending:
            if item[3] not in order:
                order.append(item[3])
        merged_dx = 0.0
        merged_dy = 0.0
        merged_delay = None
        for item_tag in order:
            group = [it for it in pending if it[3] == item_tag]
            if item_tag in ("track", "rcs") and len(group) > max_batch:
                group = group[-max_batch:]
            for item in group:
                merged_dx += float(item[0])
                merged_dy += float(item[1])
                item_delay = max(0.0, float(item[2]))
                merged_delay = (
                    item_delay if merged_delay is None else min(merged_delay, item_delay)
                )
        return merged_dx, merged_dy, (merged_delay if merged_delay is not None else 0.0)

    @staticmethod
    def _group_move_items(pending):
        """``tag -> [(dx, dy, delay), ...]`` preserving first-seen tag order."""
        groups = {}
        for item in pending:
            item_dx, item_dy, item_delay, item_tag = item
            groups.setdefault(str(item_tag), []).append(
                (float(item_dx), float(item_dy), max(0.0, float(item_delay)))
            )
        return groups

    def _dispatch_groups(self, groups, max_batch):
        """Send one command per tag; returns the single delay to sleep afterwards.

        ``calib`` wins outright: every other group is dropped WITH A LOG rather
        than folded in. Items already popped from the queue cannot be pushed back
        at the head, and mixing a stray tracking step into a calibration impulse
        is exactly what made the measurement wrong.
        """
        if not groups:
            return 0.0

        delay = 0.0

        if "calib" in groups:
            items = groups["calib"]
            total_x = sum(item[0] for item in items)
            total_y = sum(item[1] for item in items)
            delay = min((item[2] for item in items), default=0.0)
            dropped = sum(len(other) for tag, other in groups.items() if tag != "calib")
            if dropped:
                print(f"[MoveQueue] dropped {dropped} non-calib items during calibration")
            self._dispatch_move(total_x, total_y)
            return delay

        # Impulses first: a flick must land before the tracking correction that
        # was produced from the same frame.
        order = [tag for tag in groups if tag == "flick"]
        order += [tag for tag in groups if tag not in ("flick", "calib")]

        for tag in order:
            items = groups[tag]
            if tag in ("track", "rcs") and len(items) > max_batch:
                items = items[-max_batch:]
            total_x = sum(item[0] for item in items)
            total_y = sum(item[1] for item in items)
            tag_delay = min((item[2] for item in items), default=0.0)
            delay = tag_delay if delay <= 0.0 else min(delay, tag_delay)
            self._dispatch_move(total_x, total_y)
        return delay

    @staticmethod
    def _unpack_move_item(item):
        """Accept both tagged ``(dx, dy, delay, tag)`` and legacy 3-tuples."""
        try:
            length = len(item)
        except TypeError:
            raise ValueError(f"invalid move queue item: {item!r}")
        if length >= 4:
            return item[0], item[1], item[2], item[3]
        if length == 3:
            return item[0], item[1], item[2], "track"
        raise ValueError(f"invalid move queue item: {item!r}")

    def _clip_movement(self, dx, dy):
        """
        Clamp a movement request to the configured budget.

        The WHOLE vector is scaled so its magnitude fits ``max_speed``; direction
        is preserved. Clipping each axis independently (the old ``np.clip``) bends
        every oversized diagonal towards 45 degrees and truncates flick impulses
        without changing their direction of error.

        Args:
            dx: X movement (mouse counts)
            dy: Y movement (mouse counts)

        Returns:
            tuple: (clipped_dx, clipped_dy)
        """
        limit = abs(float(getattr(self, "max_speed", 0.0) or 0.0))
        dx_f = float(dx)
        dy_f = float(dy)
        if limit <= 0.0:
            return dx_f, dy_f
        magnitude = math.hypot(dx_f, dy_f)
        if magnitude <= limit or magnitude <= 1e-12:
            return dx_f, dy_f
        scale = limit / magnitude
        return dx_f * scale, dy_f * scale

    def _track_loop(self):
        """
        Main tracking loop with high-precision Windows timer and monotonic clock.
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
            while not self._stop_event.is_set():
                period = 1.0 / float(self._target_fps)
                start = time.perf_counter()
                try:
                    self.track_once()
                except Exception as e:
                    print("[Track error]", e)
                elapsed = time.perf_counter() - start
                to_sleep = period - elapsed
                if to_sleep > 0.0005:
                    time.sleep(to_sleep)
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
    
    def _handle_button_mask(self):
        """
        铏曠悊鎸夐垥閬僵閭忚集
        
        鏍规摎閰嶇疆姹哄畾鏄惁閹栧畾鐗瑰畾鐨勬粦榧犳寜閳曪紝闃叉鍦ㄧ瀯婧栨檪瑾よЦ銆?        """
        # 濡傛灉鏈暉鐢?Button Mask锛岃В閹栨墍鏈夋寜閳?
        if not getattr(config, "button_mask_enabled", False):
            try:
                from src.utils.mouse import unlock_all_locks
                unlock_all_locks()
            except Exception as e:
                pass
            return
        
        # 妾㈡煡鏄惁鏈変换浣?aimbot 姝ｅ湪閬嬭
        aimbot_running = (
            getattr(config, "enableaim", False) or 
            getattr(config, "enableaim_sec", False) or 
            getattr(config, "enabletb", False)
        )
        
        if not aimbot_running:
            try:
                from src.utils.mouse import unlock_all_locks
                unlock_all_locks()
            except Exception as e:
                pass
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
            
        except Exception as e:
            print(f"[Button Mask Error] {e}")

    def _draw_fovs(self, img, frame):
        """
        绻＝ FOV锛堣閲庣瘎鍦嶏級鍦撳湀
        
        鍦ㄥ湒鍍忎笂绻＝ Aimbot 鍜?Triggerbot 鐨?FOV 绡勫湇鍦撳湀锛?        鐢ㄦ柤瑕栬鍖栭’绀虹瀯婧栧拰瑙哥櫦鍗€鍩熴€?        
        Args:
            img: BGR 鍦栧儚闄ｅ垪
            frame: 瑕栭牷骞€鐗╀欢锛屽寘鍚В鏋愬害淇℃伅
        """
        center_x = int(frame.xres / 2)
        center_y = int(frame.yres / 2)
        if getattr(config, "enableaim", False):
            mode_main = getattr(config, "mode", "Normal")
            # 鍦?NCAF 涓嬩笉鐣師鏈?FOV 鍦擄紝鍙’绀?NCAF 鍗婂緫
            if mode_main != "NCAF":
                main_fov = int(get_active_aim_fov(is_sec=False, fallback=self.fovsize))
                cv2.circle(img, (center_x, center_y), main_fov, (255, 255, 255), 2)
                # Correct: cercle smoothing = normalsmoothFOV
                cv2.circle(img, (center_x, center_y), int(getattr(config, "normalsmoothfov", self.normalsmoothfov)), (51, 255, 255), 2)
            # NCAF Radius 鍦?(Main)
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
                cv2.imshow(self.RAW_STREAM_NDI_WINDOW, raw_img)
                self._raw_stream_window_visible[self.RAW_STREAM_NDI_WINDOW] = True
            elif self._raw_stream_window_visible.get(self.RAW_STREAM_NDI_WINDOW, False):
                cv2.destroyWindow(self.RAW_STREAM_NDI_WINDOW)
                self._raw_stream_window_visible[self.RAW_STREAM_NDI_WINDOW] = False
        except Exception:
            pass

        try:
            if show_udp:
                cv2.imshow(self.RAW_STREAM_UDP_WINDOW, raw_img)
                self._raw_stream_window_visible[self.RAW_STREAM_UDP_WINDOW] = True
            elif self._raw_stream_window_visible.get(self.RAW_STREAM_UDP_WINDOW, False):
                cv2.destroyWindow(self.RAW_STREAM_UDP_WINDOW)
                self._raw_stream_window_visible[self.RAW_STREAM_UDP_WINDOW] = False
        except Exception:
            pass

        if show_ndi or show_udp:
            try:
                cv2.waitKey(1)
            except Exception:
                pass

    def _close_raw_stream_windows(self):
        """Close raw-stream windows."""
        try:
            if self._raw_stream_window_visible.get(self.RAW_STREAM_NDI_WINDOW, False):
                cv2.destroyWindow(self.RAW_STREAM_NDI_WINDOW)
                self._raw_stream_window_visible[self.RAW_STREAM_NDI_WINDOW] = False
        except Exception:
            pass
        try:
            if self._raw_stream_window_visible.get(self.RAW_STREAM_UDP_WINDOW, False):
                cv2.destroyWindow(self.RAW_STREAM_UDP_WINDOW)
                self._raw_stream_window_visible[self.RAW_STREAM_UDP_WINDOW] = False
        except Exception:
            pass

    def _active_modes_use_smoother(self):
        """True when at least one ACTIVE aimbot mode wants temporal smoothing.

        Modes advertise ``uses_smoother`` via ``mode_dispatcher.get_mode_caps``.
        Flick/Silent are one-shot: smoothing their door-knock target means aiming
        at the past with no chance to correct.
        """
        try:
            from src.aim_system.mode_dispatcher import mode_uses_smoother

            modes = []
            if getattr(config, "enableaim", False):
                modes.append(getattr(config, "mode", "Normal"))
            if getattr(config, "enableaim_sec", False):
                modes.append(getattr(config, "mode_sec", "Normal"))
            if not modes:
                return True
            return any(mode_uses_smoother(mode) for mode in modes)
        except Exception:
            return True

    def _preview_due(self):
        """True at most ``ui_preview_max_fps`` times per second (plan H3)."""
        try:
            max_fps = max(1, int(getattr(config, "ui_preview_max_fps", 30)))
        except Exception:
            max_fps = 30
        now = time.perf_counter()
        interval = 1.0 / float(max_fps)
        if (now - self._preview_last_time) < interval:
            return False
        self._preview_last_time = now
        return True

    @staticmethod
    def _nearest_bbox(target_bboxes, tx, ty):
        """Index of the bbox whose centre is closest to ``(tx, ty)`` (plan H4)."""
        best_index = -1
        best_distance = None
        for index, item in enumerate(target_bboxes):
            try:
                bx = float(item[0][0])
                by = float(item[0][1])
            except (TypeError, ValueError, IndexError):
                continue
            distance = (bx - tx) ** 2 + (by - ty) ** 2
            if best_distance is None or distance < best_distance:
                best_distance = distance
                best_index = index
        return best_index

    def _filter_targets_with_anti_smoke(self, targets, target_bboxes, mask, frame_shape, detector):
        """Filter targets using the nearest bbox contour check from anti-smoke.

        ``is_bbox_plausible`` runs ``findContours`` + ``convexHull`` on an ROI, so
        the previous implementation was O(targets x bboxes) plus a contour per
        target per frame. The bbox lookup is hoisted out of the loop, the nearest
        bbox is computed in one pass, and the verdict is cached per
        ``(bbox, detector, mask)`` version (plan H4).
        """
        if not targets or not target_bboxes or detector is None:
            return targets
        try:
            if not detector.is_enabled() or mask is None:
                return targets
        except Exception:
            return targets

        # Per-frame cache: one contour check per distinct bbox, not per target.
        verdicts = getattr(self, "_anti_smoke_verdicts", None)
        frame_key = id(mask)
        if verdicts is None or verdicts.get("mask") != frame_key or verdicts.get("detector") != id(detector):
            verdicts = {"mask": frame_key, "detector": id(detector), "verdict": {}}
            self._anti_smoke_verdicts = verdicts
        cache = verdicts["verdict"]

        filtered_targets = []
        for target in targets:
            if len(target) < 2:
                continue
            tx, ty = float(target[0]), float(target[1])
            index = self._nearest_bbox(target_bboxes, tx, ty)
            if index < 0:
                continue
            bbox = target_bboxes[index][1]
            key = (
                int(bbox[0]),
                int(bbox[1]),
                int(bbox[2]),
                int(bbox[3]),
            )
            plausible = cache.get(key)
            if plausible is None:
                try:
                    plausible = bool(detector.is_bbox_plausible(bbox, mask, frame_shape))
                except Exception:
                    plausible = True
                cache[key] = plausible
            if plausible:
                filtered_targets.append(target)
        return filtered_targets

    def track_once(self):
        """
        鍩疯涓€娆″畬鏁寸殑杩借工铏曠悊
        
        閫欐槸杩借工鍣ㄧ殑鏍稿績鏂规硶锛屽煼琛屼互涓嬫椹燂細
        1. 妾㈡煡閫ｆ帴鐙€鎱?        2. 铏曠悊 Button Mask
        3. 鎹曠嵅鐣跺墠瑕栭牷骞€
        4. 鍩疯鐩妾㈡脯
        5. 铏曠悊妾㈡脯绲愭灉涓︿及绠楅牠閮ㄤ綅缃?        6. 绻＝ FOV 鍜岀洰妯欐瑷?        7. 鍩疯鐬勬簴鍜岀Щ鍕曢倧杓?        8. 椤ず妾㈡脯绲愭灉绐楀彛
        """
        if not self.app.capture.is_connected():
            self._close_raw_stream_windows()
            return

        # Button Mask 绠＄悊
        self._handle_button_mask()
        
        # Mouse Lock 绠＄悊鍣?tick
        try:
            from src.utils.mouse import tick_movement_lock_manager
            tick_movement_lock_manager()
        except Exception:
            pass

        # 浣跨敤 CaptureService 璁€鍙?BGR 骞€
        raw_bgr_img = self.app.capture.read_frame(apply_fov=False)
        if raw_bgr_img is None:
            return

        # 纰轰繚鍦栧儚鏄€ｇ簩涓斿彲瀵殑鏁哥祫锛屼互閬垮厤 OpenCV 閷
        if not raw_bgr_img.flags['C_CONTIGUOUS']:
            raw_bgr_img = np.ascontiguousarray(raw_bgr_img)

        self._update_raw_stream_windows(raw_bgr_img)

        bgr_img = self.app.capture.apply_mode_fov(raw_bgr_img)
        if bgr_img is None:
            return
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
        # Throttle the GUI work: at 200 FPS the old code issued three imshow +
        # waitKey per frame (~600 GUI calls/s) plus a full frame copy each time.
        preview_due = self._preview_due() if show_detection else False

        # Zero-copy optimization: only clone frame if we need to draw debug overlays
        if show_detection:
            trigger_source_img = bgr_img.copy()
        else:
            trigger_source_img = bgr_img

        try:
            detection_results, mask = perform_detection(self.model, bgr_img)
            # 椤ず MASK 瑕栫獥锛堝鏋滃暉鐢級
            if (preview_due and
                getattr(config, "show_opencv_windows", True) and 
                getattr(config, "show_opencv_mask", True) and 
                mask is not None):
                cv2.imshow("MASK", mask)
                cv2.waitKey(1)
        except Exception as e:
            print("[perform_detection error]", e)
            detection_results = []
            mask = None
            # 鍗充娇妾㈡脯澶辨晽锛屼篃椤ず鍘熷鍦栧儚锛堝鏋滃暉鐢級
            if preview_due:
                try:
                    cv2.imshow("Detection", bgr_img)
                    cv2.waitKey(1)
                except:
                    pass

        targets = []
        target_bboxes = []
        if detection_results:
            # 鐛插彇鐣跺墠 aim_type锛圡ain Aimbot锛?
            aim_type = getattr(config, "aim_type", "head")
            frame_area = max(1, int(frame.xres) * int(frame.yres))
            dynamic_min_area = int(
                getattr(
                    config,
                    "min_detection_bbox_area",
                    max(120, int(frame_area * 0.0015)),
                )
            )
            if str(getattr(config, "detection_morph_mode", "legacy")).strip().lower() != "stable":
                dynamic_min_area = min(dynamic_min_area, max(40, int(frame_area * 0.00035)))
            
            for det in detection_results:
                try:
                    x, y, w, h = det['bbox']
                    conf = det.get('confidence', 1.0)
                    if int(w) <= 0 or int(h) <= 0:
                        continue
                    # Ignore tiny blobs to reduce per-frame target flicker.
                    if int(w) * int(h) < dynamic_min_area:
                        continue
                    x1, y1 = int(x), int(y)
                    x2, y2 = int(x + w), int(y + h)
                    # Dessin corps (only if preview active)
                    if show_detection:
                        self._draw_body(bgr_img, x1, y1, x2, y2, conf)
                    
                    # 瑷堢畻 body 鐨勪腑蹇冮粸鍜?Y 绡勫湇
                    body_cx = (x1 + x2) / 2.0
                    body_cy = (y1 + y2) / 2.0
                    body_y_min = y1  # body 鐨?Y 杌告渶楂樺€硷紙鍦栧儚搴ф绯讳腑 y 瓒婂皬瓒婇潬涓婏級
                    body_y_max = y2  # body 鐨?Y 杌告渶浣庡€?                    
                    # Estimation t锚tes dans la bbox
                    head_positions = self._estimate_head_positions(
                        x1, y1, x2, y2, bgr_img, mask, draw=show_detection
                    )
                    
                    if aim_type == "body":
                        # Body 妯″紡锛氫娇鐢?body 涓績榛?
                        d = math.hypot(body_cx - frame.xres / 2.0, body_cy - frame.yres / 2.0)
                        target_tuple = (body_cx, body_cy, d, None, None)
                        targets.append(target_tuple)  # 鏈€寰屽叐鍊嬪弮鏁哥偤 head_y_min, body_y_max锛坆ody 妯″紡涓嶉渶瑕侊級
                        target_bboxes.append(((body_cx, body_cy), (x1, y1, int(w), int(h))))
                    else:
                        # Head 鎴?Nearest 妯″紡锛氫娇鐢?head 浣嶇疆
                        for head_cx, head_cy, bbox in head_positions:
                            if show_detection:
                                self._draw_head_bbox(bgr_img, head_cx, head_cy)
                            d = math.hypot(head_cx - frame.xres / 2.0, head_cy - frame.yres / 2.0)
                            
                            # 瑷堢畻 head 鐨?Y 绡勫湇锛堢敤鏂?nearest 妯″紡锛?
                            # head_y_min 鏄?head 鐨勬渶楂?Y 鍊硷紙鏈€灏忕殑 y锛屽湪鍦栧儚搴ф绯讳腑锛?
                            # 浣跨敤 head_cy 娓涘幓涓€鍊嬩及绠楃殑 head 鍗婇珮锛堢磩 15 鍍忕礌锛?
                            estimated_head_height = 30  # 浼扮畻 head 楂樺害
                            head_y_min = head_cy - estimated_head_height // 2  # head 鏈€楂?Y 鍊?                            
                            if aim_type == "nearest":
                                # Nearest 妯″紡锛氫繚瀛?Y 绡勫湇淇℃伅
                                target_tuple = (head_cx, head_cy, d, head_y_min, body_y_max)
                            else:  # head 妯″紡
                                target_tuple = (head_cx, head_cy, d, None, None)
                            targets.append(target_tuple)
                            target_bboxes.append(((head_cx, head_cy), (x1, y1, int(w), int(h))))
                except Exception as e:
                    print("Erreur dans _estimate_head_positions:", e)

        targets_raw = list(targets) if targets else []
        use_temporal_smoothing = bool(getattr(config, "enable_target_temporal_smoothing", True))
        if use_temporal_smoothing and not self._active_modes_use_smoother():
            # Every active mode is one-shot/open-loop (e.g. Flick): aim at the RAW
            # position of the current frame. An EMA plus a 3-frame switch hold
            # makes a single impulse fire at where the target USED to be, and there
            # is no second measurement to correct it.
            use_temporal_smoothing = False
            self._target_smoother.reset()
        if targets_raw and use_temporal_smoothing:
            targets_smoothed = self._target_smoother.stabilize(targets_raw, frame.xres / 2.0, frame.yres / 2.0)
            self.last_target = self._target_smoother.last_target
            self.stable_candidate = self._target_smoother.stable_candidate
            self.stable_count = self._target_smoother.stable_count
        else:
            targets_smoothed = list(targets_raw)

        # Finding 103: dispatch raw vs smoothed target lists per mode so open-loop modes
        # like Flick Aim are never contaminated by EMA delay when another mode uses smoothing.
        try:
            from src.aim_system.mode_dispatcher import mode_uses_smoother
            main_mode = getattr(config, "mode", "Normal")
            sec_mode = getattr(config, "mode_sec", "Normal")
            targets_main = list(targets_smoothed if (use_temporal_smoothing and mode_uses_smoother(main_mode)) else targets_raw)
            targets_sec = list(targets_smoothed if (use_temporal_smoothing and mode_uses_smoother(sec_mode)) else targets_raw)
        except Exception:
            targets_main = list(targets_smoothed)
            targets_sec = list(targets_smoothed)

        targets_all = targets_smoothed if use_temporal_smoothing else targets_raw
        if target_bboxes:
            frame_shape = bgr_img.shape
            if targets_main:
                targets_main = self._filter_targets_with_anti_smoke(
                    targets_main, target_bboxes, mask, frame_shape, self.anti_smoke_detector
                )
            if targets_sec:
                targets_sec = self._filter_targets_with_anti_smoke(
                    targets_sec, target_bboxes, mask, frame_shape, self.anti_smoke_detector_sec
                )

        # FOVs once per frame only if preview is enabled
        if show_detection:
            try:
                self._draw_fovs(bgr_img, frame)
            except Exception:
                pass

        try:
            self._aim_and_move(
                targets_main,
                frame,
                bgr_img,
                targets_sec=targets_sec,
                targets_trigger=targets_all,
                trigger_img=trigger_source_img,
            )
        except Exception as e:
            print("[Aim error]", e)

        # 椤ず Detection 瑕栫獥锛堟牴鎿氳ō缃級
        if preview_due:
            try:
                # 鍎寲绻＝锛氭坊鍔犳洿澶氳瑕轰俊鎭?
                display_img = self._draw_enhanced_detection(bgr_img.copy(), targets_all, frame)
                cv2.imshow("Detection", display_img)
                cv2.waitKey(1)
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
                if is_best:
                    target_color = (0, 0, 255)  # 绱呰壊
                    circle_radius = 8
                    thickness = -1  # 瀵﹀績
                else:
                    target_color = (255, 0, 0)  # 钘嶈壊
                    circle_radius = 5
                    thickness = 2
                
                # 绻＝鐩榛?
                cv2.circle(img, (int(tx), int(ty)), circle_radius, target_color, thickness)
                
                # 绻＝寰炰腑蹇冨埌鐩鐨勯€ｇ窔锛堝儏鏈€浣崇洰妯欙級
                if is_best:
                    cv2.line(img, (center_x, center_y), (int(tx), int(ty)), 
                            (0, 255, 0), 1, cv2.LINE_AA)
                
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
        # 澶栧湀锛堢櫧鑹诧級
        cv2.circle(img, (int(headx), int(heady)), 6, (255, 255, 255), 2)
        # 鍏у湀锛堢磪鑹诧級
        cv2.circle(img, (int(headx), int(heady)), 3, (0, 0, 255), -1)

    def _estimate_head_positions(self, x1, y1, x2, y2, img, mask=None, draw=False):
        """
        Estimate head position from body bbox geometry only.

        ``draw`` defaults to False: the ROI rectangle used to be drawn on EVERY
        frame even with the preview disabled, costing CPU and painting on the
        frame handed to the trigger source (plan H9/C7).
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
        # Geometric head ratio (0.13 = ~13% of height, dead center on eyes/nose/chin)
        base_head_ratio = float(getattr(config, "head_estimate_ratio", 0.13))
        heady_base = float(y1) + float(height) * base_head_ratio + effective_height * (offset_y / 100.0)

        # One-pass refinement from the already computed global mask.
        # Refines both X and Y to lock directly onto the true head hitbox center!
        if mask is not None:
            mx1 = max(0, min(int(x1), mask.shape[1] - 1))
            my1 = max(0, min(int(y1), mask.shape[0] - 1))
            mx2 = max(mx1 + 1, min(int(x2), mask.shape[1]))
            my2 = max(my1 + 1, min(int(y2), mask.shape[0]))
            upper_h = max(6, int((my2 - my1) * 0.35))
            upper_y2 = min(my2, my1 + upper_h)
            upper_mask = mask[my1:upper_y2, mx1:mx2]
            if upper_mask.size > 0:
                min_pixels = int(getattr(config, "head_refine_min_pixels", 12))
                # ``np.where`` + two ``median``/``min`` calls allocated several
                # arrays per detection. Column sums give the X centroid and the
                # first hit row gives the crown, both in one pass over the mask.
                column_counts = np.count_nonzero(upper_mask, axis=0)
                total = int(column_counts.sum())
                if total >= min_pixels:
                    indices = np.flatnonzero(column_counts)
                    weights = column_counts[indices]
                    weighted = int((indices * weights).sum())
                    headx_base = float(mx1 + int(round(weighted / float(total))))
                    row_counts = np.count_nonzero(upper_mask, axis=1)
                    first_row = int(np.flatnonzero(row_counts)[0])
                    head_top = float(first_row)
                    # Head center sits ~11-13% of total body height below top of crown
                    head_center_offset = max(3.0, float(height) * 0.11)
                    heady_base = float(my1) + head_top + head_center_offset
                    if offset_y != 0:
                        heady_base += effective_height * (offset_y / 100.0)

        pixel_marginx = max(12, int(width * 0.20))
        pixel_marginy = max(8, int(height * 0.10))
        x1_roi = int(max(headx_base - pixel_marginx, 0))
        y1_roi = int(max(heady_base - pixel_marginy, 0))
        x2_roi = int(min(headx_base + pixel_marginx, img.shape[1]))
        y2_roi = int(min(heady_base + pixel_marginy, img.shape[0]))

        if x2_roi <= x1_roi or y2_roi <= y1_roi:
            return [(int(round(headx_base)), int(round(heady_base)), (x1_roi, y1_roi, x2_roi, y2_roi))]

        if draw:
            cv2.rectangle(img, (x1_roi, y1_roi), (x2_roi, y2_roi), (0, 255, 255), 1)

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
    from src.version import get_version_summary
    from src.utils import single_instance

    _cli_show = "--show" in sys.argv[1:]

    # --- 1. single instance guard, BEFORE Tk/capture/mouse are allocated -----
    # A second run must not open a second window or fight for the capture device
    # and the hotkey; it signals the running instance and exits 0 (plan §8.6).
    is_first, _mutex_handle = single_instance.acquire()
    if not is_first:
        single_instance.signal_existing()
        print("[Main] Another instance is running; requested show.")
        raise SystemExit(0)

    # Load the persisted config ONCE, BEFORE AimTracker. AimTracker snapshots
    # config during __init__; loading it afterwards (as before) left the tracker
    # on defaults until _sync_config_to_tracker() ran (plan H12 / C9).
    try:
        config.load_from_file()
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
    # Config was already loaded above (before AimTracker); only push it into
    # the tracker/UI here instead of reading the file a second time.
    app._sync_config_to_tracker()

    # --- Instance watcher: a second `run.bat` shows THIS window --------------
    try:
        watcher = single_instance.InstanceWatcher(
            on_show=lambda: app._launcher_queue.put("show")
        )
        watcher.attach_event()
        watcher.start()
        app._instance_watcher = watcher
    except Exception as exc:
        print(f"[Main] instance watcher unavailable: {exc}")

    # `--show` (run.bat) forces the window forward; ui_start_hidden keeps it out
    # of the way on boot while the hotkey/tray remain reachable.
    if _cli_show:
        app.after(300, app._show_window)
    elif bool(getattr(config, "ui_start_hidden", False)):
        app.after(200, app._hide_window)
    
    print("[Main] Application initialized")
    
    # Print version info from the single source of truth (src/version.py).
    print(f"[Main] Current version: {get_version_summary()}")
    
    app.protocol("WM_DELETE_WINDOW", app._on_close)
    
    # Update check disabled per user configuration
    # app.after(2000, app._check_for_updates)
    
    try:
        app.mainloop()
    finally:
        # Never leave the mutex/event handles open, even on an abnormal exit.
        single_instance.release()


