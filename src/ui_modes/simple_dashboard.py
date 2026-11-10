"""Simple Mode dashboard builder (plan §5).

A dedicated widget tree, not "Pro with a few sections collapsed". The whole
layout is six fixed blocks inside a ``CTkFrame`` (never a
``CTkScrollableFrame``), with:

* **no sidebar** (the nav lives in Pro only),
* **no canvas / chart / tooltip top-level** (those are Pro-only),
* **six sliders and three option menus** — the full contents of the compact
  dashboard, which fits easily in 560×540.

The builder deliberately reuses the existing attribute names
(``runtime_btn``, ``mode_option``, ``aim_key_bind_button``, ``fovsize``,
``pill_fps`` …) so the scheduler, the settings loader and the runtime button
refresher keep working without a second, parallel contract.

Nothing here rebuilds on a mode change: ``refresh_simple_dashboard`` only moves
two pre-built rows with ``grid``/``grid_remove`` (plan §5.4).
"""

from __future__ import annotations

import tkinter as tk

import customtkinter as ctk

from src.utils.config import config
from src.utils.i18n import t
from src.ui_components import StatusPill

#: Widget budget from plan §5.5 (Tk widgets, counted recursively).
SIMPLE_WIDGET_BUDGET = 150

#: Mode value that swaps the Sec "Gain" row for the "Speed" row.
FLICK_MODE = "Flick"

#: Mirrors ``src.ui.AIM_MODE_OPTIONS``. Duplicated instead of imported because
#: ``src.ui`` imports this module (a reverse import would be circular); the
#: builder reads the app attribute first, so the UI stays the source of truth.
_DEFAULT_MODE_OPTIONS = [
    "Normal",
    "Flick",
    "Silent",
    "NCAF",
    "WindMouse",
    "Bezier",
    "PID Controller ( RISK )",
]


def _mode_options(app):
    return list(getattr(app, "AIM_MODE_OPTIONS", None) or _DEFAULT_MODE_OPTIONS)


def _make_card(app, parent, title: str, accent: str):
    """A flat card: header label + 1 px separator + content frame."""
    card = ctk.CTkFrame(
        parent,
        fg_color="#141822",
        corner_radius=8,
        border_width=1,
        border_color="#232B3B",
    )
    head = ctk.CTkLabel(
        card,
        text=t(title).upper(),
        font=("Segoe UI", 9, "bold"),
        text_color=accent,
        anchor="w",
        height=16,
    )
    head.pack(fill="x", padx=10, pady=(5, 1))
    ctk.CTkFrame(card, height=1, fg_color="#1D2433").pack(fill="x", padx=10)
    body = ctk.CTkFrame(card, fg_color="transparent")
    body.pack(fill="both", expand=True, padx=10, pady=(4, 5))
    return card, body


def _row(parent):
    row = ctk.CTkFrame(parent, fg_color="transparent")
    row.pack(fill="x", pady=1)
    return row


def _labeled(parent, text, color="#E2E8F0", width=None, font=None):
    label = ctk.CTkLabel(
        parent,
        text=t(text),
        font=font or ("Segoe UI", 9),
        text_color=color,
        anchor="w",
    )
    if width is not None:
        label.configure(width=width)
    return label


class SimpleSliderRow(ctk.CTkFrame):
    """Label + live value + slider. Six Tk widgets instead of eleven.

    ``_add_slider_in_frame`` (the Pro row) carries a header frame plus an editable
    entry widget: three extra widgets per row, times seven sliders. In a 560 px
    dashboard the value is shown read-only and edited with the slider; Pro keeps
    the precise numeric entry.

    The row still registers into ``app._slider_widgets`` with ``entry=None`` so
    ``_set_slider_value`` / ``_apply_settings`` reach it exactly like a Pro
    slider (plan §5.3 contract).
    """

    def __init__(self, app, parent, label_text, key, minimum, maximum, init, command, is_float=False):
        super().__init__(parent, fg_color="transparent")
        self.key = key
        self.min_val = float(minimum)
        self.max_val = float(maximum)
        self.is_float = bool(is_float)
        self.command = command
        self._value = float(init)

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x")
        ctk.CTkLabel(
            head,
            text=t(label_text),
            font=("Segoe UI", 9),
            text_color="#E2E8F0",
            anchor="w",
            height=14,
        ).pack(side="left")
        self.value_lbl = ctk.CTkLabel(
            head,
            text=self._format(self._value),
            font=("Consolas", 9, "bold"),
            text_color="#94A3B8",
            anchor="e",
            height=14,
        )
        self.value_lbl.pack(side="right")

        self.slider = ctk.CTkSlider(
            self,
            from_=minimum,
            to=maximum,
            number_of_steps=max(1, int((maximum - minimum) * (10 if is_float else 1))),
            command=self._on_moved,
            height=10,
            progress_color="#10B981",
            button_color="#10B981",
            button_hover_color="#34D399",
            fg_color="#1E2536",
        )
        self.slider.set(self._value)
        self.slider.pack(fill="x", pady=(0, 1))

        app._register_slider(key, self.slider, None, minimum, maximum, is_float)

    def _format(self, value):
        return f"{float(value):.2f}" if self.is_float else f"{int(round(float(value)))}"

    def _on_moved(self, raw):
        parsed = float(raw) if self.is_float else int(round(float(raw)))
        parsed = max(self.min_val, min(self.max_val, parsed))
        self._value = float(parsed)
        try:
            self.value_lbl.configure(text=self._format(parsed))
        except Exception:
            pass
        if self.command is not None:
            self.command(parsed)

    def set_display(self, value):
        """Push a config value in without re-invoking the callback."""
        try:
            parsed = float(value)
        except Exception:
            return
        parsed = max(self.min_val, min(self.max_val, parsed))
        self._value = parsed
        try:
            self.slider.set(parsed)
            self.value_lbl.configure(text=self._format(parsed))
        except Exception:
            pass


def _compact_slider(app, parent, label_text, key, minimum, maximum, init, command, is_float=False):
    """Build a :class:`SimpleSliderRow`, pack it, and return the row."""
    row = SimpleSliderRow(
        app, parent, label_text, key, minimum, maximum, init, command, is_float=is_float
    )
    row.pack(fill="x", pady=1)
    return row


def build_simple_dashboard(app, parent) -> ctk.CTkFrame:
    """Build the six core blocks inside ``parent`` and register their attributes."""
    root = ctk.CTkFrame(parent, fg_color="transparent")
    root.pack(fill="both", expand=True, padx=12, pady=(2, 8))

    _build_engine_block(app, root)
    _build_aim_blocks(app, root)
    _build_quick_block(app, root)
    _build_footer(app, root)
    return root


# --- block 1: master engine + telemetry ------------------------------------
def _build_engine_block(app, parent):
    card, body = _make_card(app, parent, "Engine", "#10B981")
    card.pack(fill="x", pady=(0, 6))

    app.runtime_btn = ctk.CTkButton(
        body,
        text=t("START ENGINE"),
        command=app._toggle_runtime,
        fg_color="#10B981",
        hover_color="#059669",
        text_color="#022C22",
        font=("Segoe UI", 12, "bold"),
        height=40,
        corner_radius=8,
    )
    app.runtime_btn.pack(fill="x", pady=(0, 6))
    app._refresh_runtime_button()

    pills = ctk.CTkFrame(body, fg_color="transparent")
    pills.pack(fill="x")

    hw_init = getattr(config, "mouse_api", "Serial")
    app.pill_fps = StatusPill(pills, "FPS", "--", dot_color="#10B981")
    app.pill_fps.pack(side="left", padx=(0, 4))
    # Kept as ``pill_delay`` (same attribute name as Pro) so the scheduler and
    # the existing tests address one widget, not two.
    app.pill_delay = StatusPill(pills, "Ping", "-- ms", dot_color="#06B6D4")
    app.pill_delay.pack(side="left", padx=(0, 4))
    app.pill_hardware = StatusPill(pills, "HW", str(hw_init), dot_color="#94A3B8")
    app.pill_hardware.pack(side="left", padx=(0, 4))
    app.pill_conn = StatusPill(pills, "", "OFFLINE", dot_color="#F43F5E")
    app.pill_conn.pack(side="left")

    app.status_indicator = ctk.CTkLabel(
        body,
        text=t("Status: Offline"),
        font=("Segoe UI", 9),
        text_color="#94A3B8",
        anchor="w",
    )
    app.status_indicator.pack(fill="x", pady=(4, 0))


# --- blocks 2 and 3: main aim + sec aim / flick ---------------------------
def _build_aim_blocks(app, parent):
    columns = ctk.CTkFrame(parent, fg_color="transparent")
    columns.pack(fill="x", pady=(0, 6))
    columns.grid_columnconfigure(0, weight=1, uniform="aim")
    columns.grid_columnconfigure(1, weight=1, uniform="aim")

    _build_main_aim_card(app, columns)
    _build_sec_aim_card(app, columns)


def _build_main_aim_card(app, parent):
    card, body = _make_card(app, parent, "Main Aim", "#10B981")
    card.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
    app.simple_main_card = card

    app.var_enableaim = tk.BooleanVar(value=bool(getattr(config, "enableaim", False)))
    enable = ctk.CTkSwitch(
        body,
        text=t("Enable Aimbot"),
        variable=app.var_enableaim,
        command=app._on_enableaim_changed,
        font=("Segoe UI", 10, "bold"),
        progress_color="#10B981",
        width=40,
        switch_width=34,
        switch_height=16,
    )
    enable.pack(anchor="w", pady=(0, 2))
    app._checkbox_vars["enableaim"] = app.var_enableaim

    app.mode_option = _simple_option_row(
        body,
        "Mode",
        _mode_options(app),
        app._on_mode_selected,
    )
    app._option_widgets["mode"] = app.mode_option
    app.mode_option.set(app._aim_mode_value_to_display(getattr(config, "mode", "Normal")))

    app.aim_key_bind_button = app._add_bind_capture_row_in_frame(
        body,
        "Aim Key",
        app._ads_binding_to_display(getattr(config, "selected_mouse_button", 3)),
        lambda: app._start_aim_key_capture(is_sec=False),
    )
    _shrink_bind_button(app.aim_key_bind_button)

    _compact_slider(
        app,
        body,
        "FOV",
        "fovsize",
        1,
        1000,
        float(getattr(config, "fovsize", 100)),
        app._on_fovsize_changed,
    )
    _compact_slider(
        app,
        body,
        "Speed",
        "normal_x_speed",
        0.1,
        20.0,
        float(getattr(config, "normal_x_speed", 0.5)),
        app._on_normal_x_speed_changed,
        is_float=True,
    )
    _compact_slider(
        app,
        body,
        "Smooth",
        "normalsmooth",
        1,
        100,
        float(getattr(config, "normalsmooth", 10)),
        app._on_config_normal_smooth_changed,
    )


def _build_sec_aim_card(app, parent):
    card, body = _make_card(app, parent, "Sec Aim / Flick", "#06B6D4")
    card.grid(row=0, column=1, sticky="nsew", padx=(4, 0))
    app.simple_sec_card = card

    app.var_enableaim_sec = tk.BooleanVar(value=bool(getattr(config, "enableaim_sec", False)))
    enable = ctk.CTkSwitch(
        body,
        text=t("Enable Sec / Flick"),
        variable=app.var_enableaim_sec,
        command=app._on_enableaim_sec_changed,
        font=("Segoe UI", 10, "bold"),
        progress_color="#06B6D4",
        width=40,
        switch_width=34,
        switch_height=16,
    )
    enable.pack(anchor="w", pady=(0, 2))
    app._checkbox_vars["enableaim_sec"] = app.var_enableaim_sec

    app.mode_option_sec = _simple_option_row(
        body,
        "Mode",
        _mode_options(app),
        app._on_mode_sec_selected,
    )
    app._option_widgets["mode_sec"] = app.mode_option_sec
    app.mode_option_sec.set(app._aim_mode_value_to_display(getattr(config, "mode_sec", "Normal")))

    app.aim_key_bind_button_sec = app._add_bind_capture_row_in_frame(
        body,
        "Aim Key",
        app._ads_binding_to_display(getattr(config, "selected_mouse_button_sec", 2)),
        lambda: app._start_aim_key_capture(is_sec=True),
    )
    _shrink_bind_button(app.aim_key_bind_button_sec)

    _compact_slider(
        app,
        body,
        "FOV",
        "fovsize_sec",
        1,
        1000,
        float(getattr(config, "fovsize_sec", 150)),
        app._on_fovsize_sec_changed,
    )

    # Row 5 is built ONCE per variant and toggled with grid_remove/grid: a mode
    # change must never destroy a widget (that was the 50-150 ms freeze), and
    # grid keeps the row in place instead of re-appending it to the bottom.
    tuning = ctk.CTkFrame(body, fg_color="transparent")
    tuning.pack(fill="x")
    tuning.grid_columnconfigure(0, weight=1)
    app.simple_sec_tuning_frame = tuning

    app.simple_sec_gain_row = _compact_slider(
        app,
        tuning,
        "Gain",
        "flick_gain_sec",
        0.1,
        3.0,
        float(getattr(config, "flick_gain_sec", 1.0)),
        app.flick_handler_for("flick_gain_sec"),
        is_float=True,
    )
    app.simple_sec_speed_row = _compact_slider(
        app,
        tuning,
        "Speed",
        "normal_x_speed_sec",
        0.1,
        20.0,
        float(getattr(config, "normal_x_speed_sec", 2.0)),
        app._on_normal_x_speed_sec_changed,
        is_float=True,
    )
    for index, row in enumerate((app.simple_sec_gain_row, app.simple_sec_speed_row)):
        row.pack_forget()
        row.grid(row=index, column=0, sticky="ew")
    app.simple_sec_speed_row.grid_remove()
    _compact_slider(
        app,
        body,
        "Smooth",
        "normalsmooth_sec",
        1,
        100,
        float(getattr(config, "normalsmooth_sec", 20)),
        app._on_config_normal_smooth_sec_changed,
    )


def _simple_option_row(parent, label_text, values, command):
    row = _row(parent)
    _labeled(row, label_text, width=44).pack(side="left")
    menu = ctk.CTkOptionMenu(
        row,
        values=values,
        command=command,
        width=124,
        height=22,
        fg_color="#1A202C",
        button_color="#1A202C",
        button_hover_color="#232B3B",
        dropdown_fg_color="#141822",
        text_color="#E2E8F0",
        font=("Segoe UI", 9),
        corner_radius=6,
    )
    menu.pack(side="right")
    return menu


def _shrink_bind_button(button):
    try:
        button.configure(width=124, height=22, font=("Segoe UI", 9))
    except Exception:
        pass


# --- block 4: quick switches + active profile -----------------------------
def _build_quick_block(app, parent):
    card, body = _make_card(app, parent, "Quick", "#F59E0B")
    card.pack(fill="x", pady=(0, 6))
    app.simple_quick_card = card

    switches = ctk.CTkFrame(body, fg_color="transparent")
    switches.pack(fill="x", pady=(0, 2))

    # ``var_enabletb_quick`` is new on purpose: the old ``var_enabletb`` only
    # ever existed inside the dead ``_show_tb_tab`` body, so there was nothing
    # to reuse (plan §5.3 row 4).
    app.var_enabletb_quick = tk.BooleanVar(value=bool(getattr(config, "enabletb", False)))
    trigger = ctk.CTkSwitch(
        switches,
        text=t("Triggerbot"),
        variable=app.var_enabletb_quick,
        command=app._on_quick_trigger_changed,
        font=("Segoe UI", 10),
        progress_color="#F59E0B",
        width=40,
        switch_width=32,
        switch_height=15,
    )
    trigger.pack(side="left", padx=(0, 12))
    app._checkbox_vars["enabletb"] = app.var_enabletb_quick

    app.var_enablercs = tk.BooleanVar(value=bool(getattr(config, "enablercs", True)))
    rcs = ctk.CTkSwitch(
        switches,
        text=t("RCS"),
        variable=app.var_enablercs,
        command=app._on_enablercs_changed,
        font=("Segoe UI", 10),
        progress_color="#06B6D4",
        width=40,
        switch_width=32,
        switch_height=15,
    )
    rcs.pack(side="left")
    app._checkbox_vars["enablercs"] = app.var_enablercs

    profile_row = _row(body)
    _labeled(profile_row, "Profile", color="#94A3B8", width=44).pack(side="left")
    app.simple_profile_option = ctk.CTkOptionMenu(
        profile_row,
        values=app._simple_profile_names(),
        command=app._on_simple_profile_selected,
        width=140,
        height=22,
        fg_color="#1A202C",
        button_color="#1A202C",
        button_hover_color="#232B3B",
        dropdown_fg_color="#141822",
        text_color="#E2E8F0",
        font=("Segoe UI", 9),
        corner_radius=6,
    )
    app.simple_profile_option.pack(side="left", padx=(0, 6))
    _select_current_profile(app)
    load = ctk.CTkButton(
        profile_row,
        text=t("LOAD"),
        command=app._load_selected_config,
        width=52,
        height=22,
        font=("Segoe UI", 9, "bold"),
        fg_color="#1A202C",
        hover_color="#232B3B",
        text_color="#E2E8F0",
        corner_radius=6,
        border_width=1,
        border_color="#232B3B",
    )
    load.pack(side="left")


def _build_footer(app, parent):
    footer = ctk.CTkFrame(parent, fg_color="transparent")
    footer.pack(fill="x", side="bottom")

    app.simple_pro_btn = ctk.CTkButton(
        footer,
        text="⭐ Pro Mode",
        command=lambda: app._apply_ui_mode("pro"),
        width=112,
        height=26,
        font=("Segoe UI", 10, "bold"),
        fg_color="#1A202C",
        hover_color="#232B3B",
        text_color="#10B981",
        border_width=1,
        border_color="#232B3B",
        corner_radius=8,
    )
    app.simple_pro_btn.pack(side="left")

    hotkey = str(getattr(config, "ui_toggle_hotkey", "Insert") or "Insert")
    app.simple_hide_btn = ctk.CTkButton(
        footer,
        text=f"{t('Hide')} ({hotkey})",
        command=app._hide_window,
        width=104,
        height=26,
        font=("Segoe UI", 9),
        fg_color="transparent",
        hover_color="#232B3B",
        text_color="#94A3B8",
        border_width=1,
        border_color="#232B3B",
        corner_radius=8,
    )
    app.simple_hide_btn.pack(side="right")


# --- refresh (never rebuilds) ---------------------------------------------
def refresh_simple_dashboard(app, changed=None) -> None:
    """Re-read the config into the Simple widgets, touching only what changed.

    ``changed`` is an optional iterable of config keys. ``None`` means "refresh
    everything". Rows are toggled with ``grid``/``grid_remove`` — never destroyed.
    """
    changed = set(changed or ()) if changed is not None else None

    if changed is None or "mode" in changed:
        _safe_set(app, "mode_option", app._aim_mode_value_to_display(getattr(config, "mode", "Normal")))
    if changed is None or "mode_sec" in changed:
        _safe_set(
            app,
            "mode_option_sec",
            app._aim_mode_value_to_display(getattr(config, "mode_sec", "Normal")),
        )

    if changed is None or "enableaim" in changed:
        _safe_var(app, "var_enableaim", bool(getattr(config, "enableaim", False)))
    if changed is None or "enableaim_sec" in changed:
        _safe_var(app, "var_enableaim_sec", bool(getattr(config, "enableaim_sec", False)))
    if changed is None or "enabletb" in changed:
        _safe_var(app, "var_enabletb_quick", bool(getattr(config, "enabletb", False)))
    if changed is None or "enablercs" in changed:
        _safe_var(app, "var_enablercs", bool(getattr(config, "enablercs", True)))

    if changed is None or "selected_mouse_button" in changed:
        button = getattr(app, "aim_key_bind_button", None)
        if button is not None:
            app._set_bind_button_text(
                button,
                app._ads_binding_to_display(getattr(config, "selected_mouse_button", 3)),
            )
    if changed is None or "selected_mouse_button_sec" in changed:
        button = getattr(app, "aim_key_bind_button_sec", None)
        if button is not None:
            app._set_bind_button_text(
                button,
                app._ads_binding_to_display(getattr(config, "selected_mouse_button_sec", 2)),
            )

    if changed is None or "mode_sec" in changed:
        _apply_sec_tuning_row(app)

    if changed is None or "flick_gain_sec" in changed:
        _set_row_value(app, "flick_gain_sec", float(getattr(config, "flick_gain_sec", 1.0)))
    # Slider values are only re-pushed when the caller says they moved; the
    # scheduler never calls this, so there is no periodic widget churn.
    for key, attr, default in (
        ("fovsize", "fovsize", 100),
        ("normal_x_speed", "normal_x_speed", 0.5),
        ("normalsmooth", "normalsmooth", 10),
        ("fovsize_sec", "fovsize_sec", 150),
        ("normal_x_speed_sec", "normal_x_speed_sec", 2.0),
        ("normalsmooth_sec", "normalsmooth_sec", 20),
    ):
        if changed is None or key in changed:
            _set_row_value(app, key, float(getattr(config, attr, default)))

    _refresh_simple_telemetry(app)


def _set_row_value(app, key, value) -> None:
    """Push a value into a Simple row (slider + label) without firing callbacks."""
    entry = app._slider_widgets.get(key)
    if entry is None:
        return
    row = _row_owner(entry)
    if row is not None:
        row.set_display(value)
        return
    app._set_slider_value(key, value)


def _row_owner(entry):
    """Return the :class:`SimpleSliderRow` backing a registry entry, if any.

    ``SimpleSliderRow`` owns the slider directly (``row.master is row``), so a
    single ``master`` hop is enough — no tree walk, no ambiguity with the Pro
    rows whose master is a plain ``CTkFrame``.
    """
    slider = entry.get("slider")
    master = getattr(slider, "master", None)
    return master if isinstance(master, SimpleSliderRow) else None


def _apply_sec_tuning_row(app) -> None:
    """Flick -> show Gain; every other mode -> show Speed. Never destroys."""
    gain_row = getattr(app, "simple_sec_gain_row", None)
    speed_row = getattr(app, "simple_sec_speed_row", None)
    if gain_row is None or speed_row is None:
        return
    mode = app._aim_mode_display_to_value(getattr(config, "mode_sec", "Normal"))
    show_gain = mode == FLICK_MODE
    try:
        if show_gain:
            speed_row.grid_remove()
            gain_row.grid()
        else:
            gain_row.grid_remove()
            speed_row.grid()
    except Exception:
        pass


def _refresh_simple_telemetry(app) -> None:
    """Push cached FPS/ping strings into the pills; called on real changes only."""
    for attr, text in (
        ("pill_fps", getattr(app, "_simple_fps_text", None)),
        ("pill_delay", getattr(app, "_simple_ping_text", None)),
    ):
        pill = getattr(app, attr, None)
        if pill is None or not text:
            continue
        try:
            if pill.winfo_exists():
                pill.update_value(text)
        except Exception:
            pass


def _select_current_profile(app) -> None:
    menu = getattr(app, "simple_profile_option", None)
    if menu is None:
        return
    try:
        menu.set(app._current_profile_name())
    except Exception:
        pass


def _safe_set(app, attr, value) -> None:
    widget = getattr(app, attr, None)
    if widget is None:
        return
    try:
        if widget.winfo_exists():
            widget.set(str(value))
    except Exception:
        pass


def _safe_var(app, attr, value) -> None:
    var = getattr(app, attr, None)
    if var is None:
        return
    try:
        var.set(bool(value))
    except Exception:
        pass


def simple_widget_count(app) -> int:
    """Recursive Tk widget count, used by the layout budget test/QA."""
    def _count(widget):
        total = 1
        try:
            children = widget.winfo_children()
        except Exception:
            return total
        for child in children:
            total += _count(child)
        return total

    return _count(app)


__all__ = [
    "SIMPLE_WIDGET_BUDGET",
    "build_simple_dashboard",
    "refresh_simple_dashboard",
    "simple_widget_count",
]
