"""
aim_math — Single source of truth for pixel -> mouse-count conversion.

This module replaces the two contradictory, dimensionally wrong converters that
used to live in ``normal.py``:

  * ``calculate_movement()``    : multiplied a PIXEL delta by DEGREES/COUNT and
                                  called the result "counts" (unit error).
  * ``calculate_exact_counts()``: correct geometry, but hard-coded 1920/103 and
                                  the magic constant 54.54 cm/rev.

Everything that needs to turn a screen-pixel error into physical mouse counts
goes through :func:`px_to_counts`. Nothing else is allowed to invent a gain.

Design notes
------------
* Geometry comes from the REAL frame that produced the detection, including any
  centre crop applied by the capture layer. A pixel in a 256x256 crop is not the
  same angle as a pixel of a 1920x1080 downscale.
* A centre crop preserves the angular scale (focal length in pixels): it only
  shows fewer degrees. A smaller *source* resolution sees the same degrees with
  fewer pixels, so its degrees-per-pixel is larger. Both cases are handled.
* ``Calibration`` prefers measured ``counts_per_deg`` (Calibration panel) over
  the analytic model. When a measurement exists, ``54.54`` and ``103.0`` are
  never used.
* All functions are pure and sign-symmetric, so they are unit-testable without
  a capture device.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Analytic constants (only used until a measurement exists)
# ---------------------------------------------------------------------------

#: Physical mouse travel for one full 360 turn at in-game sensitivity 1.0.
#: Kept for backward compatibility of legacy configs; superseded by a measured
#: calibration. This value is NOT authoritative.
DEFAULT_CM_PER_REV: float = 54.54

#: Default horizontal field of view of the native source, in degrees.
DEFAULT_HFOV_DEG: float = 103.0

#: Fallbacks used when neither config nor tracker supplies a value.
DEFAULT_DPI: float = 1100.0
DEFAULT_SENS: float = 0.23

#: A measurement diverging this much from the analytic model is suspicious.
MEASURED_DIVERGENCE_WARN: float = 0.20


# ---------------------------------------------------------------------------
# Small numeric helpers
# ---------------------------------------------------------------------------


def _as_positive_float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return float(default)
    if parsed != parsed or parsed in (float("inf"), float("-inf")):
        return float(default)
    return parsed


def _as_positive_int(value: Any) -> Optional[int]:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FrameGeometry:
    """Geometry of the region of the world that the current frame actually sees."""

    frame_w: int
    frame_h: int
    hfov_deg: float
    vfov_deg: float
    source: str = "analytic"

    def __post_init__(self) -> None:
        if int(self.frame_w) <= 0 or int(self.frame_h) <= 0:
            raise ValueError(f"invalid frame size: {self.frame_w}x{self.frame_h}")
        if not (0.0 < float(self.hfov_deg) < 180.0):
            raise ValueError(f"invalid hfov_deg: {self.hfov_deg}")
        if not (0.0 < float(self.vfov_deg) < 180.0):
            raise ValueError(f"invalid vfov_deg: {self.vfov_deg}")

    # -- focal lengths in pixels -------------------------------------------
    @property
    def focal_x(self) -> float:
        """Focal length in pixels along X: (w/2) / tan(hfov/2)."""
        return (float(self.frame_w) / 2.0) / math.tan(math.radians(float(self.hfov_deg) / 2.0))

    @property
    def focal_y(self) -> float:
        """Focal length in pixels along Y: (h/2) / tan(vfov/2)."""
        return (float(self.frame_h) / 2.0) / math.tan(math.radians(float(self.vfov_deg) / 2.0))

    @property
    def aspect(self) -> float:
        return float(self.frame_w) / float(self.frame_h)

    @property
    def center_x(self) -> float:
        return float(self.frame_w) / 2.0

    @property
    def center_y(self) -> float:
        return float(self.frame_h) / 2.0

    # -- conversions --------------------------------------------------------
    def px_to_deg(self, dx: float, dy: float) -> Tuple[float, float]:
        """Pixel offset from frame centre -> (yaw, pitch) in degrees."""
        deg_x = math.degrees(math.atan2(float(dx), self.focal_x))
        deg_y = math.degrees(math.atan2(float(dy), self.focal_y))
        return deg_x, deg_y

    def deg_to_px(self, dx_deg: float, dy_deg: float) -> Tuple[float, float]:
        """Inverse of :meth:`px_to_deg`."""
        px_x = math.tan(math.radians(float(dx_deg))) * self.focal_x
        px_y = math.tan(math.radians(float(dy_deg))) * self.focal_y
        return px_x, px_y

    def deg_per_px_at_center(self) -> Tuple[float, float]:
        """Small-angle degrees-per-pixel at the frame centre."""
        return (
            math.degrees(1.0 / self.focal_x),
            math.degrees(1.0 / self.focal_y),
        )


def vfov_from_hfov(hfov_deg: float, frame_w: int, frame_h: int) -> float:
    """Derive vertical FOV from horizontal FOV for square pixels."""
    if int(frame_w) <= 0 or int(frame_h) <= 0:
        raise ValueError(f"invalid frame size: {frame_w}x{frame_h}")
    half_h = math.radians(float(hfov_deg) / 2.0)
    tan_v = math.tan(half_h) * (float(frame_h) / float(frame_w))
    return math.degrees(2.0 * math.atan(tan_v))


def hfov_from_focal(frame_w: int, focal_px: float) -> float:
    """Horizontal FOV covered by ``frame_w`` pixels at ``focal_px``."""
    return math.degrees(2.0 * math.atan((float(frame_w) / 2.0) / max(float(focal_px), 1e-9)))


def geometry_from_native(
    native_w: int = 1920,
    native_h: int = 1080,
    hfov_deg: float = DEFAULT_HFOV_DEG,
    vfov_deg: Optional[float] = None,
    region_w: Optional[int] = None,
    region_h: Optional[int] = None,
    source: str = "analytic",
) -> FrameGeometry:
    """Geometry of a centre region of a native source with known FOV.

    The native source sees ``hfov_deg`` across ``native_w`` pixels. Focal length
    (pixels per radian) is invariant under a centre crop, so the region inherits
    it and simply covers fewer degrees.
    """
    native_w_i = max(1, int(native_w))
    native_h_i = max(1, int(native_h))
    region_w_i = max(1, int(region_w or native_w_i))
    region_h_i = max(1, int(region_h or native_h_i))

    focal_x = (native_w_i / 2.0) / math.tan(math.radians(float(hfov_deg) / 2.0))
    explicit_vfov = _as_positive_float(vfov_deg, 0.0)
    if 0.0 < explicit_vfov < 180.0:
        focal_y = (native_h_i / 2.0) / math.tan(math.radians(explicit_vfov) / 2.0)
    else:
        focal_y = focal_x

    return FrameGeometry(
        frame_w=region_w_i,
        frame_h=region_h_i,
        hfov_deg=hfov_from_focal(region_w_i, focal_x),
        vfov_deg=hfov_from_focal(region_h_i, focal_y),
        source=source,
    )


# ---------------------------------------------------------------------------
# Capture-crop resolution
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CropInfo:
    """How the analysed region relates to the native source frame."""

    crop_w: Optional[int] = None
    crop_h: Optional[int] = None
    native_w: Optional[int] = None
    native_h: Optional[int] = None

    @property
    def is_cropped(self) -> bool:
        if not self.crop_w or not self.crop_h or not self.native_w or not self.native_h:
            return False
        return int(self.crop_w) < int(self.native_w) or int(self.crop_h) < int(self.native_h)


def resolve_crop_info(
    *,
    capture_mode: str = "",
    udp_fov_enabled: bool = False,
    udp_fov: Any = None,
    ndi_fov_enabled: bool = False,
    ndi_fov: Any = None,
    capture_range_x: Any = None,
    capture_range_y: Any = None,
    native_w: Any = None,
    native_h: Any = None,
) -> CropInfo:
    """Work out whether the analysed region is a centre crop of the native frame.

    Mirrors the crop rules in ``capture_service._apply_mode_fov`` (NDI/UDP centre
    crop with half-extent ``fov``) and ``CaptureCard`` (``capture_range_*`` is the
    full extent).
    """
    mode = str(capture_mode or "").strip()
    native_w_i = _as_positive_int(native_w)
    native_h_i = _as_positive_int(native_h)
    crop_w: Optional[int] = None
    crop_h: Optional[int] = None

    if mode == "UDP" and bool(udp_fov_enabled):
        half = _as_positive_int(udp_fov)
        if half:
            crop_w = crop_h = 2 * half
    elif mode == "NDI" and bool(ndi_fov_enabled):
        half = _as_positive_int(ndi_fov)
        if half:
            crop_w = crop_h = 2 * half
    elif mode in ("CaptureCard", "CaptureCardGStreamer"):
        range_x = _as_positive_int(capture_range_x)
        range_y = _as_positive_int(capture_range_y)
        if range_x and range_y:
            crop_w, crop_h = range_x, range_y

    if crop_w is None or crop_h is None:
        return CropInfo(None, None, native_w_i, native_h_i)

    if native_w_i:
        crop_w = min(crop_w, native_w_i)
    if native_h_i:
        crop_h = min(crop_h, native_h_i)
    return CropInfo(crop_w, crop_h, native_w_i, native_h_i)


def _frame_size(frame: Any) -> Tuple[int, int]:
    if frame is None:
        return 0, 0
    for attr_w, attr_h in (("xres", "yres"), ("width", "height"), ("w", "h")):
        w = getattr(frame, attr_w, None)
        h = getattr(frame, attr_h, None)
        if w is not None and h is not None:
            try:
                return int(w), int(h)
            except (TypeError, ValueError):
                pass
    shape = getattr(frame, "shape", None)
    if shape is not None and len(shape) >= 2:
        try:
            return int(shape[1]), int(shape[0])
        except (TypeError, ValueError):
            pass
    return 0, 0


def _resolve_capture_service(tracker: Any) -> Any:
    if tracker is None:
        return None
    capture = getattr(tracker, "capture_service", None)
    if capture is not None:
        return capture
    capture = getattr(tracker, "capture", None)
    if capture is not None:
        return capture
    app = getattr(tracker, "app", None)
    if app is not None:
        return getattr(app, "capture", None)
    return None


def resolve_geometry(
    frame: Any = None,
    *,
    frame_w: Any = None,
    frame_h: Any = None,
    cfg: Any = None,
    tracker: Any = None,
) -> FrameGeometry:
    """Build a :class:`FrameGeometry` for the frame currently being analysed.

    Parameters
    ----------
    frame:
        Object carrying ``xres``/``yres`` (e.g. ``main.FrameInfo``) or a numpy
        array with ``shape``.
    cfg:
        Config-like object (defaults to the global ``src.utils.config.config``).
    tracker:
        Optional tracker; may expose ``capture``/``app.capture``.
    """
    if frame_w is None or frame_h is None:
        if frame is None:
            # Fall back to the frame the tracker last analysed.
            frame = getattr(tracker, "_aim_frame", None) or getattr(tracker, "_last_frame", None)
        width, height = _frame_size(frame)
        frame_w = width if frame_w is None else frame_w
        frame_h = height if frame_h is None else frame_h

    region_w = _as_positive_int(frame_w) or 0
    region_h = _as_positive_int(frame_h) or 0

    if cfg is None:
        try:
            from src.utils.config import config as cfg  # local import avoids a cycle
        except Exception:  # pragma: no cover - config always importable in-app
            cfg = None

    def _get(name: str, default: Any) -> Any:
        if isinstance(cfg, dict):
            return cfg.get(name, default)
        if cfg is None:
            return default
        return getattr(cfg, name, default)

    hfov_deg = _as_positive_float(_get("hfov_deg", DEFAULT_HFOV_DEG), DEFAULT_HFOV_DEG)
    if not (0.0 < hfov_deg < 180.0):
        hfov_deg = DEFAULT_HFOV_DEG
    configured_vfov = _as_positive_float(_get("vfov_deg", 0.0), 0.0)

    capture = _resolve_capture_service(tracker)
    capture_mode = str(_get("capture_mode", "") or "")
    if not capture_mode and capture is not None:
        capture_mode = str(getattr(capture, "mode", "") or "")

    configured_native_w = _as_positive_int(_get("capture_width", None))
    configured_native_h = _as_positive_int(_get("capture_height", None))

    crop = resolve_crop_info(
        capture_mode=capture_mode,
        udp_fov_enabled=bool(_get("udp_fov_enabled", False)),
        udp_fov=_get("udp_fov", None),
        ndi_fov_enabled=bool(_get("ndi_fov_enabled", False)),
        ndi_fov=_get("ndi_fov", None),
        capture_range_x=_get("capture_range_x", None),
        capture_range_y=_get("capture_range_y", None),
        native_w=configured_native_w,
        native_h=configured_native_h,
    )

    # Default assumption: the frame we received IS the raster that ``hfov_deg``
    # describes. ``hfov_deg`` is the FOV of the frame handed to the detector, so
    # a downscale (1920 -> 256 pixels of the same 103 degrees) is handled by the
    # frame size alone. Only an EXPLICIT centre-crop option makes the frame a
    # sub-region of a wider native raster; there, focal length is invariant.
    native_w, native_h = region_w, region_h
    source = "analytic"
    if crop.is_cropped:
        native_w = int(crop.native_w)
        native_h = int(crop.native_h)
        # Trust the frame we actually received when it disagrees with config;
        # the received pixels are what the detector measured.
        if region_w and region_h and (
            abs(int(crop.crop_w) - region_w) > 1 or abs(int(crop.crop_h) - region_h) > 1
        ):
            region_w, region_h = int(crop.crop_w), int(crop.crop_h)
        region_w = min(region_w, native_w) if region_w else native_w
        region_h = min(region_h, native_h) if region_h else native_h
        source = "crop"

    if not region_w or not region_h:
        region_w, region_h = native_w, native_h
    if not region_w or not region_h:
        # Nothing usable; fall back to a sane 16:9 raster so callers never crash.
        region_w, region_h = 1920, 1080
        native_w, native_h = 1920, 1080

    native_w = max(int(native_w or region_w), int(region_w))
    native_h = max(int(native_h or region_h), int(region_h))

    explicit_vfov = configured_vfov if 0.0 < configured_vfov < 180.0 else None

    return geometry_from_native(
        native_w=native_w,
        native_h=native_h,
        hfov_deg=hfov_deg,
        vfov_deg=explicit_vfov,
        region_w=region_w,
        region_h=region_h,
        source=source,
    )


# ---------------------------------------------------------------------------
# Calibration (the one place counts come from)
# ---------------------------------------------------------------------------


@dataclass
class Calibration:
    """Maps angles to mouse counts.

    ``counts_per_deg_x/y`` come either from the analytic model (sensitivity, DPI,
    cm/rev) or from a real measurement. A measured calibration always wins.
    """

    counts_per_deg_x: Optional[float] = None
    counts_per_deg_y: Optional[float] = None
    source: str = "analytic"
    sens: float = DEFAULT_SENS
    dpi: float = DEFAULT_DPI
    cm_per_rev: float = DEFAULT_CM_PER_REV

    def __post_init__(self) -> None:
        measured_x = _as_positive_float(self.counts_per_deg_x, 0.0)
        measured_y = _as_positive_float(self.counts_per_deg_y, 0.0)
        self.counts_per_deg_x = measured_x if measured_x > 0.0 else None
        self.counts_per_deg_y = measured_y if measured_y > 0.0 else None
        self.sens = max(0.01, _as_positive_float(self.sens, DEFAULT_SENS) or DEFAULT_SENS)
        self.dpi = max(1.0, _as_positive_float(self.dpi, DEFAULT_DPI) or DEFAULT_DPI)
        self.cm_per_rev = max(
            0.01, _as_positive_float(self.cm_per_rev, DEFAULT_CM_PER_REV) or DEFAULT_CM_PER_REV
        )

        # A complete pair of supplied scales IS a measurement. An incomplete pair
        # is not usable, so both axes fall back to the analytic model together
        # (a half-measured calibration would silently skew one axis only).
        if self.counts_per_deg_x is not None and self.counts_per_deg_y is not None:
            self.source = "measured"
            return

        self.source = "analytic"
        analytic = self.analytic_counts_per_deg()
        self.counts_per_deg_x = analytic
        self.counts_per_deg_y = analytic

    # -- analytic fallback --------------------------------------------------
    @property
    def deg_per_count(self) -> float:
        cm_per_rev = self.cm_per_rev / max(self.sens, 0.01)
        counts_per_cm = self.dpi / 2.54
        return 360.0 / max(1e-9, cm_per_rev * counts_per_cm)

    def analytic_counts_per_deg(self) -> float:
        return 1.0 / max(1e-9, self.deg_per_count)

    @property
    def is_measured(self) -> bool:
        return self.source == "measured"

    @property
    def divergence_from_analytic(self) -> float:
        """Relative difference between the active scale and the analytic model."""
        analytic = self.analytic_counts_per_deg()
        if analytic <= 0:
            return 0.0
        return (float(self.counts_per_deg_x) - analytic) / analytic

    def needs_recalibration_warning(self) -> bool:
        return self.is_measured and abs(self.divergence_from_analytic) > MEASURED_DIVERGENCE_WARN

    # -- conversion ---------------------------------------------------------
    def deg_to_counts(self, dx_deg: float, dy_deg: float) -> Tuple[float, float]:
        return (
            float(dx_deg) * float(self.counts_per_deg_x),
            float(dy_deg) * float(self.counts_per_deg_y),
        )

    def counts_to_deg(self, counts_x: float, counts_y: float) -> Tuple[float, float]:
        return (
            float(counts_x) / float(self.counts_per_deg_x),
            float(counts_y) / float(self.counts_per_deg_y),
        )

    def px_to_counts(self, geometry: FrameGeometry, dx: float, dy: float) -> Tuple[float, float]:
        deg_x, deg_y = geometry.px_to_deg(dx, dy)
        return self.deg_to_counts(deg_x, deg_y)

    def describe(self) -> str:
        return (
            f"Calibration(source={self.source}, "
            f"counts/deg=({float(self.counts_per_deg_x):.4f}, "
            f"{float(self.counts_per_deg_y):.4f}), "
            f"sens={self.sens:.4f}, dpi={self.dpi:.1f})"
        )


def resolve_calibration(cfg: Any = None, tracker: Any = None) -> Calibration:
    """Build the active :class:`Calibration` from config/tracker."""
    if cfg is None:
        try:
            from src.utils.config import config as cfg
        except Exception:  # pragma: no cover
            cfg = None

    def _get(name: str, default: Any) -> Any:
        if isinstance(cfg, dict):
            return cfg.get(name, default)
        if cfg is None:
            return default
        return getattr(cfg, name, default)

    sens = _get("in_game_sens", getattr(tracker, "in_game_sens", DEFAULT_SENS))
    dpi = _get("mouse_dpi", getattr(tracker, "mouse_dpi", DEFAULT_DPI))
    cm_per_rev = _get("cm_per_rev", DEFAULT_CM_PER_REV)

    measured_x = _as_positive_float(_get("counts_per_deg_x", None), 0.0)
    measured_y = _as_positive_float(_get("counts_per_deg_y", None), 0.0)

    if measured_x > 0.0 and measured_y > 0.0:
        return Calibration(
            counts_per_deg_x=measured_x,
            counts_per_deg_y=measured_y,
            source="measured",
            sens=sens,
            dpi=dpi,
            cm_per_rev=cm_per_rev,
        )
    return Calibration(sens=sens, dpi=dpi, cm_per_rev=cm_per_rev)


def px_to_counts(
    dx: float,
    dy: float,
    *,
    geometry: Optional[FrameGeometry] = None,
    calibration: Optional[Calibration] = None,
    cfg: Any = None,
    tracker: Any = None,
    frame: Any = None,
) -> Tuple[float, float]:
    """THE public API: pixel error -> physical mouse counts.

    Sign-symmetric: ``f(-dx) == -f(dx)``.
    """
    if geometry is None:
        geometry = resolve_geometry(frame=frame, cfg=cfg, tracker=tracker)
    if calibration is None:
        calibration = resolve_calibration(cfg=cfg, tracker=tracker)
    return calibration.px_to_counts(geometry, dx, dy)


# ---------------------------------------------------------------------------
# Legacy compatibility wrappers
# ---------------------------------------------------------------------------


def legacy_exact_counts(
    dx: float,
    dy: float,
    sens: float,
    dpi: float,
    screen_w: int = 1920,
    fov_deg: float = DEFAULT_HFOV_DEG,
) -> Tuple[float, float]:
    """Back-compat for the old ``calculate_exact_counts`` signature.

    Deprecated: callers should use :func:`px_to_counts`. The 1920/103 defaults are
    kept only so legacy call sites keep working.
    """
    width = max(1, int(screen_w))
    height = max(1, int(round(width * 9.0 / 16.0)))
    geometry = geometry_from_native(
        native_w=width,
        native_h=height,
        hfov_deg=float(fov_deg),
        region_w=width,
        region_h=height,
    )
    return Calibration(sens=sens, dpi=dpi).px_to_counts(geometry, dx, dy)


#: Engines for the CLOSED-LOOP modes (Normal/PID/NCAF/WindMouse/Bezier).
#:
#: ``legacy`` keeps the pre-fix kinematic scale so existing tuning keeps working
#: while the v2 path is A/B tested per mode (plan section 10). ``v2`` uses
#: physical counts and therefore requires the speed/smoothing knobs to be
#: retuned; it is opt-in and never silently applied.
ENGINE_LEGACY = "legacy"
ENGINE_V2 = "v2"


def closed_loop_counts(
    dx: float,
    dy: float,
    *,
    sens: float = DEFAULT_SENS,
    dpi: float = DEFAULT_DPI,
    engine: str = ENGINE_LEGACY,
    geometry: Optional[FrameGeometry] = None,
    calibration: Optional[Calibration] = None,
    cm_per_rev: float = DEFAULT_CM_PER_REV,
) -> Tuple[float, float]:
    """Pixel error -> per-frame delta for closed-loop (tracking) modes.

    ``engine="legacy"`` reproduces the pre-fix numbers exactly, so existing
    ``normal_x_speed`` / ``normalsmooth`` tuning is preserved. It is explicitly
    gain-compensated debt: the old scale was dimensional nonsense whose shortfall
    was cancelled by large speed values.

    ``engine="v2"`` returns physical counts from :func:`px_to_counts`; the caller's
    speed knobs then act as a fraction of the remaining error and must be
    retuned. Default stays ``legacy`` until each mode is A/B verified.
    """
    if str(engine or "").strip().lower() == ENGINE_V2:
        if calibration is None:
            calibration = Calibration(sens=sens, dpi=dpi, cm_per_rev=cm_per_rev)
        if geometry is None:
            geometry = FrameGeometry(
                frame_w=1920,
                frame_h=1080,
                hfov_deg=DEFAULT_HFOV_DEG,
                vfov_deg=vfov_from_hfov(DEFAULT_HFOV_DEG, 1920, 1080),
            )
        return calibration.px_to_counts(geometry, dx, dy)

    # Legacy path: identical arithmetic to the retired calculate_movement().
    deg_per_count = Calibration(sens=sens, dpi=dpi, cm_per_rev=cm_per_rev).deg_per_count
    return float(dx) * deg_per_count, float(dy) * deg_per_count


# ---------------------------------------------------------------------------
# Experimental calibration fitting (Calibration panel & tests)
# ---------------------------------------------------------------------------


def fit_calibration(
    samples: Iterable[Sequence[float]],
    *,
    min_r2: float = 0.99,
) -> Optional[Tuple[float, float, float]]:
    """Least-squares fit of ``counts = slope * px + intercept``.

    ``samples`` is an iterable of ``(px_delta, counts)`` pairs for one axis.

    Returns ``(counts_per_px, intercept, r2)`` or ``None`` when the data is
    insufficient or too noisy (``r2 < min_r2``).
    """
    points = []
    for item in samples or ():
        try:
            px, counts = float(item[0]), float(item[1])
        except (TypeError, ValueError, IndexError):
            continue
        points.append((px, counts))
    if len(points) < 2:
        return None

    n = float(len(points))
    sum_x = sum(p[0] for p in points)
    sum_y = sum(p[1] for p in points)
    sum_xx = sum(p[0] * p[0] for p in points)
    sum_xy = sum(p[0] * p[1] for p in points)

    denom = n * sum_xx - sum_x * sum_x
    if abs(denom) < 1e-12:
        return None
    slope = (n * sum_xy - sum_x * sum_y) / denom
    intercept = (sum_y - slope * sum_x) / n
    if slope <= 0.0:
        return None

    mean_y = sum_y / n
    ss_tot = sum((p[1] - mean_y) ** 2 for p in points)
    ss_res = sum((p[1] - (slope * p[0] + intercept)) ** 2 for p in points)
    if ss_tot <= 1e-12:
        return None
    r2 = 1.0 - (ss_res / ss_tot)
    if r2 < float(min_r2):
        return None
    return slope, intercept, r2


def counts_per_deg_from_slope(
    geometry: FrameGeometry,
    counts_per_px_x: float,
    counts_per_px_y: float,
) -> Tuple[float, float]:
    """Convert measured counts-per-pixel slopes into counts-per-degree."""
    deg_per_px_x, deg_per_px_y = geometry.deg_per_px_at_center()
    return (
        float(counts_per_px_x) / deg_per_px_x if deg_per_px_x > 0 else 0.0,
        float(counts_per_px_y) / deg_per_px_y if deg_per_px_y > 0 else 0.0,
    )
