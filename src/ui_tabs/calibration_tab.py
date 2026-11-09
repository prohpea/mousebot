"""
Calibration — Valorant card.

Three explicit sources, one card (plan 5):

* **Valorant** — ``counts_per_deg = 1 / (0.07 * sens)``. Recomputed from the
  current sensitivity, so changing sens from 0.23 to 0.40 moves the scale from
  62.112 to 35.714 without a restart. At 0.23 that is 51.63 cm/360 and
  30 px ≈ 139.8 counts, which the card shows so the user can verify it.
* **Measured** — impulse + *signed* pixel shift, minimum 5 samples per axis,
  R² ≥ 0.99, **both axes required** (no extrapolation), provenance stored.
* **Analytic** — the legacy 54.54 cm/rev model, explicitly labelled LEGACY.

The old panel hard-coded ``abs()`` on the measured shift (destroying the sign),
extrapolated the missing axis from the focal ratio, and displayed a preset as
"MEASURED". All three are fixed here.
"""

from __future__ import annotations

import datetime

import customtkinter as ctk
import tkinter as tk

from src.utils.config import config
from src.utils.debug_logger import log_print
from src.utils.i18n import t
from .common import SOURCE_LABELS, safe_configure, safe_text

#: Minimum samples per axis before a fit is accepted.
MIN_SAMPLES_PER_AXIS = 5
#: Minimum coefficient of determination for a stored measurement.
MIN_R2 = 0.99


def _colors(app):
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
    }


SOURCE_DESCRIPTIONS = {
    "valorant": "0.07 °/count at sens 1.00 — recomputed from in-game sens",
    "measured": "Impulse-measured scale; invariant under sensitivity",
    "analytic": "Legacy 54.54 cm/rev model (unverified)",
}


def build_flick_calibration_card(app, parent, layout="pack", grid_options=None):
    """Build the Calibration card and register its widgets on ``app``.

    ``layout`` is ``"pack"`` for the Flick V2 tab (vertical stack) or ``"grid"``
    when the Main Aimbot tab embeds the card in its two-column grid.
    """
    colors = _colors(app)
    from src.ui_components import ModernCard

    card = ModernCard(
        parent,
        "Calibration — Valorant",
        icon="📐",
        badge_text="Accuracy",
        accent_color="#22D3EE",
    )
    if layout == "grid":
        options = dict(row=2, column=0, columnspan=2, sticky="nsew", padx=0, pady=(0, 10))
        options.update(grid_options or {})
        card.grid(**options)
    else:
        card.pack(fill="x", pady=(0, 10))
    app.card_calibration = card
    content = card.content

    # ── Source selector ─────────────────────────────────────────────────
    source_row = ctk.CTkFrame(content, fg_color="transparent")
    source_row.pack(fill="x", pady=(2, 6))
    ctk.CTkLabel(
        source_row, text=t("Source:"), font=colors["font_main"], text_color=colors["text"]
    ).pack(side="left", padx=(0, 8))

    app.calibration_source_var = tk.StringVar(
        value=str(getattr(config, "calibration_source", "valorant") or "valorant")
    )
    for value, label in (
        ("valorant", "Valorant preset"),
        ("measured", "Measured"),
        ("analytic", "Analytic (legacy)"),
    ):
        ctk.CTkRadioButton(
            source_row,
            text=t(label),
            variable=app.calibration_source_var,
            value=value,
            command=lambda v=value: app.on_calibration_source_changed(v),
            font=colors["font_main"],
            text_color=colors["text"],
            fg_color=colors["accent"],
            hover_color=colors["accent"],
            radiobutton_width=14,
            radiobutton_height=14,
        ).pack(side="left", padx=(0, 12))

    ctk.CTkLabel(
        source_row,
        text=SOURCE_DESCRIPTIONS.get(
            app.calibration_source_var.get(), ""
        ),
        font=("Consolas", 9),
        text_color=colors["dim"],
    ).pack(side="left", padx=(8, 0))

    # ── Sens / DPI row ──────────────────────────────────────────────────
    inputs = ctk.CTkFrame(content, fg_color="transparent")
    inputs.pack(fill="x", pady=(0, 4))

    def _entry(parent_frame, label_text, key, default, width=70):
        ctk.CTkLabel(
            parent_frame,
            text=t(label_text),
            font=colors["font_main"],
            text_color=colors["dim"],
        ).pack(side="left", padx=(0, 4))
        entry = ctk.CTkEntry(
            parent_frame, width=width, height=24, justify="center", font=("Consolas", 10)
        )
        entry.insert(0, str(getattr(config, key, default)))
        entry.pack(side="left", padx=(0, 12))

        def _commit(event=None, entry=entry, key=key, default=default):
            app.commit_calibration_inputs()

        entry.bind("<FocusOut>", _commit)
        entry.bind("<Return>", _commit)
        return entry

    app.calibration_sens_entry = _entry(inputs, "In-game Sens", "in_game_sens", 0.23)
    app.calibration_dpi_entry = _entry(inputs, "DPI", "mouse_dpi", 1100)
    app.calibration_yaw_entry = _entry(
        inputs, "Yaw (°/count @ 1.0)", "valorant_deg_per_count", 0.07, width=60
    )

    # ── Valorant readout ────────────────────────────────────────────────
    app.calibration_valorant_label = ctk.CTkLabel(
        content,
        text="→ --",
        font=("Consolas", 10),
        text_color=colors["text"],
        justify="left",
        anchor="w",
    )
    app.calibration_valorant_label.pack(fill="x", pady=(2, 2))

    val_row = ctk.CTkFrame(content, fg_color="transparent")
    val_row.pack(fill="x", pady=(0, 6))
    ctk.CTkButton(
        val_row,
        text=t("Apply Valorant scale"),
        command=app.on_apply_valorant_scale,
        height=26,
        width=150,
        corner_radius=6,
        font=("Segoe UI", 10, "bold"),
        fg_color=colors["accent"],
        hover_color=colors["border"],
        text_color="#0B1218",
    ).pack(side="left")

    # ── Measured workflow ───────────────────────────────────────────────
    app.calibration_measured_frame = ctk.CTkFrame(content, fg_color="transparent")
    app.calibration_measured_frame.pack(fill="x", pady=(4, 2))

    imp = ctk.CTkFrame(app.calibration_measured_frame, fg_color="transparent")
    imp.pack(fill="x", pady=(0, 4))
    ctk.CTkLabel(
        imp, text=t("Impulse counts"), font=colors["font_main"], text_color=colors["dim"]
    ).pack(side="left", padx=(0, 4))
    app.calibration_counts_entry = ctk.CTkEntry(imp, width=70, height=24, justify="center")
    app.calibration_counts_entry.insert(0, "100")
    app.calibration_counts_entry.pack(side="left", padx=(0, 10))

    ctk.CTkLabel(imp, text=t("Axis"), font=colors["font_main"], text_color=colors["dim"]).pack(
        side="left", padx=(0, 4)
    )
    app.calibration_axis_var = tk.StringVar(value="x")
    ctk.CTkOptionMenu(
        imp,
        values=["x", "y"],
        variable=app.calibration_axis_var,
        width=60,
        height=24,
    ).pack(side="left", padx=(0, 10))

    ctk.CTkButton(
        imp,
        text=t("Send test impulse"),
        command=app.on_calibration_send_impulse,
        height=26,
        width=130,
        corner_radius=6,
        font=("Segoe UI", 10, "bold"),
        fg_color=colors["surface"],
        hover_color=colors["border"],
        border_width=1,
        border_color=colors["border"],
        text_color=colors["text"],
    ).pack(side="left")

    shift = ctk.CTkFrame(app.calibration_measured_frame, fg_color="transparent")
    shift.pack(fill="x", pady=(0, 4))
    ctk.CTkLabel(
        shift,
        text=t("Measured shift (px, signed)"),
        font=colors["font_main"],
        text_color=colors["dim"],
    ).pack(side="left", padx=(0, 4))
    app.calibration_px_entry = ctk.CTkEntry(shift, width=80, height=24, justify="center")
    app.calibration_px_entry.insert(0, "0")
    app.calibration_px_entry.pack(side="left", padx=(0, 10))
    ctk.CTkButton(
        shift,
        text=t("Record sample"),
        command=app.on_calibration_record_sample,
        height=26,
        width=120,
        corner_radius=6,
        font=("Segoe UI", 10, "bold"),
        fg_color=colors["surface"],
        hover_color=colors["border"],
        border_width=1,
        border_color=colors["border"],
        text_color=colors["text"],
    ).pack(side="left")

    app.calibration_samples_label = ctk.CTkLabel(
        app.calibration_measured_frame,
        text=f"Samples: x=0/{MIN_SAMPLES_PER_AXIS}  y=0/{MIN_SAMPLES_PER_AXIS}  R²: --",
        font=("Consolas", 10),
        text_color=colors["dim"],
    )
    app.calibration_samples_label.pack(anchor="w", pady=(2, 2))

    fit_row = ctk.CTkFrame(app.calibration_measured_frame, fg_color="transparent")
    fit_row.pack(fill="x")
    ctk.CTkButton(
        fit_row,
        text=t("Fit & save"),
        command=app.on_calibration_fit,
        height=26,
        width=110,
        corner_radius=6,
        font=("Segoe UI", 10, "bold"),
        fg_color="#10B981",
        hover_color="#059669",
        text_color="#04120C",
    ).pack(side="left", padx=(0, 6))
    ctk.CTkButton(
        fit_row,
        text=t("Clear"),
        command=app.on_calibration_clear,
        height=26,
        width=80,
        corner_radius=6,
        font=("Segoe UI", 10, "bold"),
        fg_color=colors["surface"],
        hover_color=colors["border"],
        border_width=1,
        border_color=colors["border"],
        text_color=colors["text"],
    ).pack(side="left", padx=(0, 6))

    # ── Analytic (legacy) row ───────────────────────────────────────────
    app.calibration_analytic_label = ctk.CTkLabel(
        content,
        text="",
        font=("Consolas", 10),
        text_color=colors["dim"],
        justify="left",
        anchor="w",
    )
    app.calibration_analytic_label.pack(fill="x", pady=(4, 2))

    # ── Provenance / geometry footer ────────────────────────────────────
    app.calibration_state_label = ctk.CTkLabel(
        content,
        text="--",
        font=("Consolas", 10),
        text_color=colors["dim"],
        justify="left",
        anchor="w",
    )
    app.calibration_state_label.pack(fill="x", pady=(4, 0))

    if not hasattr(app, "_calibration_samples") or not isinstance(
        getattr(app, "_calibration_samples", None), dict
    ):
        app._calibration_samples = {"x": [], "y": []}

    refresh_calibration_card(app)
    return card


# ---------------------------------------------------------------------------
# Refresh / readouts
# ---------------------------------------------------------------------------


def _geometry_text(geometry) -> str:
    deg_x, deg_y = geometry.deg_per_px_at_center()
    return (
        f"Geometry: {geometry.frame_w}×{geometry.frame_h} · "
        f"hFOV {geometry.hfov_deg:.2f}° · vFOV {geometry.vfov_deg:.2f}° · "
        f"focal {geometry.focal_x:.2f}/{geometry.focal_y:.2f} px · "
        f"{deg_x:.4f}°/px · {geometry.source}"
    )


def refresh_calibration_card(app):
    """Update every readout in the Calibration card from the live config."""
    try:
        from src.aim_system.aim_math import resolve_calibration, resolve_geometry

        calibration = resolve_calibration()
        geometry = resolve_geometry(frame=getattr(app.tracker, "_aim_frame", None))
    except Exception as exc:  # pragma: no cover - defensive
        safe_text(getattr(app, "calibration_state_label", None), f"calibration unavailable: {exc}")
        return

    colors = _colors(app)
    cpd = float(calibration.counts_per_deg_x)
    cm360 = calibration.cm_per_360()
    deg_per_px = geometry.deg_per_px_at_center()[0]
    counts_30 = 30.0 * deg_per_px * cpd

    safe_text(
        getattr(app, "calibration_valorant_label", None),
        f"→ {cpd:.3f} counts/deg · {cm360:.2f} cm/360 · "
        f"30 px ≈ {counts_30:.1f} counts",
    )

    legacy_cpd = calibration.analytic_counts_per_deg()
    safe_text(
        getattr(app, "calibration_analytic_label", None),
        f"Legacy analytic: {legacy_cpd:.2f} counts/deg "
        f"(54.54 cm/rev) — {legacy_cpd / cpd:.3f}× the active scale. "
        "Unverified; use only when neither a preset nor a measurement exists.",
    )
    safe_configure(
        getattr(app, "calibration_analytic_label", None),
        text_color=colors["warning"] if calibration.is_analytic else colors["dim"],
    )

    source_label = SOURCE_LABELS.get(calibration.source, calibration.source.upper())
    updated = str(getattr(config, "calibration_updated_at", "") or "--")
    samples = int(getattr(config, "calibration_samples", 0) or 0)
    r2 = float(getattr(config, "calibration_r2", 0.0) or 0.0)
    r2_text = f"{r2:.4f}" if samples else "--"
    warning = ""
    if calibration.needs_recalibration_warning():
        if calibration.is_measured:
            drift = calibration.sens_drift()
            if abs(drift) > 0.02:
                warning = (
                    f"\nWARN sens changed {drift * 100:+.1f}% since the measurement; "
                    "re-measure or switch to the Valorant preset."
                )
            elif r2 and r2 < MIN_R2:
                warning = f"\nWARN R²={r2:.4f} < {MIN_R2}; the measurement is noisy."
        elif calibration.is_valorant:
            warning = "\nWARN in-game sens is outside the Valorant preset range (0.05–5.0)."
        else:
            warning = "\nWARN analytic model is legacy and unverified."
    if calibration.is_measured and abs(calibration.divergence_from_valorant) > 0.20:
        warning += (
            f"\nWARN measured scale differs from the Valorant preset by "
            f"{calibration.divergence_from_valorant * 100:+.1f}% (>20%); check the samples."
        )

    safe_text(
        getattr(app, "calibration_state_label", None),
        f"Source={source_label} · Updated={updated} · Samples={samples} · R²={r2_text}\n"
        f"{_geometry_text(geometry)}{warning}",
    )

    samples_map = getattr(app, "_calibration_samples", {"x": [], "y": []})
    safe_text(
        getattr(app, "calibration_samples_label", None),
        f"Samples: x={len(samples_map.get('x', []))}/{MIN_SAMPLES_PER_AXIS}  "
        f"y={len(samples_map.get('y', []))}/{MIN_SAMPLES_PER_AXIS}  R²: {r2_text}",
    )


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------


def apply_valorant_scale(app) -> bool:
    """Compute and store the Valorant preset for the current sensitivity."""
    try:
        sens = float(app.calibration_sens_entry.get().strip())
    except Exception:
        log_print("[Calibration] invalid sensitivity")
        return False
    sens = max(0.05, min(5.0, sens))
    try:
        yaw = float(app.calibration_yaw_entry.get().strip())
    except Exception:
        yaw = 0.07
    yaw = max(0.01, min(0.2, yaw))

    cpd = 1.0 / (yaw * sens)
    config.in_game_sens = sens
    config.valorant_deg_per_count = yaw
    config.counts_per_deg_x = float(cpd)
    config.counts_per_deg_y = float(cpd)
    config.calibration_source = "valorant"
    config.calibration_r2 = 0.0
    config.calibration_samples = 0
    config.valorant_sens_at_calibration = sens
    config.calibration_updated_at = datetime.datetime.now().isoformat(timespec="seconds")
    if hasattr(app, "tracker"):
        app.tracker.in_game_sens = sens
    app.on_calibration_persisted()
    log_print(
        f"[Calibration] Valorant preset applied: {cpd:.3f} c/deg @ sens {sens:.3f}"
    )
    return True


def record_sample(app) -> bool:
    """Store ``(signed_px, counts)`` for the selected axis."""
    try:
        counts = float(app.calibration_counts_entry.get().strip())
        observed_px = float(app.calibration_px_entry.get().strip())
    except Exception:
        log_print("[Calibration] invalid sample values")
        return False
    if counts <= 0.0:
        log_print("[Calibration] impulse counts must be > 0")
        return False
    if observed_px == 0.0:
        log_print("[Calibration] measured shift must be non-zero (signed)")
        return False
    axis = str(app.calibration_axis_var.get()).strip().lower()
    axis = "y" if axis == "y" else "x"
    if not isinstance(getattr(app, "_calibration_samples", None), dict):
        app._calibration_samples = {"x": [], "y": []}
    app._calibration_samples.setdefault(axis, []).append((observed_px, counts))
    log_print(
        f"[Calibration] sample {axis}: {counts:.1f} counts -> {observed_px:+.2f} px "
        f"({len(app._calibration_samples[axis])} total)"
    )
    refresh_calibration_card(app)
    return True


def fit_and_save(app) -> bool:
    """Fit both axes; refuse incomplete or noisy data instead of extrapolating."""
    from src.aim_system.aim_math import (
        counts_per_deg_from_slope,
        fit_calibration,
        resolve_geometry,
    )

    samples_map = getattr(app, "_calibration_samples", {"x": [], "y": []})
    results = {}
    reasons = []
    for axis in ("x", "y"):
        samples = samples_map.get(axis, [])
        if len(samples) < MIN_SAMPLES_PER_AXIS:
            reasons.append(f"{axis}: {len(samples)}/{MIN_SAMPLES_PER_AXIS} samples")
            continue
        fit = fit_calibration(samples, min_r2=MIN_R2)
        if fit is None:
            reasons.append(f"{axis}: R² < {MIN_R2}")
            continue
        results[axis] = fit

    if reasons:
        log_print(
            "[Calibration] fit rejected: " + "; ".join(reasons) + ". "
            "Measure at least 5 points per axis across 4 directions."
        )
        return False

    geometry = resolve_geometry(frame=getattr(app.tracker, "_aim_frame", None))
    cpd_x, cpd_y = counts_per_deg_from_slope(
        geometry, results["x"][0], results["y"][0]
    )
    if cpd_x <= 0.0 or cpd_y <= 0.0:
        log_print("[Calibration] fit produced a non-positive scale; keeping current model")
        return False

    try:
        sens = float(app.calibration_sens_entry.get().strip())
    except Exception:
        sens = float(getattr(config, "in_game_sens", 0.23) or 0.23)

    config.counts_per_deg_x = float(cpd_x)
    config.counts_per_deg_y = float(cpd_y)
    config.calibration_r2 = float(min(results["x"][2], results["y"][2]))
    config.calibration_samples = int(
        len(samples_map.get("x", [])) + len(samples_map.get("y", []))
    )
    config.calibration_source = "measured"
    config.calibration_sens_at_measurement = sens
    config.calibration_updated_at = datetime.datetime.now().isoformat(timespec="seconds")
    app.on_calibration_persisted()
    log_print(
        f"[Calibration] saved counts_per_deg=({cpd_x:.4f}, {cpd_y:.4f}) "
        f"R²={config.calibration_r2:.4f} samples={config.calibration_samples}"
    )
    return True


def clear_measurement(app):
    """Drop the measured pair and fall back to the analytic model."""
    config.counts_per_deg_x = 0.0
    config.counts_per_deg_y = 0.0
    config.calibration_r2 = 0.0
    config.calibration_samples = 0
    config.calibration_sens_at_measurement = 0.0
    config.calibration_source = "analytic"
    config.calibration_updated_at = datetime.datetime.now().isoformat(timespec="seconds")
    app._calibration_samples = {"x": [], "y": []}
    app.on_calibration_persisted()
    log_print("[Calibration] measurement cleared; using the analytic model")
