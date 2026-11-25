"""
HSV Filter Preview Window - real-time preview for HSV filter tuning.
"""
import threading
import time
import tkinter as tk
from pathlib import Path

import customtkinter as ctk
import cv2
import numpy as np
from PIL import Image, ImageTk

from src.utils.app_paths import get_bundle_dir
from src.utils.config import config
from src.utils.debug_logger import log_print
from src.utils.detection import XUDP_HSV_PRESETS, load_model, perform_detection
from src.utils.hsv_calibrator import solve_contrast_hsv
from src.utils.i18n import t

COLOR_BG = "#121212"
COLOR_SURFACE = "#1E1E1E"
COLOR_ACCENT = "#FFFFFF"
COLOR_TEXT = "#E0E0E0"
COLOR_TEXT_DIM = "#757575"
COLOR_BORDER = "#2C2C2C"
COLOR_SUCCESS = "#4CAF50"
COLOR_DANGER = "#CF6679"

FONT_MAIN = ("Roboto", 11)
FONT_BOLD = ("Roboto", 11, "bold")
FONT_TITLE = ("Roboto", 13, "bold")
FONT_SMALL = ("Roboto", 10)

PREVIEW_W = 320
PREVIEW_H = 240

EYEDROPPER_H_TOL = 8
EYEDROPPER_S_TOL = 45
EYEDROPPER_V_TOL = 45


def _grab_frame_bgr(capture_service) -> np.ndarray | None:
    """Capture a BGR frame using the same path as the main loop."""
    try:
        frame = capture_service.read_frame(apply_fov=False)
        if frame is not None and frame.size > 0:
            if len(frame.shape) == 2:
                return cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
            if frame.shape[2] == 4:
                return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
            return frame.copy()
    except Exception as exc:
        log_print(f"[HsvPreview] grab frame error: {exc}")
    return None


def _apply_hsv_mask(bgr: np.ndarray, h_lo, h_hi, s_lo, s_hi, v_lo, v_hi):
    """Apply HSV mask and return (filtered image, binary mask)."""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    lo = np.array([h_lo, s_lo, v_lo], dtype=np.uint8)
    hi = np.array([h_hi, s_hi, v_hi], dtype=np.uint8)
    mask = cv2.inRange(hsv, lo, hi)

    result = bgr.copy()
    result[mask == 0] = (result[mask == 0] * 0.2).astype(np.uint8)
    result[mask > 0] = np.clip(
        result[mask > 0].astype(np.int16) + [0, 60, 0], 0, 255
    ).astype(np.uint8)
    return result, mask


def _bgr_to_pil(bgr: np.ndarray, w: int, h: int) -> ImageTk.PhotoImage:
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    pil = Image.fromarray(rgb).resize((w, h), Image.NEAREST)
    return ImageTk.PhotoImage(pil)


def _gray_to_pil(gray: np.ndarray, w: int, h: int) -> ImageTk.PhotoImage:
    pil = Image.fromarray(gray).resize((w, h), Image.NEAREST)
    return ImageTk.PhotoImage(pil)


class HsvPreviewWindow(ctk.CTkToplevel):
    """
    Real-time HSV filter preview window.
    Shows live capture with HSV mask applied alongside the binary mask.
    Each channel (H, S, V) has Low and High sliders in the same row.
    """

    def __init__(self, parent, capture_service, on_apply_callback=None):
        super().__init__(parent)

        self.capture_service = capture_service
        self.on_apply_callback = on_apply_callback

        self._h_lo = tk.IntVar(value=int(getattr(config, "custom_hsv_min_h", 0)))
        self._h_hi = tk.IntVar(value=int(getattr(config, "custom_hsv_max_h", 179)))
        self._s_lo = tk.IntVar(value=int(getattr(config, "custom_hsv_min_s", 0)))
        self._s_hi = tk.IntVar(value=int(getattr(config, "custom_hsv_max_s", 255)))
        self._v_lo = tk.IntVar(value=int(getattr(config, "custom_hsv_min_v", 0)))
        self._v_hi = tk.IntVar(value=int(getattr(config, "custom_hsv_max_v", 255)))

        self._running = True
        self._last_bgr = None
        self._preview_hsv = None
        self._lock = threading.Lock()

        self._photo_orig = None
        self._photo_mask = None
        self._photo_result = None

        self._eyedropper_active = False
        self._pick_role = "target"
        self._target_samples = []
        self._bg_samples = []
        self._full_det_var = tk.BooleanVar(value=True)
        self._det_model = None
        try:
            self._det_model, _ = load_model()
        except Exception:
            self._det_model = None
        self._eyedropper_icon = None
        self._preview_canvases = []

        self._build_ui()
        self._start_capture_thread()
        self._schedule_update()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        self.title(t("HSV Filter Preview"))
        self.configure(fg_color=COLOR_BG)
        self.resizable(True, True)
        self.attributes("-topmost", True)

        title_bar = ctk.CTkFrame(self, fg_color=COLOR_SURFACE, corner_radius=0)
        title_bar.pack(fill="x")
        ctk.CTkLabel(
            title_bar,
            text=t("HSV FILTER PREVIEW"),
            font=FONT_TITLE,
            text_color=COLOR_TEXT,
        ).pack(side="left", padx=16, pady=10)
        ctk.CTkLabel(
            title_bar,
            text=t("Adjust sliders and see the result in real time"),
            font=FONT_SMALL,
            text_color=COLOR_TEXT_DIM,
        ).pack(side="left", padx=4)

        main = ctk.CTkScrollableFrame(
            self,
            fg_color="transparent",
            scrollbar_button_color=COLOR_BORDER,
            scrollbar_button_hover_color=COLOR_SURFACE,
        )
        main.pack(fill="both", expand=True, padx=12, pady=(8, 4))

        prev_row = ctk.CTkFrame(main, fg_color="transparent")
        prev_row.pack(fill="x")

        orig_col = ctk.CTkFrame(prev_row, fg_color=COLOR_SURFACE, corner_radius=6)
        orig_col.pack(side="left", expand=True, fill="both", padx=(0, 6))
        ctk.CTkLabel(
            orig_col,
            text=t("ORIGINAL"),
            font=FONT_SMALL,
            text_color=COLOR_TEXT_DIM,
        ).pack(pady=(6, 2))
        self._canvas_orig = tk.Canvas(
            orig_col,
            width=PREVIEW_W,
            height=PREVIEW_H,
            bg="#000000",
            highlightthickness=0,
        )
        self._canvas_orig.pack(padx=6, pady=(0, 6))

        res_col = ctk.CTkFrame(prev_row, fg_color=COLOR_SURFACE, corner_radius=6)
        res_col.pack(side="left", expand=True, fill="both", padx=(6, 6))
        ctk.CTkLabel(
            res_col,
            text=t("WITH FILTER"),
            font=FONT_SMALL,
            text_color=COLOR_TEXT_DIM,
        ).pack(pady=(6, 2))
        self._canvas_result = tk.Canvas(
            res_col,
            width=PREVIEW_W,
            height=PREVIEW_H,
            bg="#000000",
            highlightthickness=0,
        )
        self._canvas_result.pack(padx=6, pady=(0, 6))

        mask_col = ctk.CTkFrame(prev_row, fg_color=COLOR_SURFACE, corner_radius=6)
        mask_col.pack(side="left", expand=True, fill="both", padx=(6, 0))
        ctk.CTkLabel(
            mask_col,
            text=t("MASK"),
            font=FONT_SMALL,
            text_color=COLOR_TEXT_DIM,
        ).pack(pady=(6, 2))
        self._canvas_mask = tk.Canvas(
            mask_col,
            width=PREVIEW_W,
            height=PREVIEW_H,
            bg="#000000",
            highlightthickness=0,
        )
        self._canvas_mask.pack(padx=6, pady=(0, 6))

        self._preview_canvases = [self._canvas_orig, self._canvas_result, self._canvas_mask]
        for canvas in self._preview_canvases:
            canvas.bind("<Button-1>", self._on_preview_click)

        sliders_frame = ctk.CTkFrame(main, fg_color=COLOR_SURFACE, corner_radius=6)
        sliders_frame.pack(fill="x", pady=(10, 4))

        ctk.CTkLabel(
            sliders_frame,
            text=t("HSV RANGE"),
            font=FONT_BOLD,
            text_color=COLOR_TEXT_DIM,
        ).pack(anchor="w", padx=14, pady=(10, 4))

        self._build_channel_row(sliders_frame, "H  Hue", self._h_lo, self._h_hi, 0, 179, "#E05050")
        self._build_channel_row(sliders_frame, "S  Sat", self._s_lo, self._s_hi, 0, 255, "#50B0E0")
        self._build_channel_row(sliders_frame, "V  Val", self._v_lo, self._v_hi, 0, 255, "#80E080")

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=12, pady=(4, 12))

        self._eyedropper_icon = self._load_eyedropper_icon()
        self._btn_eyedropper = ctk.CTkButton(
            btn_row,
            text="Pick Target" if not self._eyedropper_icon else "",
            image=self._eyedropper_icon,
            width=40,
            height=32,
            fg_color=COLOR_SURFACE,
            hover_color=COLOR_BORDER,
            text_color=COLOR_TEXT,
            font=FONT_MAIN,
            corner_radius=4,
            command=lambda: self._start_pick("target"),
        )
        self._btn_eyedropper.pack(side="left", padx=(0, 4))

        self._btn_pick_bg = ctk.CTkButton(
            btn_row,
            text=t("Pick BG"),
            width=70,
            height=32,
            fg_color=COLOR_SURFACE,
            hover_color=COLOR_BORDER,
            text_color="#F59E0B",
            font=FONT_SMALL,
            corner_radius=4,
            command=lambda: self._start_pick("bg"),
        )
        self._btn_pick_bg.pack(side="left", padx=(0, 4))

        self._btn_auto_solve = ctk.CTkButton(
            btn_row,
            text=t("Auto-Solve"),
            width=86,
            height=32,
            fg_color="#0E7490",
            hover_color="#0891B2",
            text_color="#FFFFFF",
            font=FONT_SMALL,
            corner_radius=4,
            command=self._auto_solve_samples,
        )
        self._btn_auto_solve.pack(side="left", padx=(0, 6))

        ctk.CTkCheckBox(
            btn_row,
            text=t("Full Det"),
            variable=self._full_det_var,
            font=FONT_SMALL,
            text_color=COLOR_TEXT,
            width=70,
        ).pack(side="left", padx=(0, 6))

        for preset_key, preset_lbl in (("purple", "Purple"), ("yellow", "Yellow"), ("red", "Red")):
            ctk.CTkButton(
                btn_row,
                text=preset_lbl,
                width=52,
                height=26,
                fg_color=COLOR_SURFACE,
                hover_color=COLOR_BORDER,
                text_color=COLOR_TEXT_DIM,
                font=FONT_SMALL,
                corner_radius=4,
                command=lambda pk=preset_key: self._load_preset(pk),
            ).pack(side="left", padx=2)

        self._lbl_pixels = ctk.CTkLabel(
            btn_row,
            text=t("Detected pixels: 0"),
            font=FONT_SMALL,
            text_color=COLOR_TEXT_DIM,
        )
        self._lbl_pixels.pack(side="left", padx=8)

        self._lbl_pick = ctk.CTkLabel(
            btn_row,
            text=t("Pick mode: Off"),
            font=FONT_SMALL,
            text_color=COLOR_TEXT_DIM,
        )
        self._lbl_pick.pack(side="left", padx=(4, 8))

        ctk.CTkButton(
            btn_row,
            text=t("Close"),
            width=100,
            height=32,
            fg_color=COLOR_SURFACE,
            hover_color=COLOR_BORDER,
            text_color=COLOR_TEXT,
            font=FONT_MAIN,
            corner_radius=4,
            command=self._on_close,
        ).pack(side="right", padx=(6, 0))

        ctk.CTkButton(
            btn_row,
            text=t("Apply to Config"),
            width=160,
            height=32,
            fg_color=COLOR_SUCCESS,
            hover_color="#388E3C",
            text_color="#000000",
            font=FONT_BOLD,
            corner_radius=4,
            command=self._on_apply,
        ).pack(side="right", padx=6)

        ctk.CTkButton(
            btn_row,
            text=t("Reset"),
            width=80,
            height=32,
            fg_color=COLOR_SURFACE,
            hover_color=COLOR_BORDER,
            text_color=COLOR_DANGER,
            font=FONT_MAIN,
            corner_radius=4,
            command=self._on_reset,
        ).pack(side="right", padx=6)

        self._set_eyedropper_active(False)

    def _build_channel_row(
        self,
        parent,
        label: str,
        var_lo: tk.IntVar,
        var_hi: tk.IntVar,
        min_v: int,
        max_v: int,
        accent: str,
    ):
        """Create a row with Low and High sliders for one HSV channel."""
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(2, 8))

        ctk.CTkLabel(
            row,
            text=label,
            font=FONT_BOLD,
            text_color=COLOR_TEXT,
            width=60,
            anchor="w",
        ).grid(row=0, column=0, rowspan=2, sticky="w", padx=(0, 12))

        ctk.CTkLabel(
            row,
            text=t("Low"),
            font=FONT_SMALL,
            text_color=COLOR_TEXT_DIM,
            width=30,
            anchor="w",
        ).grid(row=0, column=1, sticky="w")
        lbl_lo = ctk.CTkLabel(
            row,
            text=str(var_lo.get()),
            font=FONT_BOLD,
            text_color=COLOR_TEXT,
            width=36,
            anchor="e",
        )
        lbl_lo.grid(row=0, column=3, sticky="e", padx=(4, 0))
        slider_lo = ctk.CTkSlider(
            row,
            from_=min_v,
            to=max_v,
            number_of_steps=max_v,
            fg_color=COLOR_BORDER,
            progress_color=accent,
            button_color=accent,
            button_hover_color=COLOR_ACCENT,
            height=10,
            variable=var_lo,
            command=lambda v, lbl=lbl_lo, var=var_lo: self._on_slider(v, lbl, var, True, var_hi),
        )
        slider_lo.grid(row=0, column=2, sticky="ew", padx=(4, 0))

        ctk.CTkLabel(
            row,
            text=t("High"),
            font=FONT_SMALL,
            text_color=COLOR_TEXT_DIM,
            width=30,
            anchor="w",
        ).grid(row=1, column=1, sticky="w")
        lbl_hi = ctk.CTkLabel(
            row,
            text=str(var_hi.get()),
            font=FONT_BOLD,
            text_color=COLOR_TEXT,
            width=36,
            anchor="e",
        )
        lbl_hi.grid(row=1, column=3, sticky="e", padx=(4, 0))
        slider_hi = ctk.CTkSlider(
            row,
            from_=min_v,
            to=max_v,
            number_of_steps=max_v,
            fg_color=COLOR_BORDER,
            progress_color=accent,
            button_color=accent,
            button_hover_color=COLOR_ACCENT,
            height=10,
            variable=var_hi,
            command=lambda v, lbl=lbl_hi, var=var_hi: self._on_slider(v, lbl, var, False, var_lo),
        )
        slider_hi.grid(row=1, column=2, sticky="ew", padx=(4, 0))

        var_lo.trace_add("write", lambda *_args, lbl=lbl_lo, var=var_lo: lbl.configure(text=str(var.get())))
        var_hi.trace_add("write", lambda *_args, lbl=lbl_hi, var=var_hi: lbl.configure(text=str(var.get())))

        row.columnconfigure(2, weight=1)

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def _on_slider(self, val, label_widget, var: tk.IntVar, is_low: bool, partner: tk.IntVar):
        """Update label and enforce low <= high constraint."""
        ival = int(round(float(val)))
        var.set(ival)
        label_widget.configure(text=str(ival))
        if is_low and ival > partner.get():
            partner.set(ival)
        elif not is_low and ival < partner.get():
            partner.set(ival)

    def _on_apply(self):
        """Save current slider values to config."""
        config.custom_hsv_min_h = self._h_lo.get()
        config.custom_hsv_max_h = self._h_hi.get()
        config.custom_hsv_min_s = self._s_lo.get()
        config.custom_hsv_max_s = self._s_hi.get()
        config.custom_hsv_min_v = self._v_lo.get()
        config.custom_hsv_max_v = self._v_hi.get()
        config.save_to_file()
        log_print(
            f"[HsvPreview] Applied: H[{self._h_lo.get()}-{self._h_hi.get()}] "
            f"S[{self._s_lo.get()}-{self._s_hi.get()}] "
            f"V[{self._v_lo.get()}-{self._v_hi.get()}]"
        )
        if self.on_apply_callback:
            self.on_apply_callback()

    def _on_reset(self):
        """Restore values from saved config."""
        self._set_eyedropper_active(False)
        self._h_lo.set(int(getattr(config, "custom_hsv_min_h", 0)))
        self._h_hi.set(int(getattr(config, "custom_hsv_max_h", 179)))
        self._s_lo.set(int(getattr(config, "custom_hsv_min_s", 0)))
        self._s_hi.set(int(getattr(config, "custom_hsv_max_s", 255)))
        self._v_lo.set(int(getattr(config, "custom_hsv_min_v", 0)))
        self._v_hi.set(int(getattr(config, "custom_hsv_max_v", 255)))
        self._lbl_pick.configure(text=t("Pick mode: Off"))

    def _start_pick(self, role: str):
        self._pick_role = role
        self._set_eyedropper_active(True)
        lbl = "Pick TARGET (click enemy)" if role == "target" else "Pick BG (click wall/noise)"
        self._lbl_pick.configure(text=lbl)

    def _load_preset(self, preset_key: str):
        preset = XUDP_HSV_PRESETS.get(preset_key)
        if not preset:
            return
        lo, hi = preset[0]
        self._h_lo.set(int(lo[0]))
        self._h_hi.set(int(hi[0]))
        self._s_lo.set(int(lo[1]))
        self._s_hi.set(int(hi[1]))
        self._v_lo.set(int(lo[2]))
        self._v_hi.set(int(hi[2]))
        self._lbl_pick.configure(text=f"Preset: {preset_key}")

    def _auto_solve_samples(self):
        if not self._target_samples:
            self._lbl_pick.configure(text="Pick at least 1 Target pixel first")
            return
        h_lo, h_hi, s_lo, s_hi, v_lo, v_hi = solve_contrast_hsv(
            self._target_samples, self._bg_samples
        )
        self._h_lo.set(h_lo)
        self._h_hi.set(h_hi)
        self._s_lo.set(s_lo)
        self._s_hi.set(s_hi)
        self._v_lo.set(v_lo)
        self._v_hi.set(v_hi)
        self._lbl_pick.configure(
            text=f"Solved ({len(self._target_samples)}T/{len(self._bg_samples)}BG)"
        )

    def _toggle_eyedropper(self):
        self._pick_role = "target"
        self._set_eyedropper_active(not self._eyedropper_active)

    def _set_eyedropper_active(self, is_active: bool):
        self._eyedropper_active = bool(is_active)

        cursor = "crosshair" if self._eyedropper_active else ""
        for canvas in self._preview_canvases:
            canvas.configure(cursor=cursor)

        if self._eyedropper_active:
            self._btn_eyedropper.configure(
                fg_color=COLOR_SUCCESS,
                hover_color="#388E3C",
                text_color="#000000",
            )
            self._lbl_pick.configure(text=t("Pick mode: ON (click preview)"))
        else:
            self._btn_eyedropper.configure(
                fg_color=COLOR_SURFACE,
                hover_color=COLOR_BORDER,
                text_color=COLOR_TEXT,
            )

    def _on_preview_click(self, event):
        if not self._eyedropper_active or self._preview_hsv is None:
            return

        x = max(0, min(int(event.x), PREVIEW_W - 1))
        y = max(0, min(int(event.y), PREVIEW_H - 1))

        src_h, src_w = self._preview_hsv.shape[:2]
        src_x = min(src_w - 1, int(x * src_w / PREVIEW_W))
        src_y = min(src_h - 1, int(y * src_h / PREVIEW_H))

        h, s, v = [int(vv) for vv in self._preview_hsv[src_y, src_x]]
        if self._pick_role == "bg":
            self._bg_samples.append((h, s, v))
            if self._target_samples:
                self._auto_solve_samples()
            else:
                self._lbl_pick.configure(text=f"BG sample ({len(self._bg_samples)}): {h},{s},{v}")
        else:
            self._target_samples.append((h, s, v))
            if len(self._target_samples) == 1 and not self._bg_samples:
                self._set_hsv_range_from_pick(h, s, v)
                self._lbl_pick.configure(text=f"Target: {h},{s},{v} (pick BG or Apply)")
            else:
                self._auto_solve_samples()
        self._set_eyedropper_active(False)
        log_print(f"[HsvPreview] Eyedropper ({self._pick_role}) picked HSV ({h}, {s}, {v}) at ({src_x}, {src_y})")

    def _set_hsv_range_from_pick(self, h: int, s: int, v: int):
        self._h_lo.set(max(0, h - EYEDROPPER_H_TOL))
        self._h_hi.set(min(179, h + EYEDROPPER_H_TOL))
        self._s_lo.set(max(0, s - EYEDROPPER_S_TOL))
        self._s_hi.set(min(255, s + EYEDROPPER_S_TOL))
        self._v_lo.set(max(0, v - EYEDROPPER_V_TOL))
        self._v_hi.set(min(255, v + EYEDROPPER_V_TOL))

    @staticmethod
    def _load_eyedropper_icon():
        icon_path = get_bundle_dir() / "themes" / "icon" / "EyedropperTool.png"
        if not icon_path.exists():
            log_print(f"[HsvPreview] Eyedropper icon not found: {icon_path}")
            return None

        try:
            icon_img = Image.open(icon_path).convert("RGBA")
            return ctk.CTkImage(light_image=icon_img, dark_image=icon_img, size=(18, 18))
        except Exception as exc:
            log_print(f"[HsvPreview] Failed to load eyedropper icon: {exc}")
            return None

    def _on_close(self):
        self._running = False
        try:
            self.destroy()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Capture thread
    # ------------------------------------------------------------------

    def _start_capture_thread(self):
        t = threading.Thread(target=self._capture_loop, daemon=True)
        t.start()

    def _capture_loop(self):
        while self._running:
            bgr = _grab_frame_bgr(self.capture_service)
            if bgr is not None:
                with self._lock:
                    self._last_bgr = bgr
            time.sleep(0.05)  # ~20 fps

    # ------------------------------------------------------------------
    # Preview update loop (main thread via after)
    # ------------------------------------------------------------------

    def _schedule_update(self):
        if not self._running:
            return
        try:
            self._update_preview()
        except Exception as exc:
            log_print(f"[HsvPreview] update error: {exc}")
        self.after(50, self._schedule_update)  # ~20 fps

    def _update_preview(self):
        with self._lock:
            bgr = self._last_bgr.copy() if self._last_bgr is not None else None

        if bgr is None:
            bgr = self._make_placeholder()

        h_lo, h_hi = self._h_lo.get(), self._h_hi.get()
        s_lo, s_hi = self._s_lo.get(), self._s_hi.get()
        v_lo, v_hi = self._v_lo.get(), self._v_hi.get()

        self._preview_hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        result, mask = _apply_hsv_mask(bgr, h_lo, h_hi, s_lo, s_hi, v_lo, v_hi)

        if getattr(self, "_full_det_var", None) is not None and self._full_det_var.get() and self._det_model is not None:
            try:
                old_vals = (
                    config.color,
                    config.custom_hsv_min_h, config.custom_hsv_max_h,
                    config.custom_hsv_min_s, config.custom_hsv_max_s,
                    config.custom_hsv_min_v, config.custom_hsv_max_v,
                )
                config.color = "custom"
                config.custom_hsv_min_h, config.custom_hsv_max_h = h_lo, h_hi
                config.custom_hsv_min_s, config.custom_hsv_max_s = s_lo, s_hi
                config.custom_hsv_min_v, config.custom_hsv_max_v = v_lo, v_hi
                dets, det_mask = perform_detection(self._det_model, bgr, stabilize=False)
                if det_mask is not None:
                    mask = det_mask
                for det in dets:
                    bx, by, bw, bh = det["bbox"]
                    cv2.rectangle(result, (int(bx), int(by)), (int(bx + bw), int(by + bh)), (0, 255, 160), 2)
                    hx = int(bx + bw * 0.5)
                    hy = int(by + bh * 0.22)
                    cv2.circle(result, (hx, hy), 4, (0, 80, 255), -1)
            except Exception:
                pass
            finally:
                (
                    config.color,
                    config.custom_hsv_min_h, config.custom_hsv_max_h,
                    config.custom_hsv_min_s, config.custom_hsv_max_s,
                    config.custom_hsv_min_v, config.custom_hsv_max_v,
                ) = old_vals

        pixel_count = int(cv2.countNonZero(mask))

        self._photo_orig = _bgr_to_pil(bgr, PREVIEW_W, PREVIEW_H)
        self._photo_result = _bgr_to_pil(result, PREVIEW_W, PREVIEW_H)
        self._photo_mask = _gray_to_pil(mask, PREVIEW_W, PREVIEW_H)

        self._canvas_orig.delete("all")
        self._canvas_result.delete("all")
        self._canvas_mask.delete("all")

        self._canvas_orig.create_image(0, 0, anchor="nw", image=self._photo_orig)
        self._canvas_result.create_image(0, 0, anchor="nw", image=self._photo_result)
        self._canvas_mask.create_image(0, 0, anchor="nw", image=self._photo_mask)

        self._lbl_pixels.configure(text=f"Detected pixels: {pixel_count}")

    @staticmethod
    def _make_placeholder() -> np.ndarray:
        """Generate a hue-gradient placeholder when there is no capture signal."""
        img = np.zeros((240, 320, 3), dtype=np.uint8)
        for x in range(320):
            h = int(x / 320 * 179)
            col = cv2.cvtColor(
                np.array([[[h, 200, 200]]], dtype=np.uint8),
                cv2.COLOR_HSV2BGR,
            )[0][0]
            img[:, x] = col

        cv2.putText(
            img,
            "No capture signal",
            (60, 120),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (200, 200, 200),
            1,
            cv2.LINE_AA,
        )
        return img

    def destroy(self):
        self._running = False
        if hasattr(self, "_preview_canvases") and hasattr(self, "_btn_eyedropper"):
            self._set_eyedropper_active(False)
        super().destroy()
