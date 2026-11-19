"""
Tactical Gaming HUD components for CVM-colorBot.

Provides reusable, high-density HUD primitives (cards, sub-cards, compact
three-column sliders, switches, status pills and badges) that match the
Tactical Gaming HUD reference in `_perf_audit/cvm_colorbot_ui.html`.

The public contract of the previous dashboard widgets is preserved:
`ModernCard` keeps `title`, `content`, `set_open`/`is_open`; `ModernSlider`
keeps `key/min_val/max_val/is_float/suffix/command`, `get_value`/`set_value`;
`ModernSwitch` keeps `var`, `get_value`/`set_value`; `StatusPill` keeps
`label_prefix`, `value_text`, `dot` and `update_value`.
"""
import customtkinter as ctk
import tkinter as tk

from src.utils.i18n import t

# Fallback tokens used until a theme is applied. src/ui.py owns the real palette
# and pushes it through apply_theme(); this copy only keeps widget construction
# safe at import time (e.g. unit tests that never load a preset).
_DEFAULT_TOKENS = {
    "COLOR_BG": "#06080D",
    "COLOR_SIDEBAR": "#06090F",
    "COLOR_CARD": "#101622",
    "COLOR_CARD_BORDER": "#1E293B",
    "COLOR_CARD_HEADER": "#0E1420",
    "COLOR_SUB": "#0C111A",
    "COLOR_INPUT": "#070A10",
    "COLOR_ACCENT": "#00F59B",
    "COLOR_ACCENT_2": "#00D2FF",
    "COLOR_ACCENT_HOVER": "#00D2FF",
    "COLOR_BADGE_BG": "#0F1724",
    "COLOR_TEXT": "#E2E8F0",
    "COLOR_TEXT_DIM": "#94A3B8",
    "COLOR_HUD_MUTED": "#64748B",
    "COLOR_DANGER": "#FF2A5F",
    "COLOR_WARNING": "#FBBF24",
    "COLOR_SUCCESS": "#00F59B",
}

_TOKENS = dict(_DEFAULT_TOKENS)

# Fonts are detected once by src/ui.py (the only place that owns a Tk root at
# import time is None, so this must be lazy) and pushed here for all widgets.
_FONTS = {"gaming": "Segoe UI Semibold", "mono": "Consolas"}


def set_fonts(gaming=None, mono=None) -> None:
    """Set the family names used for HUD headings (gaming) and numerals (mono)."""
    if gaming:
        _FONTS["gaming"] = str(gaming)
    if mono:
        _FONTS["mono"] = str(mono)


def hud_font(size=10, weight="normal", mono=False):
    """Return a Tk font tuple for HUD chrome."""
    return (_FONTS["mono"] if mono else _FONTS["gaming"], size, weight)


def apply_theme(tokens: dict) -> None:
    """Copy COLOR_* entries of a theme preset into the active widget palette.

    Missing or malformed entries are ignored so a partial preset (or None) never
    crashes widget construction; previously applied tokens stay in place.
    """
    if not isinstance(tokens, dict):
        return
    for key, value in tokens.items():
        if isinstance(key, str) and key.startswith("COLOR_") and isinstance(value, str) and value:
            _TOKENS[key] = value


def get_token(name: str) -> str:
    """Return the currently active value of a widget color token."""
    return _TOKENS[name]


def _hex_to_rgb(color: str):
    raw = str(color or "").strip().lstrip("#")
    if len(raw) == 3:
        raw = "".join(ch * 2 for ch in raw)
    if len(raw) != 6:
        return (0, 0, 0)
    try:
        return (int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16))
    except ValueError:
        return (0, 0, 0)


def mix(color_a: str, color_b: str, ratio: float) -> str:
    """Blend `color_a` over `color_b`; ratio 0 -> b, 1 -> a."""
    ratio = max(0.0, min(1.0, float(ratio)))
    a = _hex_to_rgb(color_a)
    b = _hex_to_rgb(color_b)
    blended = tuple(int(round(a[i] * ratio + b[i] * (1.0 - ratio))) for i in range(3))
    return "#%02X%02X%02X" % blended


def luminance(color: str) -> float:
    """Rough perceived luminance (0-255) used to pick readable text on a fill."""
    r, g, b = _hex_to_rgb(color)
    return 0.299 * r + 0.587 * g + 0.114 * b


def readable_on(color: str, dark: str = "#04140A", light: str = "#FFFFFF") -> str:
    return dark if luminance(color) > 140 else light


class HudBadge(ctk.CTkFrame):
    """Tiny uppercase badge pill (`CORE`, `v1.2 ALGO`, `SLOT 1 // PRIMARY`)."""

    def __init__(self, parent, text, accent_color=None, font_size=8, **kwargs):
        accent = accent_color or _TOKENS["COLOR_ACCENT"]
        base = kwargs.pop("base_color", _TOKENS["COLOR_CARD"])
        super().__init__(
            parent,
            fg_color=mix(accent, base, 0.10),
            border_color=mix(accent, base, 0.32),
            border_width=1,
            corner_radius=3,
            height=16,
            **kwargs,
        )
        self.text = str(text)
        self.accent_color = accent
        self.label = ctk.CTkLabel(
            self,
            text=self.text.upper(),
            font=hud_font(font_size, "bold"),
            text_color=accent,
            padx=4,
            pady=0,
            height=14,
        )
        self.label.pack(padx=1, pady=0)

    def set_text(self, text):
        self.text = str(text)
        self.label.configure(text=self.text.upper())


class HudSectionTitle(ctk.CTkLabel):
    """Small dim uppercase caption used to group fields inside a card."""

    def __init__(self, parent, text, **kwargs):
        super().__init__(
            parent,
            text=str(text).upper(),
            font=hud_font(8, "bold"),
            text_color=_TOKENS["COLOR_TEXT_DIM"],
            anchor="w",
            justify="left",
            **kwargs,
        )


class SubCard(ctk.CTkFrame):
    """Sub-card with a 2px accent bar on the left edge."""

    def __init__(self, parent, accent_color=None, **kwargs):
        accent = accent_color or _TOKENS["COLOR_ACCENT"]
        super().__init__(
            parent,
            fg_color=_TOKENS["COLOR_SUB"],
            border_color=_TOKENS["COLOR_CARD_BORDER"],
            border_width=1,
            corner_radius=4,
            **kwargs,
        )
        self.accent_color = accent
        self.bar = ctk.CTkFrame(self, width=2, fg_color=accent, corner_radius=0)
        self.bar.pack(side="left", fill="y")
        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.pack(side="left", fill="both", expand=True, padx=0, pady=0)
        self.content = self.body

    def set_accent(self, color):
        self.accent_color = color
        try:
            self.bar.configure(fg_color=color)
        except Exception:
            pass


class ModernCard(ctk.CTkFrame):
    """HUD card: `#101622` body, 2px accent top border, header title + badge pill."""

    def __init__(
        self,
        parent,
        title: str,
        icon: str = None,
        badge_text: str = None,
        accent_color: str = None,
        collapsible: bool = False,
        initially_open: bool = True,
        on_toggle=None,
        show_header: bool = True,
        **kwargs
    ):
        accent_color = accent_color or _TOKENS["COLOR_ACCENT"]
        kwargs.setdefault("fg_color", _TOKENS["COLOR_CARD"])
        kwargs.setdefault("border_color", _TOKENS["COLOR_CARD_BORDER"])
        kwargs.setdefault("border_width", 1)
        kwargs.setdefault("corner_radius", 6)
        super().__init__(parent, **kwargs)
        self.title = title
        self.accent_color = accent_color
        self._collapsible = collapsible
        self._is_open = bool(initially_open)
        self._on_toggle = on_toggle
        self._show_header = bool(show_header)
        self._toggle_targets = []

        # 2px accent strip standing in for the CSS `border-top: 2px` accent edge.
        self.top_strip = ctk.CTkFrame(
            self,
            height=2,
            fg_color=mix(accent_color, _TOKENS["COLOR_CARD"], 0.55),
            corner_radius=0,
        )

        # Header container
        self.header_frame = ctk.CTkFrame(self, fg_color="transparent")

        # Left: Icon & Title
        title_left = ctk.CTkFrame(self.header_frame, fg_color="transparent")
        title_left.pack(side="left", fill="y")

        if collapsible:
            self.arrow_label = ctk.CTkLabel(
                title_left,
                text="\u25be" if self._is_open else "\u25b8",
                font=hud_font(9, "bold"),
                text_color=accent_color,
                width=10,
            )
            self.arrow_label.pack(side="left", padx=(0, 3))

        display_text = f"{icon}  {t(title)}" if icon else t(title)
        self.title_label = ctk.CTkLabel(
            title_left,
            text=str(display_text).upper(),
            font=hud_font(10, "bold"),
            text_color=accent_color,
            anchor="w",
            justify="left",
        )
        self.title_label.pack(side="left")

        # Right: Badge (Optional)
        if badge_text:
            self.badge_frame = HudBadge(self.header_frame, badge_text, accent_color=accent_color)
            self.badge_frame.pack(side="right")
            self.badge_label = self.badge_frame.label

        # Separator line
        self.sep = ctk.CTkFrame(self, height=1, fg_color=_TOKENS["COLOR_CARD_HEADER"])

        # Inner content container
        self.content = ctk.CTkFrame(self, fg_color="transparent")

        self._pack_content = lambda: self.content.pack(
            fill="both", expand=True, padx=9, pady=(0, 7)
        )
        if collapsible:
            self._toggle_targets = [self.header_frame, self.title_label, title_left]
            if hasattr(self, "arrow_label"):
                self._toggle_targets.append(self.arrow_label)
            if hasattr(self, "badge_frame"):
                self._toggle_targets.append(self.badge_frame)
                self._toggle_targets.append(self.badge_label)
            for widget in self._toggle_targets:
                widget.bind("<Button-1>", self._handle_toggle)
            self.header_frame.configure(cursor="hand2")

        # Shipped open: strip -> header -> separator -> content.
        self._mount_open()
        if collapsible and not self._is_open:
            self.sep.pack_forget()
            self.content.pack_forget()

    def _mount_open(self):
        self.top_strip.pack(fill="x", padx=1, pady=(1, 0))
        if self._show_header:
            self.header_frame.pack(fill="x", padx=9, pady=(5, 3))
            self.sep.pack(fill="x", padx=9, pady=(0, 5))
            self._pack_content()
        else:
            # Card used purely as a container (e.g. the combat strip): no chrome.
            self.content.pack(fill="both", expand=True, padx=7, pady=6)

    def _handle_toggle(self, _event=None):
        self.set_open(not self._is_open, notify=True)

    def set_open(self, is_open, notify=False):
        """Expand or collapse the card body. Notifies on_toggle only when notify=True."""
        if not self._collapsible:
            return
        is_open = bool(is_open)
        if is_open == self._is_open:
            return
        self._is_open = is_open
        if is_open:
            self.sep.pack(fill="x", padx=9, pady=(0, 5))
            self._pack_content()
        else:
            self.sep.pack_forget()
            self.content.pack_forget()
        if hasattr(self, "arrow_label"):
            self.arrow_label.configure(text="\u25be" if is_open else "\u25b8")
        if notify and self._on_toggle is not None:
            self._on_toggle(is_open)

    def is_open(self):
        return self._is_open


class ModernSlider(ctk.CTkFrame):
    """Compact HUD parameter row: `112px label | slider track | 54px numeric box`."""

    def __init__(
        self,
        parent,
        label: str,
        key: str,
        min_val: float,
        max_val: float,
        init_val: float,
        command=None,
        is_float: bool = False,
        suffix: str = "",
        accent_color: str = None,
        label_width: int = 112,
        **kwargs
    ):
        accent_color = accent_color or _TOKENS["COLOR_ACCENT"]
        super().__init__(parent, fg_color="transparent", **kwargs)
        self.key = key
        self.min_val = min_val
        self.max_val = max_val
        self.is_float = is_float
        self.suffix = suffix
        self.command = command
        self._current_value = float(init_val) if is_float else int(init_val)
        self._ignore_events = False
        self.label_width = int(label_width)

        self.grid_columnconfigure(0, minsize=self.label_width)
        self.grid_columnconfigure(1, weight=1, minsize=54)
        self.grid_columnconfigure(2, minsize=54)

        self.label_widget = ctk.CTkLabel(
            self,
            text=t(label),
            font=hud_font(9),
            text_color=_TOKENS["COLOR_TEXT"],
            anchor="w",
            justify="left",
            wraplength=self.label_width,
        )
        self.label_widget.grid(row=0, column=0, sticky="w", padx=(0, 6), pady=1)

        self.entry_var = tk.StringVar(value=self._format_value(self._current_value))
        self.entry = ctk.CTkEntry(
            self,
            textvariable=self.entry_var,
            width=54,
            height=19,
            fg_color=_TOKENS["COLOR_INPUT"],
            border_color=_TOKENS["COLOR_CARD_BORDER"],
            border_width=1,
            font=hud_font(9, "bold", mono=True),
            text_color=accent_color,
            justify="center",
            corner_radius=3,
        )
        self.entry.grid(row=0, column=2, sticky="e")
        self.entry.bind("<FocusOut>", self._on_entry_commit)
        self.entry.bind("<Return>", self._on_entry_commit)

        self.slider = ctk.CTkSlider(
            self,
            from_=min_val,
            to=max_val,
            number_of_steps=int((max_val - min_val) * 10) if is_float else max(1, int(max_val - min_val)),
            command=self._on_slider_moved,
            height=11,
            progress_color=accent_color,
            button_color=accent_color,
            button_hover_color=_TOKENS["COLOR_ACCENT_HOVER"],
            fg_color=_TOKENS["COLOR_INPUT"],
            button_length=9,
            button_corner_radius=2,
        )
        self.slider.set(self._current_value)
        self.slider.grid(row=0, column=1, sticky="ew", padx=(0, 6), pady=1)

    def _format_value(self, val):
        if self.is_float:
            return f"{float(val):.2f}"
        return f"{int(round(val))}"

    def _on_slider_moved(self, value):
        if self._ignore_events:
            return
        parsed = float(value) if self.is_float else int(round(value))
        self._current_value = parsed
        self._ignore_events = True
        self.entry_var.set(self._format_value(parsed))
        self._ignore_events = False
        if self.command:
            self.command(parsed)

    def _on_entry_commit(self, event=None):
        if self._ignore_events:
            return
        raw = self.entry_var.get().strip()
        try:
            val = float(raw) if self.is_float else int(float(raw))
            val = max(self.min_val, min(self.max_val, val))
        except ValueError:
            val = self._current_value
        self._current_value = val
        self._ignore_events = True
        self.slider.set(val)
        self.entry_var.set(self._format_value(val))
        self._ignore_events = False
        if self.command:
            self.command(val)

    def get_value(self):
        return self._current_value

    def set_value(self, val):
        val = max(self.min_val, min(self.max_val, val))
        self._current_value = float(val) if self.is_float else int(round(val))
        self._ignore_events = True
        self.slider.set(self._current_value)
        self.entry_var.set(self._format_value(self._current_value))
        self._ignore_events = False
        if self.command:
            self.command(self._current_value)


class ModernSwitch(ctk.CTkFrame):
    """Sub-card style toggle: title + subtitle on the left, switch on the right."""

    def __init__(
        self,
        parent,
        title: str,
        subtitle: str = None,
        init_val: bool = False,
        command=None,
        accent_color: str = None,
        **kwargs
    ):
        accent_color = accent_color or _TOKENS["COLOR_ACCENT"]
        kwargs.setdefault("fg_color", _TOKENS["COLOR_SUB"])
        kwargs.setdefault("border_color", _TOKENS["COLOR_CARD_BORDER"])
        kwargs.setdefault("border_width", 1)
        kwargs.setdefault("corner_radius", 4)
        super().__init__(parent, **kwargs)
        self.command = command
        self.var = tk.BooleanVar(value=bool(init_val))
        self.accent_color = accent_color

        self.bar = ctk.CTkFrame(self, width=2, fg_color=accent_color, corner_radius=0)
        self.bar.pack(side="left", fill="y")

        inner = ctk.CTkFrame(self, fg_color="transparent")
        inner.pack(side="left", fill="x", expand=True, padx=8, pady=4)

        text_frame = ctk.CTkFrame(inner, fg_color="transparent")
        text_frame.pack(side="left", fill="both", expand=True)

        self.title_lbl = ctk.CTkLabel(
            text_frame,
            text=str(t(title)).upper(),
            font=hud_font(9, "bold"),
            text_color=_TOKENS["COLOR_TEXT"],
            anchor="w",
            justify="left",
        )
        self.title_lbl.pack(fill="x")

        if subtitle:
            self.sub_lbl = ctk.CTkLabel(
                text_frame,
                text=t(subtitle),
                font=hud_font(8),
                text_color=_TOKENS["COLOR_TEXT_DIM"],
                anchor="w",
                justify="left",
            )
            self.sub_lbl.pack(fill="x", pady=(0, 0))

        self.switch = ctk.CTkSwitch(
            inner,
            text="",
            variable=self.var,
            command=self._on_toggled,
            width=34,
            height=16,
            switch_width=28,
            switch_height=14,
            progress_color=accent_color,
            button_color="#FFFFFF",
            button_hover_color="#E2E8F0",
            fg_color=_TOKENS["COLOR_CARD_HEADER"],
        )
        self.switch.pack(side="right", padx=(6, 0))

    def _on_toggled(self):
        val = self.var.get()
        if self.command:
            self.command(val)

    def get_value(self):
        return self.var.get()

    def set_value(self, val: bool):
        self.var.set(bool(val))
        if self.command:
            self.command(bool(val))


class StatusPill(ctk.CTkFrame):
    """Flat HUD telemetry pill: colored dot + `LABEL: value` in mono type."""

    def __init__(
        self,
        parent,
        label: str,
        value: str,
        dot_color: str = None,
        **kwargs
    ):
        dot_color = dot_color or _TOKENS["COLOR_ACCENT"]
        super().__init__(
            parent,
            fg_color=_TOKENS["COLOR_INPUT"],
            border_color=_TOKENS["COLOR_CARD_BORDER"],
            border_width=1,
            corner_radius=3,
            height=18,
            **kwargs
        )
        self.label_prefix = label
        self.value_text = value

        self.inner = ctk.CTkFrame(self, fg_color="transparent")
        self.inner.pack(padx=5, pady=0)

        # Dot
        self.dot = ctk.CTkLabel(
            self.inner,
            text="●",
            font=("Arial", 7),
            text_color=dot_color,
            width=8,
            height=10,
        )
        self.dot.pack(side="left", padx=(0, 3))

        # Text
        display = f"{label}: {value}" if label else value
        self.text_label = ctk.CTkLabel(
            self.inner,
            text=display,
            font=hud_font(9, "bold", mono=True),
            text_color=_TOKENS["COLOR_TEXT"],
            height=14,
        )
        self.text_label.pack(side="left")

    def update_value(self, value: str, dot_color: str = None):
        self.value_text = str(value)
        display = f"{self.label_prefix}: {value}" if self.label_prefix else value
        self.text_label.configure(text=display)
        if dot_color:
            self.dot.configure(text_color=dot_color)

    def set_dot_color(self, dot_color: str):
        self.dot.configure(text_color=dot_color)


# HUD alias: the reference UI calls these "pills"; the legacy tests import
# StatusPill, so both names point at the same implementation.
HudPill = StatusPill
