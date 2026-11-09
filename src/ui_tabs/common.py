"""
Shared builders and the single Flick parameter spec.

Main and Secondary used to carry two near-identical copies of the Flick slider
block (5 sliders + 5 callbacks each), which is how they drifted apart. Both
channels are now generated from :data:`FLICK_SLIDER_SPECS`, and the derived
readouts (effective steps, estimated travel) come from one helper so the compact
card and the Flick V2 tab can never disagree.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

#: Flick parameter spec shared by Main, Secondary and the Flick V2 tab.
#: ``(key, label, min, max, step, default_main, default_sec, is_float, advanced)``
FLICK_SLIDER_SPECS = (
    ("flick_gain", "Gain (1.0 = physical)", 0.1, 3.0, 0.01, 1.0, 1.0, True, False),
    ("flick_settle_ms", "Settle Delay (ms)", 0.0, 300.0, 5.0, 70.0, 70.0, True, False),
    ("flick_max_counts", "Max Counts / Step", 100, 20000, 50, 6000, 6000, False, False),
    ("flick_budget_ms", "Convergence Budget (ms)", 40, 1000, 10, 240, 240, True, False),
    ("flick_max_iterations", "Max Iterations", 1, 10, 1, 4, 4, False, False),
    ("flick_deadzone_px", "Deadzone (px)", 0.0, 20.0, 0.1, 1.5, 2.0, True, False),
    ("flick_switch_radius_px", "Target Switch Radius (px)", 16, 256, 4, 64, 64, False, True),
)

#: Sliders shown in the compact "Algorithm Tuning" card inside Main / Sec.
FLICK_COMPACT_KEYS = (
    "flick_gain",
    "flick_settle_ms",
    "flick_max_counts",
    "flick_budget_ms",
    "flick_max_iterations",
    "flick_deadzone_px",
)

#: Tooltips, keyed by config key.
FLICK_TOOLTIPS = {
    "flick_gain": (
        "Physical gain: 1.00 sends exactly the counts the geometry and the "
        "calibration ask for. It is not a 'feel' multiplier."
    ),
    "flick_settle_ms": (
        "How long to wait for a fresh frame after each impulse. Should be at "
        "least the capture pipeline latency (~70 ms) plus one frame."
    ),
    "flick_max_counts": (
        "Budget for one step, applied to the whole vector so the aim line keeps "
        "its direction. Direction is preserved; per-axis truncation is not used."
    ),
    "flick_budget_ms": (
        "Total convergence budget for one engagement. Combined with Settle Delay "
        "it decides how many steps can actually be sent."
    ),
    "flick_max_iterations": (
        "Upper bound on correction steps. The budget may fund fewer: see the "
        "effective steps readout."
    ),
    "flick_deadzone_px": "Stop correcting once the error is inside this radius.",
    "flick_switch_radius_px": (
        "A target moving further than this is treated as a different target and "
        "gets a fresh budget. Small drift while converging is ignored."
    ),
}

#: Geometry/calibration sources as displayed.
SOURCE_LABELS = {
    "valorant": "VALORANT",
    "measured": "MEASURED",
    "analytic": "ANALYTIC",
}


def spec_for(key: str) -> Optional[tuple]:
    for spec in FLICK_SLIDER_SPECS:
        if spec[0] == key:
            return spec
    return None


def channel_key(key: str, is_sec: bool) -> str:
    """``flick_gain`` -> ``flick_gain_sec`` for the secondary channel."""
    return f"{key}_sec" if is_sec else key


def default_for(key: str, is_sec: bool) -> float:
    spec = spec_for(key)
    if spec is None:
        return 0.0
    return float(spec[6] if is_sec else spec[5])


def read_value(app, key: str, is_sec: bool) -> float:
    """Current value for a spec key, falling back to the spec default."""
    from src.utils.config import config

    fused = channel_key(key, is_sec)
    value = getattr(config, fused, None)
    if value is None:
        value = getattr(config, key, None)
    if value is None:
        return default_for(key, is_sec)
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default_for(key, is_sec)
    if parsed != parsed or parsed in (float("inf"), float("-inf")):
        return default_for(key, is_sec)
    return parsed


def clamp_to_spec(key: str, value: Any) -> float:
    spec = spec_for(key)
    if spec is None:
        return float(value or 0.0)
    _key, _label, minimum, maximum, _step, _dm, _ds, is_float, _adv = spec
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return float(minimum)
    parsed = max(float(minimum), min(float(maximum), parsed))
    return parsed if is_float else float(int(round(parsed)))


def format_value(value: Any, is_float: bool) -> str:
    """Human-readable value: integers stay integers, floats keep 2 decimals."""
    if is_float:
        return f"{float(value):.2f}"
    return f"{int(round(float(value)))}"


def effective_steps(max_iterations: Any, budget_ms: Any, settle_ms: Any) -> int:
    """``min(max_iterations, floor(budget / max(settle,1)) + 1)``.

    With the historical ``settle=70, budget=120`` this is 2, not 4 — the number
    the UI used to promise without ever saying so.
    """
    try:
        iterations = max(1, int(max_iterations))
        budget = max(0.0, float(budget_ms))
        settle = max(1.0, float(settle_ms))
    except (TypeError, ValueError):
        return 1
    return max(1, min(iterations, int(budget // settle) + 1))


def timing_warning(max_iterations: Any, budget_ms: Any, settle_ms: Any) -> str:
    """Empty string when Settle/Budget agree, otherwise the warning to show."""
    if float(settle_ms or 0.0) <= 0.0:
        return ""
    steps = effective_steps(max_iterations, budget_ms, settle_ms)
    try:
        iterations = int(max_iterations)
    except (TypeError, ValueError):
        iterations = 1
    if steps >= iterations:
        return ""
    return f"Settle ≥ Budget: only {steps} of {iterations} steps"


def suggested_budget(settle_ms: Any, max_iterations: Any = None) -> float:
    """Budget that funds ``max_iterations`` at ``settle_ms`` (Auto-fix button)."""
    try:
        settle = max(0.0, float(settle_ms))
    except (TypeError, ValueError):
        settle = 0.0
    base = settle + 50.0
    if max_iterations is None:
        return base
    try:
        iterations = max(1, int(max_iterations))
    except (TypeError, ValueError):
        return base
    return max(base, settle * iterations)


def format_counts_for_px(px: float, counts_per_deg: float, deg_per_px: float) -> str:
    """``"30 px ≈ 139.8 counts"`` for the geometry/calibration readout."""
    try:
        counts = float(px) * float(deg_per_px) * float(counts_per_deg)
    except (TypeError, ValueError):
        return f"{px:g} px ≈ -- counts"
    return f"{px:g} px ≈ {counts:.1f} counts"


def build_button_row(parent, buttons: Iterable[tuple], fg_color: str, hover_color: str):
    """Pack a row of ``(label, command, style)`` buttons; returns the widgets."""
    import customtkinter as ctk

    row = ctk.CTkFrame(parent, fg_color="transparent")
    row.pack(fill="x", pady=(4, 2))
    widgets = []
    for entry in buttons:
        label, command = entry[0], entry[1]
        accent = entry[2] if len(entry) > 2 else False
        button = ctk.CTkButton(
            row,
            text=label,
            command=command,
            height=26,
            corner_radius=6,
            font=("Segoe UI", 10, "bold"),
            fg_color=fg_color if not accent else "#10B981",
            hover_color=hover_color if not accent else "#059669",
            text_color="#04120C" if accent else "#ECEFF4",
            border_width=0 if accent else 1,
        )
        button.pack(side="left", padx=(0, 6))
        widgets.append(button)
    return row, widgets


def safe_configure(widget, **kwargs) -> bool:
    """``widget.configure`` that tolerates a destroyed Tk widget."""
    if widget is None:
        return False
    try:
        if hasattr(widget, "winfo_exists") and not widget.winfo_exists():
            return False
    except Exception:
        return False
    try:
        widget.configure(**kwargs)
        return True
    except Exception:
        return False


def safe_text(widget, text: str) -> bool:
    return safe_configure(widget, text=text)
