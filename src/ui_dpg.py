"""
UI 模組 - DearPyGui GPU-Accelerated Gaming HUD (CVM colorBot)
DirectX 11 / OpenGL Hardware-Accelerated Interface
Ultra-low CPU overhead (< 0.5%), 240Hz butter-smooth window dragging, 0ms tab switching.
"""
import os
import sys
import time
import math
import queue
import threading
import numpy as np
import cv2

try:
    import dearpygui.dearpygui as dpg
except ImportError:
    dpg = None

from src.utils.config import config
from src.utils.debug_logger import get_recent_logs, log_print


# Engine/backend domains accepted by ``config`` and the runtime dispatchers.
# These tuples are a deliberate copy: ``src/ui_dpg.py`` must not import the
# private normalisers of ``src/utils`` (config owns storage, this module only
# offers the values the engine actually understands). ``tests/test_ui_dpg.py``
# asserts the combos expose exactly these tuples so a silent drift is caught.
_MODE_ITEMS = ("Normal", "Flick", "Silent", "NCAF", "WindMouse", "Bezier", "PID")
_AIM_TYPE_ITEMS = ("head", "body", "nearest")
_MOUSE_API_ITEMS = (
    "Serial",
    "Arduino",
    "SendInput",
    "Net",
    "KmboxA",
    "MakV2",
    "MakcuController",
    "MakxdMakAPI",
    "MakAPI",
    "DHZ",
    "Ferrum",
    "Medius",
)
_SERIAL_MODE_ITEMS = ("Auto", "Manual")
_CAPTURE_MODE_ITEMS = ("UDP", "NDI", "MSS", "CaptureCard", "CaptureCardGStreamer", "Teleport")

# A UDP stream whose last datagram is older than this is treated as stalled:
# the receiver's cached FPS would otherwise keep the HUD green while the feed is
# dead (same intent as the Tk HUD's starvation check).
_UDP_STALL_SECONDS = 1.0


def _finite_float(value):
    """Return ``value`` as a finite float, else ``None`` (never raises).

    Rejects ``bool``/``str``/``None`` so a stray flag or a non-numeric metric
    never reads as a measurement, but accepts any numeric type (including
    ``numpy`` scalars, which are not ``float`` subclasses).
    """
    if value is None or isinstance(value, (bool, str, bytes)):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


class DpgViewerApp:
    """
    High-Performance GPU-Accelerated UI for CVM-colorBot powered by DearPyGui (DirectX 11).
    Provides drop-in compatibility with ViewerApp (Tkinter) interface for main.py & AimTracker.
    """

    # Single source of truth for "which config key has which widget".
    # ``_cfg_tag(key)`` derives the DPG tag, ``_sync_ui_from_config()`` walks this
    # tuple to push config values back into the widgets after a profile load, an
    # F1/F5 engine hotkey or a main.py config reload.
    _CONFIG_WIDGETS = (
        ("enableaim", bool),
        ("mode", str),
        ("aim_type", str),
        ("selected_mouse_button", int),
        ("fovsize", float),
        ("normal_x_speed", float),
        ("normal_y_speed", float),
        ("wm_settle_radius_px", float),
        ("aim_offsetX", int),
        ("aim_offsetY", int),
        ("ads_fov_enabled", bool),
        ("ads_fovsize", float),
        ("normal_x_speed_sec", float),
        ("normal_y_speed_sec", float),
        ("enabletb", bool),
        ("tbfovsize", float),
        ("color", str),
        ("custom_hsv_min_h", int),
        ("custom_hsv_max_h", int),
        ("custom_hsv_min_s", int),
        ("custom_hsv_max_s", int),
        ("custom_hsv_min_v", int),
        ("custom_hsv_max_v", int),
        ("detection_min_bbox_area", int),
        ("detection_min_contour_area", int),
        ("detection_min_width", int),
        ("detection_min_height", int),
        ("ai_detection_enabled", bool),
        ("mouse_api", str),
        ("serial_port_mode", str),
        ("serial_port", str),
        ("serial_auto_switch_4m", bool),
        ("in_game_sens", float),
        ("mouse_dpi", int),
        ("capture_mode", str),
    )

    def __init__(self, tracker=None, capture_service=None):
        if dpg is None:
            raise RuntimeError("DearPyGui is not installed. Please run: pip install dearpygui")

        self.tracker = tracker
        self.capture = capture_service
        self.capture_service = capture_service

        self.preview_w = 320
        self.preview_h = 320
        self.preview_enabled = False
        self.texture_tag = None

        self._scheduled_callbacks = []
        self._callback_lock = threading.Lock()
        self._running = False
        self._closed = False
        self._close_handlers = []
        self._runtime_active = False
        self._runtime_busy = False

        # Frame publish diagnostics: only the first failure is logged, so a
        # persistent 144 Hz error cannot flood the console.
        self._preview_error_count = 0

        # Telemetry history for GPU plot (last 100 frames)
        self.max_plot_pts = 100
        self.plot_x = list(range(self.max_plot_pts))
        self.plot_latency = [0.0] * self.max_plot_pts
        self.plot_fps = [0.0] * self.max_plot_pts
        self._last_telemetry_time = time.time()
        self._last_frame_seq = 0
        # Only measured latencies feed the AVG label; the pre-filled plot window
        # is placeholder data, not a sample.
        self._latency_history = []
        self._telemetry_error_logged = False

        # Build DPG context & viewport
        dpg.create_context()
        self._setup_theme()
        self._build_textures()
        self._build_gui()

        # The window opens already matching ``config``: main.py reloads the
        # profile *after* the UI is built, and the hotkey path only syncs later,
        # so without this pass the HUD would sit on its INITIALIZING badge until
        # the first interaction. Pure read-and-display: no save, no tracker.
        self._sync_ui_from_config()

        # Auto-connect mouse and capture if enabled (matching ViewerApp)
        self.after(500, self._maybe_auto_start_runtime)

    def _setup_theme(self):
        """Configure sleek dark gaming palette (DirectX 11 Tactical HUD)."""
        with dpg.theme() as global_theme:
            with dpg.theme_component(dpg.mvAll):
                # Dark Modern Canvas
                dpg.add_theme_color(dpg.mvThemeCol_WindowBg, (15, 17, 23, 255))
                dpg.add_theme_color(dpg.mvThemeCol_ChildBg, (20, 24, 34, 255))
                dpg.add_theme_color(dpg.mvThemeCol_PopupBg, (20, 24, 34, 255))
                dpg.add_theme_color(dpg.mvThemeCol_Border, (40, 48, 65, 255))
                dpg.add_theme_color(dpg.mvThemeCol_FrameBg, (26, 32, 45, 255))
                dpg.add_theme_color(dpg.mvThemeCol_FrameBgHovered, (35, 43, 60, 255))
                dpg.add_theme_color(dpg.mvThemeCol_FrameBgActive, (45, 55, 75, 255))
                dpg.add_theme_color(dpg.mvThemeCol_TitleBg, (12, 14, 20, 255))
                dpg.add_theme_color(dpg.mvThemeCol_TitleBgActive, (20, 24, 34, 255))

                # Accents: Emerald Green & Sky Cyan
                dpg.add_theme_color(dpg.mvThemeCol_CheckMark, (56, 189, 248, 255))
                dpg.add_theme_color(dpg.mvThemeCol_SliderGrab, (56, 189, 248, 255))
                dpg.add_theme_color(dpg.mvThemeCol_SliderGrabActive, (14, 165, 233, 255))
                dpg.add_theme_color(dpg.mvThemeCol_Button, (30, 41, 59, 255))
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (51, 65, 85, 255))
                dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (71, 85, 105, 255))
                dpg.add_theme_color(dpg.mvThemeCol_Header, (30, 41, 59, 255))
                dpg.add_theme_color(dpg.mvThemeCol_HeaderHovered, (51, 65, 85, 255))
                dpg.add_theme_color(dpg.mvThemeCol_HeaderActive, (71, 85, 105, 255))
                dpg.add_theme_color(dpg.mvThemeCol_Tab, (20, 24, 34, 255))
                dpg.add_theme_color(dpg.mvThemeCol_TabHovered, (35, 43, 60, 255))
                dpg.add_theme_color(dpg.mvThemeCol_TabActive, (37, 46, 66, 255))
                dpg.add_theme_color(dpg.mvThemeCol_Text, (241, 245, 249, 255))
                dpg.add_theme_color(dpg.mvThemeCol_TextDisabled, (148, 163, 184, 255))

                # Smooth geometry
                dpg.add_theme_style(dpg.mvStyleVar_WindowRounding, 8)
                dpg.add_theme_style(dpg.mvStyleVar_ChildRounding, 6)
                dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 4)
                dpg.add_theme_style(dpg.mvStyleVar_PopupRounding, 6)
                dpg.add_theme_style(dpg.mvStyleVar_GrabRounding, 4)
                dpg.add_theme_style(dpg.mvStyleVar_TabRounding, 4)
                dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 10, 10)
                dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 8, 4)
                dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 8, 8)

        dpg.bind_theme(global_theme)

    def _build_textures(self):
        """Create hardware textures for camera and preview."""
        with dpg.texture_registry(show=False):
            init_data = np.zeros((self.preview_h, self.preview_w, 4), dtype=np.float32)
            init_data[:, :, 0:3] = 0.08
            init_data[:, :, 3] = 1.0
            self.texture_tag = dpg.add_raw_texture(
                width=self.preview_w,
                height=self.preview_h,
                default_value=init_data,
                format=dpg.mvFormat_Float_rgba,
            )

    def _build_gui(self):
        """Construct the DPG window and tabs matching Demo 2 (ImGui Tactical HUD)."""
        dpg.create_viewport(
            title="CVM-colorBot — Demo 2: DearPyGui / ImGui (GPU 240 FPS HUD)",
            width=760,
            height=700,
            min_width=640,
            min_height=520,
        )

        with dpg.window(tag="PrimaryWindow"):
            # Header status bar matching Demo 2
            with dpg.group(horizontal=True):
                dpg.add_text("●", color=(56, 189, 248))
                dpg.add_text("[IMGUI] TACTICAL HUD", color=(56, 189, 248))
                dpg.add_text("•", color=(80, 80, 100))
                dpg.add_text("D3D11 • 240 FPS", color=(148, 163, 184))
                dpg.add_spacer(width=20)
                dpg.add_button(
                    label="[▶ START RUNTIME]",
                    tag="btn_runtime_toggle",
                    callback=self._toggle_runtime,
                )
                dpg.add_text("STATUS: INITIALIZING...", tag="txt_status_badge", color=(251, 191, 36))

            dpg.add_separator()

            with dpg.tab_bar(tag="main_tab_bar"):
                # TAB 1: AIMBOT
                with dpg.tab(label="AIMBOT"):
                    self._build_combat_tab()

                # TAB 2: COLOR_HSV
                with dpg.tab(label="COLOR_HSV"):
                    self._build_vision_tab()

                # TAB 3: SERIAL_IO
                with dpg.tab(label="SERIAL_IO"):
                    self._build_hardware_tab()

                # TAB 4: GRAPHS
                with dpg.tab(label="GRAPHS"):
                    self._build_telemetry_tab()

                # TAB 5: PROFILES
                with dpg.tab(label="PROFILES"):
                    self._build_profiles_tab()

        dpg.set_primary_window("PrimaryWindow", True)
        dpg.setup_dearpygui()

    def _build_combat_tab(self):
        with dpg.child_window(border=False):
            # Card 1: Primary Aimbot Control
            with dpg.child_window(border=True, auto_resize_y=True):
                with dpg.group(horizontal=True):
                    dpg.add_checkbox(
                        label="Active Primary Aim",
                        tag=self._cfg_tag("enableaim"),
                        default_value=bool(getattr(config, "enableaim", True)),
                        callback=self._make_config_cb("enableaim", bool),
                    )
                    dpg.add_spacer(width=20)
                    dpg.add_text("ENGINE:", color=(148, 163, 184))
                    dpg.add_combo(
                        items=list(_MODE_ITEMS),
                        tag=self._cfg_tag("mode"),
                        default_value=str(getattr(config, "mode", "WindMouse")),
                        width=140,
                        callback=self._make_config_cb("mode", str),
                    )
                    dpg.add_text("BONE:", color=(148, 163, 184))
                    dpg.add_combo(
                        items=list(_AIM_TYPE_ITEMS),
                        tag=self._cfg_tag("aim_type"),
                        default_value=str(getattr(config, "aim_type", "head")),
                        width=110,
                        callback=self._make_config_cb("aim_type", str),
                    )

                with dpg.group(horizontal=True):
                    dpg.add_text("Activation Key:", color=(148, 163, 184))
                    dpg.add_combo(
                        items=["Left Mouse", "Right Mouse", "Side Mouse 4", "Side Mouse 5"],
                        tag=self._cfg_tag("selected_mouse_button"),
                        default_value=self._get_btn_name(getattr(config, "selected_mouse_button", 4)),
                        width=180,
                        callback=self._cb_aim_btn,
                    )

            dpg.add_spacer(height=4)

            # Card 2: FOV Radial Radius
            with dpg.child_window(border=True, auto_resize_y=True):
                dpg.add_text("FOV RADIAL RADIUS", color=(56, 189, 248))
                dpg.add_slider_float(
                    label="Radius (px)",
                    tag=self._cfg_tag("fovsize"),
                    min_value=5.0,
                    max_value=120.0,
                    default_value=float(getattr(config, "fovsize", 28.0)),
                    callback=self._make_config_cb("fovsize", float),
                )

            dpg.add_spacer(height=4)

            # Card 3: Target Smoothing & Speed
            with dpg.child_window(border=True, auto_resize_y=True):
                dpg.add_text("TARGET SMOOTH (SPEED X / Y)", color=(56, 189, 248))
                with dpg.group(horizontal=True):
                    dpg.add_slider_float(
                        label="Speed X",
                        tag=self._cfg_tag("normal_x_speed"),
                        min_value=10.0,
                        max_value=250.0,
                        default_value=float(getattr(config, "normal_x_speed", 100.0)),
                        width=220,
                        callback=self._make_config_cb("normal_x_speed", float),
                    )
                    dpg.add_slider_float(
                        label="Speed Y",
                        tag=self._cfg_tag("normal_y_speed"),
                        min_value=10.0,
                        max_value=250.0,
                        default_value=float(getattr(config, "normal_y_speed", 60.0)),
                        width=220,
                        callback=self._make_config_cb("normal_y_speed", float),
                    )

            dpg.add_spacer(height=4)

            # Card 4: WindMouse Settle & Aim Offsets
            with dpg.child_window(border=True, auto_resize_y=True):
                dpg.add_text("WINDMOUSE TRAJECTORY & OFFSETS", color=(56, 189, 248))
                dpg.add_slider_float(
                    label="WindMouse Settle Radius (px)",
                    tag=self._cfg_tag("wm_settle_radius_px"),
                    min_value=0.5,
                    max_value=6.0,
                    default_value=float(getattr(config, "wm_settle_radius_px", 2.8)),
                    callback=self._make_config_cb("wm_settle_radius_px", float),
                )
                with dpg.group(horizontal=True):
                    dpg.add_slider_int(
                        label="Aim Offset X",
                        tag=self._cfg_tag("aim_offsetX"),
                        min_value=-20,
                        max_value=20,
                        default_value=int(getattr(config, "aim_offsetX", 1)),
                        width=160,
                        callback=self._make_config_cb("aim_offsetX", int),
                    )
                    dpg.add_slider_int(
                        label="Aim Offset Y",
                        tag=self._cfg_tag("aim_offsetY"),
                        min_value=-20,
                        max_value=20,
                        default_value=int(getattr(config, "aim_offsetY", -1)),
                        width=160,
                        callback=self._make_config_cb("aim_offsetY", int),
                    )

            dpg.add_spacer(height=4)

            # Card 5: Secondary Aim (ADS) & Triggerbot
            with dpg.child_window(border=True, auto_resize_y=True):
                with dpg.collapsing_header(label="Secondary Aim (ADS / Sniping)", default_open=False):
                    dpg.add_checkbox(
                        label="Enable ADS Secondary Aim",
                        tag=self._cfg_tag("ads_fov_enabled"),
                        default_value=bool(getattr(config, "ads_fov_enabled", True)),
                        callback=self._make_config_cb("ads_fov_enabled", bool),
                    )
                    dpg.add_slider_float(
                        label="ADS FOV Radius (px)",
                        tag=self._cfg_tag("ads_fovsize"),
                        min_value=10.0,
                        max_value=200.0,
                        default_value=float(getattr(config, "ads_fovsize", 45.0)),
                        callback=self._make_config_cb("ads_fovsize", float),
                    )
                    with dpg.group(horizontal=True):
                        dpg.add_slider_float(
                            label="ADS Speed X",
                            tag=self._cfg_tag("normal_x_speed_sec"),
                            min_value=10.0,
                            max_value=250.0,
                            default_value=float(getattr(config, "normal_x_speed_sec", 100.0)),
                            width=220,
                            callback=self._make_config_cb("normal_x_speed_sec", float),
                        )
                        dpg.add_slider_float(
                            label="ADS Speed Y",
                            tag=self._cfg_tag("normal_y_speed_sec"),
                            min_value=10.0,
                            max_value=250.0,
                            default_value=float(getattr(config, "normal_y_speed_sec", 60.0)),
                            width=220,
                            callback=self._make_config_cb("normal_y_speed_sec", float),
                        )

                with dpg.collapsing_header(label="Triggerbot Settings", default_open=False):
                    dpg.add_checkbox(
                        label="Enable Triggerbot",
                        tag=self._cfg_tag("enabletb"),
                        default_value=bool(getattr(config, "enabletb", False)),
                        callback=self._make_config_cb("enabletb", bool),
                    )
                    dpg.add_slider_float(
                        label="Triggerbot FOV (px)",
                        tag=self._cfg_tag("tbfovsize"),
                        min_value=1.0,
                        max_value=30.0,
                        default_value=float(getattr(config, "tbfovsize", 5.0)),
                        callback=self._make_config_cb("tbfovsize", float),
                    )

            dpg.add_spacer(height=6)

            # Card 6: Quick Action Buttons matching Demo 2 mockup
            with dpg.group(horizontal=True):
                dpg.add_button(
                    label="APPLY PROFILE",
                    width=220,
                    callback=self._cb_load_profile,
                )
                dpg.add_button(
                    label="SAVE ACTIVE",
                    width=160,
                    callback=self._cb_save_profile,
                )

    def _build_vision_tab(self):
        with dpg.child_window(border=False):
            with dpg.group(horizontal=True):
                # Left Column: Color & HSV & Gates
                with dpg.child_window(width=420, border=True):
                    dpg.add_text("Color & Anti-Noise Calibration", color=(56, 189, 248))
                    dpg.add_combo(
                        items=["custom", "purple", "yellow", "red"],
                        tag=self._cfg_tag("color"),
                        default_value=str(getattr(config, "color", "custom")),
                        label="Target Color",
                        callback=self._make_config_cb("color", str),
                    )

                    dpg.add_text("HSV Golden Bounds (UDP TurboJPEG):", color=(148, 163, 184))
                    with dpg.group(horizontal=True):
                        dpg.add_slider_int(
                            label="Min H",
                            tag=self._cfg_tag("custom_hsv_min_h"),
                            min_value=0,
                            max_value=180,
                            default_value=int(getattr(config, "custom_hsv_min_h", 125)),
                            width=140,
                            callback=self._make_config_cb("custom_hsv_min_h", int),
                        )
                        dpg.add_slider_int(
                            label="Max H",
                            tag=self._cfg_tag("custom_hsv_max_h"),
                            min_value=0,
                            max_value=180,
                            default_value=int(getattr(config, "custom_hsv_max_h", 165)),
                            width=140,
                            callback=self._make_config_cb("custom_hsv_max_h", int),
                        )

                    with dpg.group(horizontal=True):
                        dpg.add_slider_int(
                            label="Min S",
                            tag=self._cfg_tag("custom_hsv_min_s"),
                            min_value=0,
                            max_value=255,
                            default_value=int(getattr(config, "custom_hsv_min_s", 80)),
                            width=140,
                            callback=self._make_config_cb("custom_hsv_min_s", int),
                        )
                        dpg.add_slider_int(
                            label="Max S",
                            tag=self._cfg_tag("custom_hsv_max_s"),
                            min_value=0,
                            max_value=255,
                            default_value=int(getattr(config, "custom_hsv_max_s", 255)),
                            width=140,
                            callback=self._make_config_cb("custom_hsv_max_s", int),
                        )

                    with dpg.group(horizontal=True):
                        dpg.add_slider_int(
                            label="Min V",
                            tag=self._cfg_tag("custom_hsv_min_v"),
                            min_value=0,
                            max_value=255,
                            default_value=int(getattr(config, "custom_hsv_min_v", 85)),
                            width=140,
                            callback=self._make_config_cb("custom_hsv_min_v", int),
                        )
                        dpg.add_slider_int(
                            label="Max V",
                            tag=self._cfg_tag("custom_hsv_max_v"),
                            min_value=0,
                            max_value=255,
                            default_value=int(getattr(config, "custom_hsv_max_v", 255)),
                            width=140,
                            callback=self._make_config_cb("custom_hsv_max_v", int),
                        )

                    dpg.add_separator()
                    dpg.add_text("Raw Extent & Anti-Noise Gates:", color=(148, 163, 184))
                    with dpg.group(horizontal=True):
                        dpg.add_slider_int(
                            label="Min Bbox Area",
                            tag=self._cfg_tag("detection_min_bbox_area"),
                            min_value=20,
                            max_value=300,
                            default_value=int(getattr(config, "detection_min_bbox_area", 90)),
                            width=140,
                            callback=self._make_config_cb("detection_min_bbox_area", int),
                        )
                        dpg.add_slider_int(
                            label="Min Contour Area",
                            tag=self._cfg_tag("detection_min_contour_area"),
                            min_value=5,
                            max_value=120,
                            default_value=int(getattr(config, "detection_min_contour_area", 30)),
                            width=140,
                            callback=self._make_config_cb("detection_min_contour_area", int),
                        )

                    with dpg.group(horizontal=True):
                        dpg.add_slider_int(
                            label="Min Width (px)",
                            tag=self._cfg_tag("detection_min_width"),
                            min_value=2,
                            max_value=20,
                            default_value=int(getattr(config, "detection_min_width", 6)),
                            width=140,
                            callback=self._make_config_cb("detection_min_width", int),
                        )
                        dpg.add_slider_int(
                            label="Min Height (px)",
                            tag=self._cfg_tag("detection_min_height"),
                            min_value=2,
                            max_value=20,
                            default_value=int(getattr(config, "detection_min_height", 8)),
                            width=140,
                            callback=self._make_config_cb("detection_min_height", int),
                        )

                    dpg.add_separator()
                    dpg.add_text("AI YOLO Model (ONNX / DirectML):", color=(56, 189, 248))
                    dpg.add_checkbox(
                        label="Enable AI Detection Guard",
                        tag=self._cfg_tag("ai_detection_enabled"),
                        default_value=bool(getattr(config, "ai_detection_enabled", False)),
                        callback=self._make_config_cb("ai_detection_enabled", bool),
                    )

                # Right Column: Live Detection Texture Viewport
                with dpg.child_window(border=True):
                    dpg.add_text("Real-time Vision Viewport", color=(56, 189, 248))
                    dpg.add_checkbox(
                        label="Stream Live Texture (GPU 60-144 FPS)",
                        tag="chk_preview",
                        default_value=self.preview_enabled,
                        callback=self._cb_toggle_preview,
                    )
                    if self.texture_tag is not None:
                        dpg.add_image(self.texture_tag, width=300, height=300)

    def _build_hardware_tab(self):
        with dpg.child_window(border=False):
            dpg.add_text("Mouse Hardware & Sensitivity Interface", color=(56, 189, 248))
            with dpg.group(horizontal=True):
                dpg.add_combo(
                    items=list(_MOUSE_API_ITEMS),
                    tag=self._cfg_tag("mouse_api"),
                    default_value=str(getattr(config, "mouse_api", "Serial")),
                    label="Mouse API",
                    width=160,
                    callback=self._make_config_cb("mouse_api", str),
                )
                dpg.add_combo(
                    items=list(_SERIAL_MODE_ITEMS),
                    tag=self._cfg_tag("serial_port_mode"),
                    default_value=str(getattr(config, "serial_port_mode", "Auto")),
                    label="Serial Port",
                    width=140,
                    callback=self._make_config_cb("serial_port_mode", str),
                )
                dpg.add_input_text(
                    label="Port Name",
                    tag=self._cfg_tag("serial_port"),
                    default_value=str(getattr(config, "serial_port", "") or ""),
                    width=110,
                    callback=self._make_config_cb("serial_port", str),
                )

            dpg.add_checkbox(
                label="Auto Switch to 4M Baud Rate (MAKCU High-Speed)",
                tag=self._cfg_tag("serial_auto_switch_4m"),
                default_value=bool(getattr(config, "serial_auto_switch_4m", True)),
                callback=self._make_config_cb("serial_auto_switch_4m", bool),
            )

            dpg.add_separator()
            with dpg.group(horizontal=True):
                dpg.add_slider_float(
                    label="In-Game Sensitivity",
                    tag=self._cfg_tag("in_game_sens"),
                    min_value=0.05,
                    max_value=2.0,
                    default_value=float(getattr(config, "in_game_sens", 0.23)),
                    width=220,
                    callback=self._make_config_cb("in_game_sens", float),
                )
                dpg.add_slider_int(
                    label="Mouse DPI",
                    tag=self._cfg_tag("mouse_dpi"),
                    min_value=400,
                    max_value=6400,
                    default_value=int(getattr(config, "mouse_dpi", 1100)),
                    width=220,
                    callback=self._make_config_cb("mouse_dpi", int),
                )

            dpg.add_spacer(height=6)
            dpg.add_separator()
            dpg.add_text("Video Capture Ingest Stream", color=(56, 189, 248))
            with dpg.group(horizontal=True):
                dpg.add_combo(
                    items=list(_CAPTURE_MODE_ITEMS),
                    tag=self._cfg_tag("capture_mode"),
                    default_value=str(getattr(config, "capture_mode", "UDP")),
                    label="Capture Mode",
                    width=150,
                    callback=self._cb_capture_mode,
                )
                dpg.add_input_text(
                    label="UDP IP",
                    tag="input_udp_ip",
                    default_value=str(getattr(config, "udp_ip", "0.0.0.0")),
                    width=110,
                )
                dpg.add_input_text(
                    label="Port",
                    tag="input_udp_port",
                    default_value=str(getattr(config, "udp_port", "5000")),
                    width=70,
                )

            dpg.add_spacer(height=10)
            with dpg.group(horizontal=True):
                dpg.add_button(
                    label="Reconnect Serial Device",
                    tag="btn_reconnect_serial",
                    callback=self._cb_reconnect_serial,
                )
                dpg.add_button(
                    label="Reconnect Capture Stream",
                    tag="btn_reconnect_capture",
                    callback=self._cb_reconnect_capture,
                )

    def _build_telemetry_tab(self):
        with dpg.child_window(border=False):
            # Telemetry Overview Card matching Demo 2 mockup
            with dpg.child_window(border=True, auto_resize_y=True):
                with dpg.group(horizontal=True):
                    dpg.add_text("TELEMETRY: LATENCY", color=(56, 189, 248))
                    dpg.add_text("(AVG --ms)", tag="txt_telemetry_avg_lat", color=(148, 163, 184))
                    dpg.add_spacer(width=20)
                    dpg.add_text("TRACK RATE:", color=(148, 163, 184))
                    dpg.add_text("-- Hz", tag="txt_telemetry_rate", color=(52, 211, 153))
                    dpg.add_spacer(width=20)
                    dpg.add_text("D3D11 • 240 FPS HUD", color=(148, 163, 184))

            dpg.add_spacer(height=4)

            # GPU Plot: Frame Latency & FPS
            with dpg.child_window(border=True, auto_resize_y=True):
                with dpg.plot(label="DirectX 11 Latency & FPS Telemetry (0% CPU)", height=160, width=-1):
                    dpg.add_plot_legend()
                    dpg.add_plot_axis(dpg.mvXAxis, label="Frame Timeline (last 100 frames)", no_tick_labels=True)
                    y_axis = dpg.add_plot_axis(dpg.mvYAxis, label="Latency (ms) / FPS / 10")
                    dpg.set_axis_limits(y_axis, 0, 30)
                    self.series_latency = dpg.add_line_series(
                        self.plot_x, self.plot_latency, label="Latency (ms)", parent=y_axis
                    )
                    self.series_fps = dpg.add_line_series(
                        self.plot_x, self.plot_fps, label="Track FPS / 10", parent=y_axis
                    )

            dpg.add_spacer(height=4)

            # Live Logging Console Card
            with dpg.child_window(border=True, auto_resize_y=True):
                dpg.add_text("TACTICAL LOG TERMINAL", color=(56, 189, 248))
                dpg.add_input_text(
                    tag="txt_log_console",
                    multiline=True,
                    readonly=True,
                    height=160,
                    width=-1,
                    default_value="[System] DPG GPU Engine started.\n",
                )

    def _build_profiles_tab(self):
        with dpg.child_window(border=False):
            dpg.add_text("Configuration Profiles Management", color=(56, 189, 248))

            dpg.add_combo(
                items=[
                    "config.json (Default)",
                    "config.burst_spray.json",
                    "udp_144hz_fast_cvm.json",
                    "2aim_cvm.json",
                ],
                default_value="config.json (Default)",
                label="Select Preset Profile",
                tag="combo_preset_profile",
            )

            with dpg.group(horizontal=True):
                dpg.add_button(
                    label="LOAD SELECTED PROFILE",
                    tag="btn_load_profile",
                    callback=self._cb_load_profile,
                )
                dpg.add_button(
                    label="SAVE CURRENT AS ACTIVE",
                    tag="btn_save_profile",
                    callback=self._cb_save_profile,
                )

            dpg.add_separator()
            dpg.add_text("Engine Info:", color=(148, 163, 184))
            dpg.add_text("• UI Framework: DearPyGui v2.3.1 (Direct3D 11)")
            dpg.add_text("• Aim Algorithm: WindMouse v1.2 + OneEuro Filter + Settle Gate (2.8px)")
            dpg.add_text("• Video Ingest: UDP TurboJPEG 144Hz MJPEG Protocol")

    # --- Callbacks & Helpers ---
    def _cfg_tag(self, key):
        """Stable DPG tag for a config-backed widget."""
        return f"cfg_{key}"

    def _sync_ui_from_config(self):
        """Push ``config`` values into the widgets (config -> UI, one way).

        Never writes ``config``, never saves, never touches the tracker and
        never creates widgets: it is a pure read-and-display pass. Safe to call
        repeatedly (idempotent) and only from the UI thread. Returns ``True``
        when at least one widget was updated.
        """
        if self._closed:
            return False

        updated = 0
        for key, type_fn in self._CONFIG_WIDGETS:
            try:
                tag = self._cfg_tag(key)
                if not dpg.does_item_exist(tag):
                    continue

                raw = getattr(config, key, None)
                if key == "selected_mouse_button":
                    value = self._get_btn_name(int(raw))
                elif key in ("serial_port", "mouse_api", "serial_port_mode"):
                    # Free-text/backend names: never display the string "None".
                    value = str(raw or "")
                else:
                    value = type_fn(raw)

                item_cfg = dpg.get_item_configuration(tag) or {}
                items = item_cfg.get("items")
                if items:
                    # A profile may hold an engine/API name the combo does not
                    # offer; keep the previous display instead of inventing one.
                    if value not in items:
                        continue
                else:
                    min_value = item_cfg.get("min_value")
                    max_value = item_cfg.get("max_value")
                    # DPG reports "" for items without bounds (checkbox, text),
                    # so only real numbers clamp a real number.
                    numeric = isinstance(value, (int, float)) and not isinstance(value, bool)
                    if (
                        numeric
                        and isinstance(min_value, (int, float))
                        and not isinstance(min_value, bool)
                        and isinstance(max_value, (int, float))
                        and not isinstance(max_value, bool)
                    ):
                        # Clamp for display only; config keeps its own value.
                        value = max(min_value, min(max_value, value))

                dpg.set_value(tag, value)
                updated += 1
            except Exception as e:
                print(f"[UI-DPG] Error syncing widget {key}: {e}")

        try:
            if dpg.does_item_exist("txt_status_badge"):
                ai_on = bool(getattr(config, "ai_detection_enabled", False)) or (
                    str(getattr(config, "detection_engine", "colorbot")).strip().lower()
                    == "ai_detection"
                )
                dpg.set_value(
                    "txt_status_badge",
                    "STATUS: AI DETECTION" if ai_on else "STATUS: ONLINE",
                )
                updated += 1
        except Exception as e:
            print(f"[UI-DPG] Error syncing status badge: {e}")

        return updated > 0

    def _sync_engine_ui_from_config(self):
        """Compatibility shim for main.py's F1/F5 hotkey path.

        ``main.py`` only calls this when ``hasattr(app, ...)`` is True; the
        detection engine is not a second source of truth, so it just forwards
        to ``_sync_ui_from_config()``.
        """
        return self._sync_ui_from_config()

    def _make_config_cb(self, key, type_fn):
        def _callback(sender, app_data):
            try:
                val = type_fn(app_data)
                setattr(config, key, val)
                config.save_to_file()
                self._sync_config_to_tracker()
            except Exception as e:
                print(f"[UI-DPG] Error setting {key}: {e}")

        return _callback

    def _get_btn_name(self, code):
        mapping = {1: "Left Mouse", 2: "Right Mouse", 4: "Side Mouse 4", 5: "Side Mouse 5"}
        return mapping.get(code, "Side Mouse 4")

    def _cb_aim_btn(self, sender, app_data):
        rev = {"Left Mouse": 1, "Right Mouse": 2, "Side Mouse 4": 4, "Side Mouse 5": 5}
        val = rev.get(app_data, 4)
        config.selected_mouse_button = val
        config.save_to_file()
        self._sync_config_to_tracker()

    def _cb_toggle_preview(self, sender, app_data):
        self.preview_enabled = bool(app_data)

    def _cb_capture_mode(self, sender, app_data):
        try:
            config.capture_mode = str(app_data)
            config.save_to_file()
            if self.capture:
                self.capture.set_mode(str(app_data))
            log_print(f"[UI-DPG] Capture mode switched to: {app_data}")
        except Exception as e:
            log_print(f"[UI-DPG] Error setting capture_mode: {e}")

    def _cb_reconnect_capture(self, sender=None, app_data=None):
        log_print("[UI-DPG] Reconnect capture requested.")
        if not self.capture:
            return
        cap_mode = str(getattr(config, "capture_mode", "UDP"))
        try:
            self.capture.disconnect()
            self.capture.set_mode(cap_mode)
            if cap_mode == "UDP":
                ip, port = self._read_udp_endpoint()
                config.udp_ip = str(ip)
                config.udp_port = str(port)
                config.save_to_file()
                ok, err = self.capture.connect_udp(ip, port)
                log_print(f"[UI-DPG] Reconnect UDP on {ip}:{port} -> {'OK' if ok else err}")
            elif cap_mode == "NDI":
                ok, err = self.capture.connect_ndi(getattr(config, "last_ndi_source", ""))
            elif cap_mode == "MSS":
                ok, err = self.capture.connect_mss(1, 320, 320)
            elif cap_mode in ("CaptureCard", "CaptureCardGStreamer"):
                ok, err = self.capture.connect_capture_card(config)
            elif cap_mode == "Teleport":
                ok, err = self.capture.connect_teleport(host=getattr(config, "teleport_host", ""), port=getattr(config, "teleport_port", "0"))
        except Exception as e:
            log_print(f"[UI-DPG] Reconnect capture error: {e}")

    def _cb_reconnect_serial(self, sender=None, app_data=None):
        log_print("[UI-DPG] Reconnect serial requested.")
        if self.tracker and hasattr(self.tracker, "mouse_api") and self.tracker.mouse_api is not None:
            try:
                self.tracker.mouse_api.disconnect()
                self.tracker.mouse_api.connect()
            except Exception as e:
                log_print(f"[UI-DPG] Reconnect error: {e}")
            return

        try:
            from src.utils.mouse import switch_backend
            hw_ok, hw_err = switch_backend(
                getattr(config, "mouse_api", "Serial"),
                serial_port_mode=getattr(config, "serial_port_mode", "Auto"),
                serial_port=getattr(config, "serial_port", ""),
            )
            log_print(f"[UI-DPG] Mouse backend reconnect: {'OK' if hw_ok else hw_err}")
        except Exception as e:
            log_print(f"[UI-DPG] Reconnect error: {e}")

    def _toggle_runtime(self, sender=None, app_data=None):
        if getattr(self, "_runtime_busy", False):
            return
        if getattr(self, "_runtime_active", False):
            self._stop_runtime()
        else:
            self._start_runtime()

    def _read_udp_endpoint(self):
        """Read the UDP endpoint widgets **on the UI thread**.

        DPG is not thread safe, so the worker must never call ``dpg.get_value``.
        ``_start_runtime()`` captures both fields here and hands them to the
        worker as plain strings. Values fall back to ``config`` (never to a
        hard-coded default) when a widget is missing.
        """
        ip = ""
        port = ""
        try:
            if dpg.does_item_exist("input_udp_ip"):
                ip = dpg.get_value("input_udp_ip")
        except Exception as e:
            log_print(f"[UI-DPG] Could not read UDP IP: {e}")
        try:
            if dpg.does_item_exist("input_udp_port"):
                port = dpg.get_value("input_udp_port")
        except Exception as e:
            log_print(f"[UI-DPG] Could not read UDP port: {e}")
        if ip in (None, ""):
            ip = getattr(config, "udp_ip", "0.0.0.0")
        if port in (None, ""):
            port = getattr(config, "udp_port", 5000)
        return str(ip), str(port)

    def _start_runtime(self):
        if self._closed:
            return
        if getattr(self, "_runtime_busy", False) or getattr(self, "_runtime_active", False):
            return
        self._runtime_busy = True
        log_print("[UI-DPG] Starting hardware + capture runtime...")
        if dpg.does_item_exist("btn_runtime_toggle"):
            dpg.set_item_label("btn_runtime_toggle", "[CONNECTING...]")
        if dpg.does_item_exist("txt_status_badge"):
            dpg.set_value("txt_status_badge", "STATUS: CONNECTING...")
            dpg.configure_item("txt_status_badge", color=(251, 191, 36))

        # Read the UI-owned values before leaving this thread.
        udp_ip, udp_port = self._read_udp_endpoint()
        threading.Thread(
            target=self._start_runtime_worker,
            args=(udp_ip, udp_port),
            daemon=True,
            name="DPG_RuntimeStart",
        ).start()

    def _start_runtime_worker(self, udp_ip, udp_port):
        """Connect hardware + capture off the UI thread.

        This runs on a background thread: it may touch ``config`` and the
        capture service but must never call ``dpg.*`` (the endpoint was read by
        ``_read_udp_endpoint`` before the thread was spawned).
        """
        # 1. Connect mouse API
        mouse_mode = str(getattr(config, "mouse_api", "Serial"))
        hw_ok, hw_err = False, None
        try:
            from src.utils.mouse import switch_backend
            hw_ok, hw_err = switch_backend(
                mouse_mode,
                serial_port_mode=getattr(config, "serial_port_mode", "Auto"),
                serial_port=getattr(config, "serial_port", ""),
            )
        except Exception as e:
            hw_ok, hw_err = False, str(e)

        # 2. Connect capture backend
        cap_mode = str(getattr(config, "capture_mode", "UDP"))
        cap_ok, cap_err = False, None
        try:
            if self.capture:
                self.capture.set_mode(cap_mode)
                if cap_mode == "UDP":
                    cap_ok, cap_err = self.capture.connect_udp(str(udp_ip), str(udp_port))
                elif cap_mode == "NDI":
                    src = str(getattr(config, "last_ndi_source", ""))
                    cap_ok, cap_err = self.capture.connect_ndi(src)
                elif cap_mode == "MSS":
                    cap_ok, cap_err = self.capture.connect_mss(
                        int(getattr(config, "mss_monitor_index", 1)),
                        int(getattr(config, "mss_fov_x", 320)),
                        int(getattr(config, "mss_fov_y", 320)),
                    )
                elif cap_mode in ("CaptureCard", "CaptureCardGStreamer"):
                    cap_ok, cap_err = self.capture.connect_capture_card(config)
                elif cap_mode == "Teleport":
                    cap_ok, cap_err = self.capture.connect_teleport(
                        host=str(getattr(config, "teleport_host", "")),
                        port=str(getattr(config, "teleport_port", "0")),
                        stream_key=str(getattr(config, "teleport_stream_key", "")),
                    )
                else:
                    cap_ok, cap_err = False, f"Unknown capture mode {cap_mode}"
            else:
                cap_ok, cap_err = False, "No capture service"
        except Exception as e:
            cap_ok, cap_err = False, str(e)

        self.after(0, self._on_runtime_started, hw_ok, hw_err, cap_ok, cap_err, mouse_mode, cap_mode)

    def _on_runtime_started(self, hw_ok, hw_err, cap_ok, cap_err, mouse_mode, cap_mode):
        self._runtime_busy = False
        if hw_ok and cap_ok:
            self._runtime_active = True
            log_print(f"[UI-DPG] Runtime active: {mouse_mode} + {cap_mode}")
            if dpg.does_item_exist("btn_runtime_toggle"):
                dpg.set_item_label("btn_runtime_toggle", "[⏹ STOP RUNTIME]")
            if dpg.does_item_exist("txt_status_badge"):
                dpg.set_value("txt_status_badge", f"STATUS: RUNNING ({mouse_mode} + {cap_mode})")
                dpg.configure_item("txt_status_badge", color=(52, 211, 153))
        else:
            self._runtime_active = False
            err_msg = hw_err if not hw_ok else cap_err
            log_print(f"[UI-DPG] Runtime start failed: {err_msg}")
            if dpg.does_item_exist("btn_runtime_toggle"):
                dpg.set_item_label("btn_runtime_toggle", "[▶ START RUNTIME]")
            if dpg.does_item_exist("txt_status_badge"):
                dpg.set_value("txt_status_badge", f"STATUS: FAILED ({err_msg})")
                dpg.configure_item("txt_status_badge", color=(239, 68, 68))

    def _stop_runtime(self):
        self._runtime_busy = True
        try:
            if self.capture and hasattr(self.capture, "disconnect"):
                self.capture.disconnect()
            from src.utils.mouse import disconnect_all
            disconnect_all()
        except Exception as e:
            log_print(f"[UI-DPG] Stop runtime error: {e}")
        self._runtime_active = False
        self._runtime_busy = False
        log_print("[UI-DPG] Runtime stopped.")
        if dpg.does_item_exist("btn_runtime_toggle"):
            dpg.set_item_label("btn_runtime_toggle", "[▶ START RUNTIME]")
        if dpg.does_item_exist("txt_status_badge"):
            dpg.set_value("txt_status_badge", "STATUS: STOPPED")
            dpg.configure_item("txt_status_badge", color=(148, 163, 184))

    def _maybe_auto_start_runtime(self):
        if bool(getattr(config, "auto_connect_mouse_api", True)):
            self._start_runtime()

    def _cb_load_profile(self, sender=None, app_data=None):
        choice = ""
        if dpg.does_item_exist("combo_preset_profile"):
            choice = dpg.get_value("combo_preset_profile")
        choice = str(choice or "")
        fname = "config.json"
        if "burst_spray" in choice:
            fname = "config.burst_spray.json"
        elif "144hz" in choice:
            fname = os.path.join("configs", "udp_144hz_fast_cvm.json")
        elif "2aim" in choice:
            fname = os.path.join("configs", "2aim_cvm.json")

        if os.path.exists(fname):
            config.load_from_file(fname)
            self._sync_config_to_tracker()
            self._sync_ui_from_config()
            log_print(f"[UI-DPG] Profile loaded: {fname}")

    def _cb_save_profile(self, sender=None, app_data=None):
        config.save_to_file()
        log_print("[UI-DPG] Active configuration saved to config.json.")

    def _sync_config_to_tracker(self):
        if self.tracker:
            try:
                self.tracker.normal_x_speed = getattr(config, "normal_x_speed", 100.0)
                self.tracker.normal_y_speed = getattr(config, "normal_y_speed", 60.0)
                self.tracker.normalsmooth = getattr(config, "normalsmooth", 3.0)
                self.tracker.normalsmoothfov = getattr(config, "normalsmoothfov", 18.67)
                self.tracker.mouse_dpi = getattr(config, "mouse_dpi", 1100)
                self.tracker.fovsize = getattr(config, "fovsize", 28.0)
                self.tracker.ads_fov_enabled = getattr(config, "ads_fov_enabled", False)
                self.tracker.ads_fovsize = getattr(config, "ads_fovsize", config.fovsize)
                self.tracker.ads_key = getattr(config, "ads_key", "Right Mouse Button")
                self.tracker.tbfovsize = getattr(config, "tbfovsize", 3.3)
                self.tracker.trigger_ads_fov_enabled = getattr(config, "trigger_ads_fov_enabled", False)
                self.tracker.trigger_ads_fovsize = getattr(config, "trigger_ads_fovsize", config.tbfovsize)
                self.tracker.trigger_ads_key = getattr(config, "trigger_ads_key", "Right Mouse Button")
                self.tracker.trigger_ads_key_type = getattr(config, "trigger_ads_key_type", "hold")
                self.tracker.selected_tb_btn = getattr(config, "selected_tb_btn", 1)
            except Exception as e:
                print(f"[UI-DPG] Error syncing config: {e}")

        # Always mirror config back into the widgets: main.py reloads the config
        # *after* the UI is built, and hotkeys mutate it from the tracker thread.
        self._sync_ui_from_config()

    # --- Framework Compatibility with main.py ---
    def after(self, ms, func, *args):
        """Thread-safe callback timer matching Tkinter's after() contract."""
        execute_at = time.time() + (ms / 1000.0)
        with self._callback_lock:
            self._scheduled_callbacks.append((execute_at, func, args))

    def protocol(self, event, handler):
        """Register window close callback matching Tkinter's protocol()."""
        if event == "WM_DELETE_WINDOW":
            self._close_handlers.append(handler)

    def _process_callbacks(self):
        if self._closed:
            return
        now = time.time()
        to_run = []
        with self._callback_lock:
            remaining = []
            for item in self._scheduled_callbacks:
                execute_at, func, args = item
                if now >= execute_at:
                    to_run.append((func, args))
                else:
                    remaining.append(item)
            self._scheduled_callbacks = remaining
        for func, args in to_run:
            try:
                func(*args)
            except Exception as e:
                print(f"[UI-DPG] Callback error: {e}")

    def _udp_performance_stats(self):
        """Return the UDP receiver's stats dict, or ``None``.

        Read-only and defensive: the capture service may be ``None``, a mock, or
        a real service whose receiver is not bound yet.
        """
        capture = self.capture if self.capture is not None else self.capture_service
        if capture is None:
            return None
        try:
            mode = getattr(capture, "mode", None)
            if isinstance(mode, str) and mode != "UDP":
                return None
            manager = getattr(capture, "udp_manager", None)
            if manager is None:
                return None
            getter = getattr(manager, "get_receiver", None)
            if not callable(getter):
                return None
            receiver = getter()
            if receiver is None:
                return None
            stats_getter = getattr(receiver, "get_performance_stats", None)
            if not callable(stats_getter):
                return None
            stats = stats_getter()
            return stats if isinstance(stats, dict) else None
        except Exception as e:
            self._log_telemetry_error(e)
            return None

    def _log_telemetry_error(self, error):
        """Log telemetry read failures once, not ten times per second."""
        if not self._telemetry_error_logged:
            self._telemetry_error_logged = True
            log_print(f"[UI-DPG] Telemetry source unavailable: {error}")

    def _read_telemetry_sample(self):
        """Read one ``(fps, latency_ms)`` sample from the real pipeline.

        Priority: live UDP receiver stats, then the last frame's publish
        latency, then the tracker counters kept for compatibility. Either side
        may be ``None`` when no source reports it; callers display ``--`` and
        push ``0.0`` into the plot. Never raises.
        """
        fps = None
        latency = None

        stats = self._udp_performance_stats()
        if stats is not None:
            fps = _finite_float(stats.get("current_fps"))
            age = _finite_float(stats.get("last_packet_age_s"))
            if age is not None and age > _UDP_STALL_SECONDS:
                # Bind succeeded but the feed is dead: a cached FPS would lie.
                fps = 0.0
            delays = []
            for key in ("receive_delay_ms", "decode_delay_ms", "processing_delay_ms"):
                value = _finite_float(stats.get(key))
                if value is not None:
                    delays.append(value)
            if delays:
                latency = _finite_float(sum(delays))

        capture = self.capture if self.capture is not None else self.capture_service
        if latency is None and capture is not None:
            meta_getter = getattr(capture, "get_frame_meta", None)
            if callable(meta_getter):
                try:
                    meta = meta_getter()
                except Exception as e:
                    self._log_telemetry_error(e)
                    meta = None
                if isinstance(meta, dict):
                    latency = _finite_float(meta.get("publish_latency_ms"))

        tracker = self.tracker
        if tracker is not None:
            if fps is None:
                try:
                    fps = _finite_float(getattr(tracker, "current_fps", None))
                except Exception as e:
                    self._log_telemetry_error(e)
            if latency is None:
                try:
                    latency = _finite_float(getattr(tracker, "last_latency_ms", None))
                except Exception as e:
                    self._log_telemetry_error(e)
            if latency is None:
                perf = getattr(tracker, "perf", None)
                if isinstance(perf, dict):
                    latency = _finite_float(perf.get("publish_to_detect_ms"))

        return fps, latency

    def _update_telemetry(self):
        if self._closed:
            return
        now = time.time()
        if now - self._last_telemetry_time >= 0.1:  # 10 Hz telemetry sample rate
            self._last_telemetry_time = now

            current_fps, latency = self._read_telemetry_sample()
            fps_known = current_fps is not None
            if not fps_known:
                current_fps = 0.0
            if latency is None:
                latency = 0.0
            else:
                # Average only measured samples: the pre-filled zeros of the
                # plot window are placeholders, not measurements.
                self._latency_history.append(latency)
                if len(self._latency_history) > self.max_plot_pts:
                    del self._latency_history[: -self.max_plot_pts]

            self.plot_latency.pop(0)
            self.plot_latency.append(latency)
            self.plot_fps.pop(0)
            self.plot_fps.append(current_fps / 10.0)

            series_latency = getattr(self, "series_latency", None)
            if series_latency is not None and dpg.does_item_exist(series_latency):
                dpg.set_value(series_latency, [self.plot_x, self.plot_latency])
            series_fps = getattr(self, "series_fps", None)
            if series_fps is not None and dpg.does_item_exist(series_fps):
                dpg.set_value(series_fps, [self.plot_x, self.plot_fps])

            if dpg.does_item_exist("txt_telemetry_avg_lat"):
                if self._latency_history:
                    avg = sum(self._latency_history) / len(self._latency_history)
                    dpg.set_value("txt_telemetry_avg_lat", f"(AVG {avg:.1f}ms)")
                else:
                    dpg.set_value("txt_telemetry_avg_lat", "(AVG --ms)")
            if dpg.does_item_exist("txt_telemetry_rate"):
                if fps_known:
                    dpg.set_value("txt_telemetry_rate", f"{current_fps:.1f} Hz")
                else:
                    dpg.set_value("txt_telemetry_rate", "-- Hz")

            # Update log console. get_recent_logs() returns list[dict], not
            # list[str]: joining it directly raised TypeError every tick.
            recent_logs = get_recent_logs(20)
            if recent_logs and dpg.does_item_exist("txt_log_console"):
                lines = []
                for entry in recent_logs:
                    if isinstance(entry, dict):
                        lines.append(f"[{entry.get('level', 'INFO')}] {entry.get('message', '')}")
                    else:
                        lines.append(str(entry))
                dpg.set_value("txt_log_console", "\n".join(lines))

    def _prepare_preview_rgba(self, frame):
        """Normalise an arbitrary capture frame to a float32 RGBA/255 image.

        Returns ``None`` when the frame cannot be published (empty, wrong
        dimensionality or an unsupported channel count) instead of raising.
        """
        if frame is None or not isinstance(frame, np.ndarray):
            return None
        if frame.size == 0 or frame.ndim not in (2, 3):
            return None

        if frame.ndim == 2:
            rgba = cv2.cvtColor(np.ascontiguousarray(frame), cv2.COLOR_GRAY2RGBA)
        else:
            channels = frame.shape[2]
            if channels == 1:
                # (H, W, 1) masks are common; drop the singleton axis first.
                gray = np.ascontiguousarray(frame[:, :, 0])
                rgba = cv2.cvtColor(gray, cv2.COLOR_GRAY2RGBA)
            elif channels == 3:
                rgba = cv2.cvtColor(np.ascontiguousarray(frame), cv2.COLOR_BGR2RGBA)
            elif channels == 4:
                rgba = cv2.cvtColor(np.ascontiguousarray(frame), cv2.COLOR_BGRA2RGBA)
            else:
                return None

        if rgba.dtype != np.uint8:
            if np.issubdtype(rgba.dtype, np.floating) and rgba.max() <= 1.0:
                rgba = np.clip(rgba * 255.0, 0, 255).astype(np.uint8)
            else:
                rgba = np.clip(rgba, 0, 255).astype(np.uint8)

        if (rgba.shape[1], rgba.shape[0]) != (self.preview_w, self.preview_h):
            rgba = cv2.resize(rgba, (self.preview_w, self.preview_h))

        return (rgba.astype(np.float32) / 255.0).ravel()

    def _update_video_preview(self):
        if self._closed or not self.preview_enabled or not self.capture:
            return False
        if self.texture_tag is None:
            return False

        try:
            frame = None
            if hasattr(self.capture, "get_last_frame"):
                frame = self.capture.get_last_frame()
            elif hasattr(self.capture, "read_frame"):
                frame = self.capture.read_frame()

            buffer = self._prepare_preview_rgba(frame)
            if buffer is None:
                return False
            if not dpg.does_item_exist(self.texture_tag):
                return False

            # DPG raw textures expect a flat float buffer, not an (H, W, 4) array.
            try:
                dpg.set_value(self.texture_tag, buffer)
            except Exception:
                # Some DPG builds only accept a plain Python list here.
                dpg.set_value(self.texture_tag, buffer.tolist())
            return True
        except Exception as e:
            self._preview_error_count += 1
            if self._preview_error_count == 1:
                log_print(f"[UI-DPG] Preview update failed: {e}")
            return False

    def mainloop(self):
        """Run GPU render loop at monitor refresh rate with VSync (DirectX 11)."""
        dpg.show_viewport()
        self._running = True

        try:
            while dpg.is_dearpygui_running() and self._running:
                self._process_callbacks()
                self._update_telemetry()
                self._update_video_preview()
                dpg.render_dearpygui_frame()
        finally:
            self._on_close()

    def _on_close(self):
        if self._closed:
            return
        self._closed = True
        self._running = False
        try:
            self._stop_runtime()
        except Exception:
            pass
        for handler in self._close_handlers:
            try:
                handler()
            except Exception as e:
                print(f"[UI-DPG] Close handler error: {e}")
        try:
            dpg.destroy_context()
        except Exception as e:
            print(f"[UI-DPG] Error destroying context: {e}")


if __name__ == "__main__":
    # Test standalone runner
    app = DpgViewerApp()
    app.mainloop()
