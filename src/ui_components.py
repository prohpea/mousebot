"""
Modern UI Components for CVM-colorBot (Gaming Dashboard Style)
Provides reusable, high-contrast, theme-consistent cards, sliders, switches, and status pills.
"""
import customtkinter as ctk
import tkinter as tk
from src.utils.i18n import t

# Theme Color Tokens
COLOR_SURFACE_CARD = "#141822"
COLOR_BORDER_CARD = "#232B3B"
COLOR_HEADER_BORDER = "#1D2433"
COLOR_ACCENT_EMERALD = "#10B981"
COLOR_ACCENT_CYAN = "#06B6D4"
COLOR_ACCENT_AMBER = "#F59E0B"
COLOR_ACCENT_ROSE = "#F43F5E"
COLOR_SLATE_TEXT = "#E2E8F0"
COLOR_SLATE_MUTED = "#94A3B8"
COLOR_SLATE_DARK = "#64748B"
COLOR_INPUT_BG = "#1A202C"


class ModernCard(ctk.CTkFrame):
    """
    Standardized 2-Column Dashboard Card with rounded corners, subtle border,
    header with icon/title, optional badge, and content container.
    """
    def __init__(
        self,
        parent,
        title: str,
        icon: str = None,
        badge_text: str = None,
        accent_color: str = COLOR_ACCENT_EMERALD,
        **kwargs
    ):
        super().__init__(
            parent,
            fg_color=COLOR_SURFACE_CARD,
            border_color=COLOR_BORDER_CARD,
            border_width=1,
            corner_radius=10,
            **kwargs
        )
        self.title = title
        self.accent_color = accent_color
        
        # Header container
        self.header_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.header_frame.pack(fill="x", padx=12, pady=(10, 6))

        # Left: Icon & Title
        title_left = ctk.CTkFrame(self.header_frame, fg_color="transparent")
        title_left.pack(side="left", fill="y")

        display_text = f"{icon}  {t(title)}" if icon else t(title)
        self.title_label = ctk.CTkLabel(
            title_left,
            text=display_text,
            font=("Segoe UI", 11, "bold"),
            text_color=accent_color,
            anchor="w",
        )
        self.title_label.pack(side="left")

        # Right: Badge (Optional)
        if badge_text:
            self.badge_frame = ctk.CTkFrame(
                self.header_frame,
                fg_color="#1A2130",
                corner_radius=4,
                border_width=1,
                border_color="#283347",
            )
            self.badge_frame.pack(side="right")
            self.badge_label = ctk.CTkLabel(
                self.badge_frame,
                text=str(badge_text),
                font=("Consolas", 9),
                text_color=COLOR_SLATE_MUTED,
                padx=6,
                pady=1,
            )
            self.badge_label.pack()

        # Separator line
        self.sep = ctk.CTkFrame(self, height=1, fg_color=COLOR_HEADER_BORDER)
        self.sep.pack(fill="x", padx=12, pady=(0, 8))

        # Inner content container
        self.content = ctk.CTkFrame(self, fg_color="transparent")
        self.content.pack(fill="both", expand=True, padx=12, pady=(0, 10))


class ModernSlider(ctk.CTkFrame):
    """
    Standardized slider row with label, value badge, smooth CTkSlider, and numeric entry box.
    """
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
        accent_color: str = COLOR_ACCENT_EMERALD,
        **kwargs
    ):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self.key = key
        self.min_val = min_val
        self.max_val = max_val
        self.is_float = is_float
        self.suffix = suffix
        self.command = command
        self._current_value = float(init_val) if is_float else int(init_val)
        self._ignore_events = False

        # Top label row: Name on left, Value Entry on right
        label_row = ctk.CTkFrame(self, fg_color="transparent")
        label_row.pack(fill="x", pady=(0, 2))

        self.label_widget = ctk.CTkLabel(
            label_row,
            text=t(label),
            font=("Segoe UI", 10),
            text_color=COLOR_SLATE_TEXT,
            anchor="w",
        )
        self.label_widget.pack(side="left")

        # Right value entry
        self.entry_var = tk.StringVar(value=self._format_value(self._current_value))
        self.entry = ctk.CTkEntry(
            label_row,
            textvariable=self.entry_var,
            width=58,
            height=22,
            fg_color=COLOR_INPUT_BG,
            border_color=COLOR_BORDER_CARD,
            border_width=1,
            font=("Consolas", 10, "bold"),
            text_color=accent_color,
            justify="center",
            corner_radius=4,
        )
        self.entry.pack(side="right")
        self.entry.bind("<FocusOut>", self._on_entry_commit)
        self.entry.bind("<Return>", self._on_entry_commit)

        # Slider bar
        self.slider = ctk.CTkSlider(
            self,
            from_=min_val,
            to=max_val,
            number_of_steps=int((max_val - min_val) * 10) if is_float else int(max_val - min_val),
            command=self._on_slider_moved,
            height=14,
            progress_color=accent_color,
            button_color=accent_color,
            button_hover_color="#34D399" if accent_color == COLOR_ACCENT_EMERALD else "#38BDF8",
            fg_color="#1E2536",
        )
        self.slider.set(self._current_value)
        self.slider.pack(fill="x", pady=(1, 4))

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
            val = float(raw) if self.is_float else int(raw)
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
    """
    Standardized toggle switch with title, subtitle description, and reactive state.
    """
    def __init__(
        self,
        parent,
        title: str,
        subtitle: str = None,
        init_val: bool = False,
        command=None,
        accent_color: str = COLOR_ACCENT_EMERALD,
        **kwargs
    ):
        super().__init__(parent, fg_color="#181E2B", corner_radius=8, border_color=COLOR_BORDER_CARD, border_width=1, **kwargs)
        self.command = command
        self.var = tk.BooleanVar(value=bool(init_val))

        inner = ctk.CTkFrame(self, fg_color="transparent")
        inner.pack(fill="x", padx=10, pady=8)

        text_frame = ctk.CTkFrame(inner, fg_color="transparent")
        text_frame.pack(side="left", fill="both", expand=True)

        self.title_lbl = ctk.CTkLabel(
            text_frame,
            text=t(title),
            font=("Segoe UI", 10, "bold"),
            text_color=COLOR_SLATE_TEXT,
            anchor="w",
        )
        self.title_lbl.pack(fill="x")

        if subtitle:
            self.sub_lbl = ctk.CTkLabel(
                text_frame,
                text=t(subtitle),
                font=("Segoe UI", 8),
                text_color=COLOR_SLATE_MUTED,
                anchor="w",
            )
            self.sub_lbl.pack(fill="x", pady=(1, 0))

        self.switch = ctk.CTkSwitch(
            inner,
            text="",
            variable=self.var,
            command=self._on_toggled,
            width=42,
            height=20,
            switch_width=36,
            switch_height=18,
            progress_color=accent_color,
            button_color="#FFFFFF",
            fg_color="#2D3748",
        )
        self.switch.pack(side="right")

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
    """
    Compact status pill for header or footer displaying telemetry with colored indicator dot.
    """
    def __init__(
        self,
        parent,
        label: str,
        value: str,
        dot_color: str = COLOR_ACCENT_EMERALD,
        **kwargs
    ):
        super().__init__(
            parent,
            fg_color="#171C28",
            border_color="#252F44",
            border_width=1,
            corner_radius=12,
            height=22,
            **kwargs
        )
        self.label_prefix = label
        self.value_text = value

        self.inner = ctk.CTkFrame(self, fg_color="transparent")
        self.inner.pack(padx=8, pady=1)

        # Dot
        self.dot = ctk.CTkLabel(
            self.inner,
            text="●",
            font=("Arial", 9),
            text_color=dot_color,
            width=10,
        )
        self.dot.pack(side="left", padx=(0, 4))

        # Text
        display = f"{label}: {value}" if label else value
        self.text_label = ctk.CTkLabel(
            self.inner,
            text=display,
            font=("Consolas", 9, "bold"),
            text_color=COLOR_SLATE_TEXT,
        )
        self.text_label.pack(side="left")

    def update_value(self, value: str, dot_color: str = None):
        self.value_text = str(value)
        display = f"{self.label_prefix}: {value}" if self.label_prefix else value
        self.text_label.configure(text=display)
        if dot_color:
            self.dot.configure(text_color=dot_color)
