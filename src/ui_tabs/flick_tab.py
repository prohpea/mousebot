"""
Flick V2 tab and the compact Flick card.

One builder, three entry points (plan 3.3 / 4.2):

* :func:`build_flick_panel`   — the compact card used inside Main/Sec Tuning;
* :func:`build_flick_v2_tab`  — the dedicated tab (2 columns + Calibration +
  Diagnostics);
* :func:`build_flick_readouts` — the derived readout row shared by both.

Everything is generated from :data:`src.ui_tabs.common.FLICK_SLIDER_SPECS`, so
Main and Secondary can never drift apart again (the old `ui.py` carried two
hand-maintained copies of the same five sliders).
"""

from __future__ import annotations

import json

import customtkinter as ctk
import tkinter as tk

from src.utils.config import config
from src.utils.i18n import heading, t
from src.version import get_engine_badge
from .common import (
    FLICK_COMPACT_KEYS,
    FLICK_SLIDER_SPECS,
    FLICK_TOOLTIPS,
    SOURCE_LABELS,
    channel_key,
    effective_steps,
    read_value,
    safe_configure,
    safe_text,
    spec_for,
    suggested_budget,
    timing_warning,
)


def _colors(app):
    """Theme colours with a safe fallback (the tab may be built before theming)."""
    import src.ui as ui_module

    return {
        "surface": getattr(ui_module, "COLOR_SURFACE", "#2E3440"),
        "border": getattr(ui_module, "COLOR_BORDER", "#434C5E"),
        "text": getattr(ui_module, "COLOR_TEXT", "#ECEFF4"),
        "dim": getattr(ui_module, "COLOR_TEXT_DIM", "#9CAEC4"),
        "accent": getattr(ui_module, "COLOR_ACCENT", "#88C0D0"),
        "warning": getattr(ui_module, "COLOR_WARNING", "#EBCB8B"),
        "danger": getattr(ui_module, "COLOR_DANGER", "#BF616A"),
        "success": getattr(ui_module, "COLOR_SUCCESS", "#A3BE8C"),
        "font_main": getattr(ui_module, "FONT_MAIN", ("Segoe UI", 11)),
        "font_bold": getattr(ui_module, "FONT_BOLD", ("Segoe UI", 11, "bold")),
    }


# ---------------------------------------------------------------------------
# Slider + readout construction
# ---------------------------------------------------------------------------


def build_channel_sliders(app, parent, is_sec: bool, compact: bool = False):
    """Create the slider rows for one channel and register them on ``app``."""
    keys = FLICK_COMPACT_KEYS if compact else tuple(spec[0] for spec in FLICK_SLIDER_SPECS)
    sliders = {}
    for key in keys:
        spec = spec_for(key)
        if spec is None:
            continue
        _key, label, minimum, maximum, step, _dm, _ds, is_float, advanced = spec
        if compact and advanced:
            continue
        fused = channel_key(key, is_sec)
        # The tab's columns are already labelled MAIN/SECONDARY, so the suffix is
        # only added to the compact card where both channels can be on screen.
        suffix = " (Sec)" if (is_sec and compact) else ""
        slider = app._add_slider_in_frame(
            parent,
            label,
            fused,
            minimum,
            maximum,
            read_value(app, key, is_sec),
            app.flick_handler_for(fused),
            is_float=is_float,
            steps=step,
            suffix=suffix,
            tooltip=FLICK_TOOLTIPS.get(key),
            advanced=advanced,
        )
        sliders[fused] = slider

    store = getattr(app, "flick_sliders_sec" if is_sec else "flick_sliders_main", None)
    if not isinstance(store, dict):
        store = {}
    store.update(sliders)
    if is_sec:
        app.flick_sliders_sec = store
    else:
        app.flick_sliders_main = store
    return sliders


def build_flick_readouts(app, parent, is_sec: bool):
    """Derived readout row: effective steps, travel estimate, warnings."""
    colors = _colors(app)
    container = ctk.CTkFrame(parent, fg_color="transparent")
    container.pack(fill="x", pady=(2, 2))

    steps_lbl = ctk.CTkLabel(
        container, text="Effective steps: --", font=("Consolas", 10), text_color=colors["dim"]
    )
    steps_lbl.pack(anchor="w")

    warn_row = ctk.CTkFrame(container, fg_color="transparent")
    warn_row.pack(fill="x", pady=(2, 0))
    warn_lbl = ctk.CTkLabel(
        warn_row, text="", font=("Consolas", 10, "bold"), text_color=colors["warning"]
    )
    warn_lbl.pack(side="left")

    fix_btn = ctk.CTkButton(
        warn_row,
        text="Auto-fix",
        width=70,
        height=22,
        corner_radius=6,
        font=("Segoe UI", 9, "bold"),
        fg_color=colors["warning"],
        hover_color="#D9A441",
        text_color="#231A00",
        command=lambda: app.auto_fix_flick_timing(is_sec),
    )
    # Packed only when the warning is visible.
    fix_btn.pack_forget()

    store = {
        "container": container,
        "steps": steps_lbl,
        "warning": warn_lbl,
        "fix": fix_btn,
    }
    if is_sec:
        app.flick_readouts_sec = store
    else:
        app.flick_readouts_main = store
    refresh_flick_readouts(app, is_sec)
    return container


def refresh_flick_readouts(app, is_sec: Optional[bool] = None):
    """Update the derived rows for one channel (or both when ``None``)."""
    channels = (False, True) if is_sec is None else (bool(is_sec),)
    colors = _colors(app)
    for channel in channels:
        store = getattr(app, "flick_readouts_sec" if channel else "flick_readouts_main", None)
        if not isinstance(store, dict):
            continue
        iterations = read_value(app, "flick_max_iterations", channel)
        budget = read_value(app, "flick_budget_ms", channel)
        settle = read_value(app, "flick_settle_ms", channel)
        max_counts = read_value(app, "flick_max_counts", channel)
        steps = effective_steps(iterations, budget, settle)
        travel = int(max_counts) * int(steps)
        safe_text(
            store.get("steps"),
            f"Effective steps: {steps} / {int(iterations)}   "
            f"Est. max travel: {travel:,} counts",
        )
        warning = timing_warning(iterations, budget, settle)
        if settle <= 0.0:
            warning = "No pipeline wait; a stale frame may be measured"
        safe_text(store.get("warning"), warning)
        safe_configure(
            store.get("warning"),
            text_color=colors["warning"] if (steps < int(iterations) or settle <= 0) else colors["dim"],
        )
        fix = store.get("fix")
        if fix is not None:
            try:
                if warning and steps < int(iterations):
                    fix.pack(side="left", padx=(8, 0))
                else:
                    fix.pack_forget()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------


def build_diagnostics(app, parent):
    """Collapsible diagnostics block reading ``tracker.flick_status``."""
    colors = _colors(app)
    section = app._create_collapsible_section(
        parent, "Diagnostics", initially_open=False, state_key="flick_diagnostics"
    )

    body = ctk.CTkLabel(
        section,
        text="--",
        font=("Consolas", 10),
        text_color=colors["dim"],
        justify="left",
        anchor="w",
    )
    body.pack(fill="x", pady=(2, 4))

    app.flick_diagnostics_label = body

    row = ctk.CTkFrame(section, fg_color="transparent")
    row.pack(fill="x")
    ctk.CTkButton(
        row,
        text="Copy diagnostics",
        command=app.copy_flick_diagnostics,
        height=24,
        width=130,
        corner_radius=6,
        font=("Segoe UI", 9, "bold"),
        fg_color=colors["surface"],
        hover_color=colors["border"],
        border_width=1,
        border_color=colors["border"],
        text_color=colors["text"],
    ).pack(side="left", padx=(0, 6))
    ctk.CTkButton(
        row,
        text="Reset state",
        command=lambda: app.reset_flick_state(None),
        height=24,
        width=100,
        corner_radius=6,
        font=("Segoe UI", 9, "bold"),
        fg_color=colors["surface"],
        hover_color=colors["border"],
        border_width=1,
        border_color=colors["border"],
        text_color=colors["text"],
    ).pack(side="left")
    return section


def refresh_diagnostics(app):
    """Render the published Flick status (250 ms cadence, tab-gated)."""
    label = getattr(app, "flick_diagnostics_label", None)
    if label is None:
        return
    lines = []
    for channel in ("main", "sec"):
        payload = app.flick_status_for(channel)
        if not payload:
            lines.append(f"{channel:>4}: --")
            continue
        counts = payload.get("counts", (0.0, 0.0))
        residual = payload.get("residual", (0.0, 0.0))
        error = payload.get("error_px", (0.0, 0.0))
        lines.append(
            f"{channel:>4}: reason={payload.get('reason') or '-':<14s} "
            f"iter={payload.get('iterations', 0)}/{payload.get('max_iterations', 0)} "
            f"eff={payload.get('effective_steps', 0)}"
        )
        lines.append(
            f"      counts=({counts[0]:.1f}, {counts[1]:.1f}) "
            f"residual=({residual[0]:.2f}, {residual[1]:.2f}) "
            f"err=({error[0]:.1f}, {error[1]:.1f})"
        )
        lines.append(
            f"      calib={payload.get('calibration', 'none')} "
            f"geom={payload.get('geometry', 'none')} "
            f"gain={payload.get('gain', 1.0):.2f} "
            f"clamped={payload.get('clamped', 0)} "
            f"armed={payload.get('armed')}"
        )
    safe_text(label, "\n".join(lines))


# ---------------------------------------------------------------------------
# Compact panel (inside Main / Sec "Algorithm Tuning")
# ---------------------------------------------------------------------------


def build_flick_panel(app, parent, is_sec: bool = False):
    """Compact Flick card body: 6 sliders + readouts + Calibrate/Open buttons."""
    colors = _colors(app)
    ctk.CTkLabel(
        parent,
        text=heading("Flick V2 (closed loop)"),
        font=("Roboto", 10, "bold"),
        text_color=colors["dim"],
    ).pack(anchor="w", pady=(4, 2))

    build_channel_sliders(app, parent, is_sec, compact=True)
    build_flick_readouts(app, parent, is_sec)

    row = ctk.CTkFrame(parent, fg_color="transparent")
    row.pack(fill="x", pady=(4, 0))
    ctk.CTkButton(
        row,
        text=t("Open Flick V2"),
        command=app.show_flick_v2_tab,
        height=26,
        width=120,
        corner_radius=6,
        font=("Segoe UI", 10, "bold"),
        fg_color=colors["accent"],
        hover_color=colors["border"],
        text_color="#0B1218",
    ).pack(side="left", padx=(0, 6))
    ctk.CTkButton(
        row,
        text=t("Calibrate"),
        command=app.show_flick_v2_calibration,
        height=26,
        width=100,
        corner_radius=6,
        font=("Segoe UI", 10, "bold"),
        fg_color=colors["surface"],
        hover_color=colors["border"],
        border_width=1,
        border_color=colors["border"],
        text_color=colors["text"],
    ).pack(side="left")
    return row


# ---------------------------------------------------------------------------
# Dedicated tab
# ---------------------------------------------------------------------------


def build_flick_v2_tab(app):
    """Build the whole Flick V2 tab inside ``app.content_frame``."""
    colors = _colors(app)
    from src.ui_components import ModernCard

    app._add_sub_nav_bar(
        ["Main Aimbot", "Sec Aimbot", "Flick V2", "Recoil & RCS"],
        "Flick V2",
        {
            "Main Aimbot": app._show_aimbot_tab,
            "Sec Aimbot": app._show_sec_aimbot_tab,
            "Flick V2": app._show_flick_v2_tab,
            "Recoil & RCS": app._show_rcs_tab,
        },
    )
    app._add_title("Flick V2")

    # ── Status strip ────────────────────────────────────────────────────
    strip = ctk.CTkFrame(
        app.content_frame, fg_color="#141822", corner_radius=8,
        border_width=1, border_color="#232B3B",
    )
    strip.pack(fill="x", pady=(0, 8))
    strip_inner = ctk.CTkFrame(strip, fg_color="transparent")
    strip_inner.pack(fill="x", padx=12, pady=6)

    app.flick_engine_pill = ctk.CTkLabel(
        strip_inner, text=get_engine_badge(), font=("Consolas", 10, "bold"),
        text_color=colors["accent"],
    )
    app.flick_engine_pill.pack(side="left", padx=(0, 14))

    app.flick_calibration_pill = ctk.CTkLabel(
        strip_inner, text="Calibration: --", font=("Consolas", 10),
        text_color=colors["dim"],
    )
    app.flick_calibration_pill.pack(side="left", padx=(0, 14))

    app.flick_geometry_pill = ctk.CTkLabel(
        strip_inner, text="Frame: --", font=("Consolas", 10), text_color=colors["dim"]
    )
    app.flick_geometry_pill.pack(side="left", padx=(0, 14))

    app.flick_last_pill = ctk.CTkLabel(
        strip_inner, text="Last: --", font=("Consolas", 10), text_color=colors["dim"]
    )
    app.flick_last_pill.pack(side="left")

    # ── Two channels ────────────────────────────────────────────────────
    grid = ctk.CTkFrame(app.content_frame, fg_color="transparent")
    grid.pack(fill="both", expand=True)
    grid.grid_columnconfigure(0, weight=1)
    grid.grid_columnconfigure(1, weight=1)

    for column, is_sec in ((0, False), (1, True)):
        card = ModernCard(
            grid,
            "SECONDARY CHANNEL" if is_sec else "MAIN CHANNEL",
            icon="🎯",
            badge_text="Sec" if is_sec else "Main",
            accent_color="#06B6D4" if not is_sec else "#BD93F9",
        )
        card.grid(
            row=0,
            column=column,
            sticky="nsew",
            padx=(0, 6) if column == 0 else (6, 0),
            pady=(0, 10),
        )
        if is_sec:
            app.card_flick_sec = card
        else:
            app.card_flick_main = card

        build_channel_sliders(app, card.content, is_sec, compact=False)
        build_flick_readouts(app, card.content, is_sec)

        actions = ctk.CTkFrame(card.content, fg_color="transparent")
        actions.pack(fill="x", pady=(4, 0))
        channel = "sec" if is_sec else "main"
        ctk.CTkButton(
            actions,
            text=t("Calibrate"),
            command=app.show_flick_v2_calibration,
            height=26,
            width=100,
            corner_radius=6,
            font=("Segoe UI", 10, "bold"),
            fg_color=colors["surface"],
            hover_color=colors["border"],
            border_width=1,
            border_color=colors["border"],
            text_color=colors["text"],
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            actions,
            text=t("Reset state"),
            command=lambda ch=channel: app.reset_flick_state(ch),
            height=26,
            width=100,
            corner_radius=6,
            font=("Segoe UI", 10, "bold"),
            fg_color=colors["surface"],
            hover_color=colors["border"],
            border_width=1,
            border_color=colors["border"],
            text_color=colors["text"],
        ).pack(side="left")

    # ── Engine + telemetry row ──────────────────────────────────────────
    engine_row = ctk.CTkFrame(app.content_frame, fg_color="transparent")
    engine_row.pack(fill="x", pady=(2, 6))

    ctk.CTkLabel(
        engine_row, text=t("Engine"), font=colors["font_main"], text_color=colors["text"]
    ).pack(side="left", padx=(0, 8))
    engine_values = ["v2", "legacy"]
    app.flick_engine_option = ctk.CTkOptionMenu(
        engine_row,
        values=engine_values,
        command=app.on_flick_engine_selected,
        width=110,
        height=26,
        fg_color=colors["surface"],
        button_color=colors["border"],
        button_hover_color=colors["accent"],
        text_color=colors["text"],
        font=colors["font_main"],
        dropdown_fg_color=colors["surface"],
        dropdown_hover_color=colors["border"],
        dropdown_text_color=colors["text"],
    )
    current_engine = str(getattr(config, "flick_engine", "v2") or "v2").lower()
    app.flick_engine_option.set("legacy" if current_engine == "legacy" else "v2")
    app.flick_engine_option.pack(side="left", padx=(0, 16))

    app.var_flick_telemetry = tk.BooleanVar(
        value=bool(getattr(config, "flick_telemetry_enabled", False))
    )
    ctk.CTkSwitch(
        engine_row,
        text=t("Publish diagnostics"),
        variable=app.var_flick_telemetry,
        command=app.on_flick_telemetry_changed,
        font=colors["font_main"],
        progress_color=colors["accent"],
    ).pack(side="left")

    # ── Calibration card ────────────────────────────────────────────────
    from .calibration_tab import build_flick_calibration_card

    build_flick_calibration_card(app, app.content_frame)

    # ── Diagnostics ─────────────────────────────────────────────────────
    build_diagnostics(app, app.content_frame)

    refresh_flick_summary(app)
    return app.content_frame


# ---------------------------------------------------------------------------
# Status strip
# ---------------------------------------------------------------------------


def refresh_flick_summary(app):
    """Update the engine/calibration/geometry/last-step strip (250 ms)."""
    try:
        from src.aim_system.aim_math import resolve_calibration, resolve_geometry

        calibration = resolve_calibration()
        geometry = resolve_geometry(frame=getattr(app.tracker, "_aim_frame", None))

        source = SOURCE_LABELS.get(calibration.source, calibration.source.upper())
        safe_text(
            getattr(app, "flick_calibration_pill", None),
            f"Calibration: {source} · {calibration.counts_per_deg_x:.2f} c/deg",
        )
        deg_per_px = geometry.deg_per_px_at_center()[0]
        safe_text(
            getattr(app, "flick_geometry_pill", None),
            f"Frame {geometry.frame_w}x{geometry.frame_h} · "
            f"hFOV {geometry.hfov_deg:.1f}° · {deg_per_px:.4f}°/px · {geometry.source}",
        )

        status = app.flick_status_for("main") or app.flick_status_for("sec") or {}
        if status:
            counts = status.get("counts", (0.0, 0.0))
            error = status.get("error_px", (0.0, 0.0))
            safe_text(
                getattr(app, "flick_last_pill", None),
                f"Last: {status.get('reason') or '-'} · "
                f"{abs(counts[0]):.1f} counts · "
                f"{abs(error[0]):.1f} px",
            )
        else:
            safe_text(getattr(app, "flick_last_pill", None), "Last: --")
    except Exception:
        safe_text(getattr(app, "flick_calibration_pill", None), "Calibration: --")


def copy_diagnostics_payload(app) -> str:
    """JSON payload for the Copy diagnostics button (and tests)."""
    payload = {
        "engine": str(getattr(config, "flick_engine", "v2")),
        "main": app.flick_status_for("main"),
        "sec": app.flick_status_for("sec"),
        "config": {
            key: getattr(config, key, None)
            for key in (
                "flick_gain",
                "flick_settle_ms",
                "flick_budget_ms",
                "flick_max_iterations",
                "flick_max_counts",
                "flick_deadzone_px",
                "flick_switch_radius_px",
                "flick_gain_sec",
                "flick_settle_ms_sec",
                "flick_budget_ms_sec",
                "flick_max_iterations_sec",
                "calibration_source",
                "counts_per_deg_x",
                "counts_per_deg_y",
                "calibration_r2",
                "calibration_samples",
            )
        },
    }
    return json.dumps(payload, indent=2, default=str)
