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
from collections import OrderedDict
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

#: Valorant yaw per mouse count at in-game sensitivity 1.0.
#: ``deg_per_count(sens) = 0.07 * sens`` and therefore
#: ``counts_per_deg(sens) = 1 / (0.07 * sens)`` -> 62.112 counts/deg at 0.23.
DEFAULT_VALORANT_DEG_PER_COUNT: float = 0.07

#: Calibration sources (explicit, never inferred at resolve time).
SOURCE_VALORANT = "valorant"
SOURCE_MEASURED = "measured"
SOURCE_ANALYTIC = "analytic"

#: A measurement diverging this much from the analytic model is suspicious.
MEASURED_DIVERGENCE_WARN: float = 0.20

#: A measurement whose sensitivity moved this much should be re-measured.
SENS_DRIFT_WARN: float = 0.02


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


def _cfg_getter(cfg: Any):
    """Return ``get(name, default)`` for a dict, object or ``None``."""
    if isinstance(cfg, dict):
        return lambda name, default: cfg.get(name, default)
    if cfg is None:
        return lambda name, default: default
    return lambda name, default: getattr(cfg, name, default)


# ---------------------------------------------------------------------------
# Caches (plan 7.3)
# ---------------------------------------------------------------------------
#
# Geometry/calibration are pure functions of a handful of scalars, but they were
# rebuilt every frame: ``FrameGeometry`` construction plus several trigonometry
# calls, and a dozen ``getattr`` reads. Both are cached under a SIGNATURE that
# includes every input, so a change to crop, FOV or sensitivity invalidates it.

_MAX_CACHE_ENTRIES = 32
_GEOMETRY_CACHE: "OrderedDict[tuple, FrameGeometry]" = OrderedDict()
_CALIBRATION_CACHE: "OrderedDict[tuple, Calibration]" = OrderedDict()


def _cache_put(cache, key: tuple, value):
    cache[key] = value
    cache.move_to_end(key)
    while len(cache) > _MAX_CACHE_ENTRIES:
        cache.popitem(last=False)
    return value


def clear_caches() -> None:
    """Drop every cached geometry/calibration (tests, config reload)."""
    _GEOMETRY_CACHE.clear()
    _CALIBRATION_CACHE.clear()


def cache_sizes() -> Tuple[int, int]:
    """``(geometry_entries, calibration_entries)`` — used by tests."""
    return len(_GEOMETRY_CACHE), len(_CALIBRATION_CACHE)


def resolve_calibration(cfg: Any = None, tracker: Any = None) -> Calibration:
    """Build the active :class:`Calibration` from config/tracker.

    ``calibration_source`` is authoritative (plan 10.3):

    * ``valorant`` recomputes ``1 / (deg_per_count * sens)`` on every call, so a
      sensitivity change takes effect immediately (0.23 -> 0.40 must NOT keep
      using 62.11 c/deg, which is 42 % too much travel).
    * ``measured`` uses the stored pair and never rescales with sens.
    * ``analytic`` falls back to the legacy ``cm_per_rev`` model.
    """
    if cfg is None:
        try:
            from src.utils.config import config as cfg  # local import avoids a cycle
        except Exception:  # pragma: no cover
            cfg = None

    _get = _cfg_getter(cfg)

    sens = _get("in_game_sens", getattr(tracker, "in_game_sens", DEFAULT_SENS))
    dpi = _get("mouse_dpi", getattr(tracker, "mouse_dpi", DEFAULT_DPI))
    cm_per_rev = _get("cm_per_rev", DEFAULT_CM_PER_REV)
    deg_per_count = _get(
        "valorant_deg_per_count", DEFAULT_VALORANT_DEG_PER_COUNT
    )
    samples = _get("calibration_samples", 0)
    r2 = _get("calibration_r2", 0.0)
    sens_at_measurement = _get("calibration_sens_at_measurement", 0.0)

    source = str(_get("calibration_source", "") or "").strip().lower()
    measured_x = _as_positive_float(_get("counts_per_deg_x", None), 0.0)
    measured_y = _as_positive_float(_get("counts_per_deg_y", None), 0.0)
    has_pair = measured_x > 0.0 and measured_y > 0.0

    common = dict(
        sens=sens,
        dpi=dpi,
        cm_per_rev=cm_per_rev,
        valorant_deg_per_count=deg_per_count,
        samples=samples,
        r2=r2,
        sens_at_measurement=sens_at_measurement,
    )

    if source == SOURCE_VALORANT:
        return Calibration(source=SOURCE_VALORANT, **common)
    if source == SOURCE_MEASURED and has_pair:
        return Calibration(
            counts_per_deg_x=measured_x,
            counts_per_deg_y=measured_y,
            source=SOURCE_MEASURED,
            **common,
        )
    if not source:
        # Un-migrated caller: a complete pair is a measurement, else analytic.
        if has_pair:
            return Calibration(
                counts_per_deg_x=measured_x,
                counts_per_deg_y=measured_y,
                source=SOURCE_MEASURED,
                **common,
            )
        return Calibration(source=SOURCE_ANALYTIC, **common)
    # Explicit analytic, or measured without a usable pair.
    return Calibration(source=SOURCE_ANALYTIC, **common)


def resolve_calibration_cached(cfg: Any = None, tracker: Any = None) -> Calibration:
    """:func:`resolve_calibration`, memoised on the scalars that define it.

    The signature includes the source plus every number the formula reads, so a
    sensitivity change (valorant) or a new measurement invalidates it.
    """
    if cfg is None:
        # Resolve the SAME object resolve_calibration() will read, otherwise the
        # signature would be built from defaults while the value came from the
        # global config (a cache that never invalidates).
        try:
            from src.utils.config import config as cfg  # local import avoids a cycle
        except Exception:  # pragma: no cover
            cfg = None

    _get = _cfg_getter(cfg)

    def _r(name: str, default: Any, digits: int = 9) -> Any:
        value = _get(name, default)
        try:
            return round(float(value), digits)
        except (TypeError, ValueError):
            return str(value)

    signature = (
        str(_get("calibration_source", "") or "").strip().lower(),
        _r("counts_per_deg_x", 0.0),
        _r("counts_per_deg_y", 0.0),
        _r("in_game_sens", getattr(tracker, "in_game_sens", DEFAULT_SENS)),
        _r("mouse_dpi", getattr(tracker, "mouse_dpi", DEFAULT_DPI)),
        _r("cm_per_rev", DEFAULT_CM_PER_REV),
        _r("valorant_deg_per_count", DEFAULT_VALORANT_DEG_PER_COUNT),
        _r("calibration_r2", 0.0),
        _r("calibration_sens_at_measurement", 0.0),
    )
    hit = _CALIBRATION_CACHE.get(signature)
    if hit is not None:
        _CALIBRATION_CACHE.move_to_end(signature)
        return hit
    calibration = resolve_calibration(cfg=cfg, tracker=tracker)
    return _cache_put(_CALIBRATION_CACHE, signature, calibration)


def _collect_geometry_inputs(
    frame: Any,
    frame_w: Any,
    frame_h: Any,
    cfg: Any,
    tracker: Any,
) -> dict:
    """Read every input that affects :func:`resolve_geometry` (once)."""
    if frame_w is None or frame_h is None:
        if frame is None:
            frame = getattr(tracker, "_aim_frame", None) or getattr(tracker, "_last_frame", None)
        width, height = _frame_size(frame)
        frame_w = width if frame_w is None else frame_w
        frame_h = height if frame_h is None else frame_h

    _get = _cfg_getter(cfg)
    capture = _resolve_capture_service(tracker)
    capture_mode = str(_get("capture_mode", "") or "")
    if not capture_mode and capture is not None:
        capture_mode = str(getattr(capture, "mode", "") or "")

    return {
        "frame_w": frame_w,
        "frame_h": frame_h,
        "hfov_deg": _get("hfov_deg", DEFAULT_HFOV_DEG),
        "vfov_deg": _get("vfov_deg", 0.0),
        "capture_mode": capture_mode,
        "udp_fov_enabled": bool(_get("udp_fov_enabled", False)),
        "udp_fov": _get("udp_fov", None),
        "ndi_fov_enabled": bool(_get("ndi_fov_enabled", False)),
        "ndi_fov": _get("ndi_fov", None),
        "capture_range_x": _get("capture_range_x", None),
        "capture_range_y": _get("capture_range_y", None),
        "capture_width": _get("capture_width", None),
        "capture_height": _get("capture_height", None),
    }


def _geometry_signature(inputs: dict) -> tuple:
    def _s(value: Any) -> Any:
        if isinstance(value, (int, float, bool)) or value is None:
            return value
        return str(value)

    return (
        _as_positive_int(inputs["frame_w"]) or 0,
        _as_positive_int(inputs["frame_h"]) or 0,
        round(_as_positive_float(inputs["hfov_deg"], DEFAULT_HFOV_DEG), 6),
        round(_as_positive_float(inputs["vfov_deg"], 0.0), 6),
        _s(inputs["capture_mode"]),
        bool(inputs["udp_fov_enabled"]),
        _s(inputs["udp_fov"]),
        bool(inputs["ndi_fov_enabled"]),
        _s(inputs["ndi_fov"]),
        _s(inputs["capture_range_x"]),
        _s(inputs["capture_range_y"]),
        _s(inputs["capture_width"]),
        _s(inputs["capture_height"]),
    )


def resolve_geometry(
    frame: Any = None,
    *,
    frame_w: Any = None,
    frame_h: Any = None,
    cfg: Any = None,
    tracker: Any = None,
    cached: bool = True,
) -> FrameGeometry:
    """Build (or fetch from cache) a :class:`FrameGeometry` for the live frame.

    Parameters
    ----------
    frame:
        Object carrying ``xres``/``yres`` (e.g. ``main.FrameInfo``) or a numpy
        array with ``shape``.
    cfg:
        Config-like object (defaults to the global ``src.utils.config.config``).
    tracker:
        Optional tracker; may expose ``capture``/``app.capture``.
    cached:
        Set ``False`` to bypass/refresh the cache.
    """
    if cfg is None:
        try:
            from src.utils.config import config as cfg  # local import avoids a cycle
        except Exception:  # pragma: no cover - config always importable in-app
            cfg = None

    inputs = _collect_geometry_inputs(frame, frame_w, frame_h, cfg, tracker)
    signature = _geometry_signature(inputs)
    if cached:
        hit = _GEOMETRY_CACHE.get(signature)
        if hit is not None:
            _GEOMETRY_CACHE.move_to_end(signature)
            return hit

    region_w = _as_positive_int(inputs["frame_w"]) or 0
    region_h = _as_positive_int(inputs["frame_h"]) or 0

    hfov_deg = _as_positive_float(inputs["hfov_deg"], DEFAULT_HFOV_DEG)
    if not (0.0 < hfov_deg < 180.0):
        hfov_deg = DEFAULT_HFOV_DEG
    configured_vfov = _as_positive_float(inputs["vfov_deg"], 0.0)

    crop = resolve_crop_info(
        capture_mode=inputs["capture_mode"],
        udp_fov_enabled=inputs["udp_fov_enabled"],
        udp_fov=inputs["udp_fov"],
        ndi_fov_enabled=inputs["ndi_fov_enabled"],
        ndi_fov=inputs["ndi_fov"],
        capture_range_x=inputs["capture_range_x"],
        capture_range_y=inputs["capture_range_y"],
        native_w=_as_positive_int(inputs["capture_width"]),
        native_h=_as_positive_int(inputs["capture_height"]),
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

    geometry = geometry_from_native(
        native_w=native_w,
        native_h=native_h,
        hfov_deg=hfov_deg,
        vfov_deg=explicit_vfov,
        region_w=region_w,
        region_h=region_h,
        source=source,
    )
    _cache_put(_GEOMETRY_CACHE, signature, geometry)
    return geometry


# ---------------------------------------------------------------------------
# Calibration (the one place counts come from)
# ---------------------------------------------------------------------------


@dataclass
class Calibration:
    """Maps angles to mouse counts.

    ``counts_per_deg_x/y`` come from one of three EXPLICIT sources:

    ``valorant``
        ``1 / (0.07 * sens)`` — the Valorant preset. Recomputed live when the
        sensitivity changes, so a flick never silently loses 40 % of its travel.
    ``measured``
        A real impulse/shift measurement. Invariant under sensitivity; carries
        ``samples``/``r2`` provenance and the sensitivity it was taken at.
    ``analytic``
        The legacy ``cm_per_rev`` model. Kept for compatibility, always flagged
        as untrusted in the UI.
    """

    counts_per_deg_x: Optional[float] = None
    counts_per_deg_y: Optional[float] = None
    #: Empty means "caller did not declare one": a complete supplied pair is then
    #: treated as a measurement (back-compat with the pre-provenance API), and
    #: anything less falls back to the analytic model. ``resolve_calibration``
    #: always passes an explicit source read from the config.
    source: str = ""
    sens: float = DEFAULT_SENS
    dpi: float = DEFAULT_DPI
    cm_per_rev: float = DEFAULT_CM_PER_REV
    valorant_deg_per_count: float = DEFAULT_VALORANT_DEG_PER_COUNT
    samples: int = 0
    r2: float = 0.0
    sens_at_measurement: float = 0.0

    def __post_init__(self) -> None:
        supplied_x = _as_positive_float(self.counts_per_deg_x, 0.0)
        supplied_y = _as_positive_float(self.counts_per_deg_y, 0.0)
        self.sens = max(0.01, _as_positive_float(self.sens, DEFAULT_SENS) or DEFAULT_SENS)
        self.dpi = max(1.0, _as_positive_float(self.dpi, DEFAULT_DPI) or DEFAULT_DPI)
        self.cm_per_rev = max(
            0.01, _as_positive_float(self.cm_per_rev, DEFAULT_CM_PER_REV) or DEFAULT_CM_PER_REV
        )
        self.valorant_deg_per_count = max(
            0.001,
            _as_positive_float(self.valorant_deg_per_count, DEFAULT_VALORANT_DEG_PER_COUNT)
            or DEFAULT_VALORANT_DEG_PER_COUNT,
        )
        try:
            self.samples = max(0, int(self.samples or 0))
        except (TypeError, ValueError):
            self.samples = 0
        try:
            self.r2 = max(0.0, min(1.0, float(self.r2 or 0.0)))
        except (TypeError, ValueError):
            self.r2 = 0.0
        self.sens_at_measurement = _as_positive_float(self.sens_at_measurement, 0.0)

        source = str(self.source or "").strip().lower()
        if source not in (SOURCE_VALORANT, SOURCE_MEASURED, SOURCE_ANALYTIC):
            source = ""

        # A complete supplied pair IS a measurement unless the caller named a
        # preset explicitly. An incomplete pair is not usable, so both axes fall
        # back together (a half-measured calibration would skew one axis only).
        has_pair = supplied_x > 0.0 and supplied_y > 0.0
        if source == SOURCE_VALORANT:
            self._apply_valorant()
            return
        if source == SOURCE_MEASURED:
            if has_pair:
                self.counts_per_deg_x = supplied_x
                self.counts_per_deg_y = supplied_y
                self.source = SOURCE_MEASURED
                return
            # Claimed measured but no pair: fall through to analytic rather than
            # pretend the constants are a measurement.
        elif source == "" and has_pair:
            self.counts_per_deg_x = supplied_x
            self.counts_per_deg_y = supplied_y
            self.source = SOURCE_MEASURED
            return

        self.source = SOURCE_ANALYTIC
        analytic = self.analytic_counts_per_deg()
        self.counts_per_deg_x = analytic
        self.counts_per_deg_y = analytic

    def _apply_valorant(self) -> None:
        cpd = self.valorant_counts_per_deg(self.sens)
        self.counts_per_deg_x = cpd
        self.counts_per_deg_y = cpd
        self.source = SOURCE_VALORANT

    # -- source helpers -----------------------------------------------------
    def valorant_counts_per_deg(self, sens: Optional[float] = None) -> float:
        """Valorant scale for ``sens`` (defaults to this calibration's sens)."""
        value = self.sens if sens is None else _as_positive_float(sens, self.sens)
        value = max(0.01, float(value))
        return 1.0 / (self.valorant_deg_per_count * value)

    def rebased(self, sens: Optional[float] = None) -> "Calibration":
        """Return this calibration at a new sensitivity.

        Only ``valorant`` follows sensitivity (that IS its definition). A
        measurement is a physical fact and must not be rescaled.
        """
        if self.source != SOURCE_VALORANT or sens is None:
            return self
        return Calibration(
            source=SOURCE_VALORANT,
            sens=sens,
            dpi=self.dpi,
            cm_per_rev=self.cm_per_rev,
            valorant_deg_per_count=self.valorant_deg_per_count,
        )

    def cm_per_360(self) -> float:
        """Physical mouse travel for one 360 turn at the active scale."""
        cpd = _as_positive_float(self.counts_per_deg_x, 0.0)
        if cpd <= 0.0:
            return 0.0
        counts_360 = cpd * 360.0
        return counts_360 / (self.dpi / 2.54)

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
        return self.source == SOURCE_MEASURED

    @property
    def is_valorant(self) -> bool:
        return self.source == SOURCE_VALORANT

    @property
    def is_analytic(self) -> bool:
        return self.source == SOURCE_ANALYTIC

    @property
    def is_legacy(self) -> bool:
        return self.source == SOURCE_ANALYTIC

    @property
    def divergence_from_analytic(self) -> float:
        """Relative difference between the active scale and the analytic model."""
        analytic = self.analytic_counts_per_deg()
        if analytic <= 0:
            return 0.0
        return (float(self.counts_per_deg_x) - analytic) / analytic

    @property
    def divergence_from_valorant(self) -> float:
        """Relative difference between the active scale and the Valorant preset."""
        valorant = self.valorant_counts_per_deg(self.sens)
        if valorant <= 0:
            return 0.0
        return (float(self.counts_per_deg_x) / valorant) - 1.0

    def sens_drift(self) -> float:
        """Relative change of in-game sensitivity since a measurement was taken."""
        if self.sens_at_measurement <= 0:
            return 0.0
        return (self.sens / self.sens_at_measurement) - 1.0

    def needs_recalibration_warning(self) -> bool:
        """Source-specific "this scale is suspicious" predicate."""
        if self.source == SOURCE_MEASURED:
            # Sensitivity moved since the measurement -> re-measure.
            if abs(self.sens_drift()) > SENS_DRIFT_WARN:
                return True
            # A stored R2 below the acceptance threshold means noisy data.
            if self.r2 > 0.0 and self.r2 < 0.99:
                return True
            # A measurement far from the analytic model is worth a second look.
            return abs(self.divergence_from_analytic) > MEASURED_DIVERGENCE_WARN
        if self.source == SOURCE_VALORANT:
            return not (0.05 <= self.sens <= 5.0)
        # Analytic is legacy by definition: always warn.
        return True

    def describe(self) -> str:
        return (
            f"Calibration(source={self.source}, "
            f"counts/deg=({float(self.counts_per_deg_x):.4f}, "
            f"{float(self.counts_per_deg_y):.4f}), "
            f"sens={self.sens:.4f}, dpi={self.dpi:.1f}, "
            f"samples={self.samples}, r2={self.r2:.3f})"
        )

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
        calibration = resolve_calibration_cached(cfg=cfg, tracker=tracker)
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
    return Calibration(source=SOURCE_ANALYTIC, sens=sens, dpi=dpi).px_to_counts(
        geometry, dx, dy
    )


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
            calibration = Calibration(
                source=SOURCE_ANALYTIC, sens=sens, dpi=dpi, cm_per_rev=cm_per_rev
            )
        if geometry is None:
            geometry = FrameGeometry(
                frame_w=1920,
                frame_h=1080,
                hfov_deg=DEFAULT_HFOV_DEG,
                vfov_deg=vfov_from_hfov(DEFAULT_HFOV_DEG, 1920, 1080),
            )
        return calibration.px_to_counts(geometry, dx, dy)

    # Legacy path: identical arithmetic to the retired calculate_movement().
    deg_per_count = Calibration(
        source=SOURCE_ANALYTIC, sens=sens, dpi=dpi, cm_per_rev=cm_per_rev
    ).deg_per_count
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
