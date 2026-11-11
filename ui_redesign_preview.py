"""
CVM colorBot v2 — UI Redesign Preview (mock data, no engine).

Standalone design demo for approval. Run:
    venv\\Scripts\\python.exe ui_redesign_preview.py

Nothing here is wired to the tracker/capture services; every value is fake.
Once the layout is approved, the same widgets get ported into src/ui.py.
"""
import customtkinter as ctk
import tkinter as tk
import random
import math

# ────────────────────────────────  Design tokens  ────────────────────────────────
# Single source of truth. Cards/pills/rows all read from here, so a future theme
# switch only overrides this dict instead of hardcoding hex in every widget.
TOKENS = {
    "bg":            "#0A0D12",
    "bg_alt":        "#0E1219",
    "sidebar":       "#0B0F16",
    "surface":       "#121821",
    "surface_hi":    "#18202C",
    "border":        "#212B3A",
    "border_soft":   "#1A222E",
    "text":          "#E8EDF5",
    "text_dim":      "#8A99AD",
    "text_faint":    "#7A8798",
    "accent":        "#3DDC97",
    "accent_dim":    "#2A9E6C",
    "accent_soft":   "#12301F",
    "cyan":          "#4CC2FF",
    "cyan_soft":     "#10283A",
    "amber":         "#F2B441",
    "violet":        "#A78BFA",
    "rose":          "#F2545B",
}

F_LOGO = ("Consolas", 17, "bold")
F_H1 = ("Segoe UI Semibold", 19)
F_H2 = ("Segoe UI Semibold", 12)
F_LABEL = ("Segoe UI", 10)
F_SMALL = ("Segoe UI", 9)
F_TINY = ("Segoe UI", 8)
F_MONO = ("Consolas", 10)
F_MONO_B = ("Consolas", 10, "bold")
F_BIG_NUM = ("Consolas", 22, "bold")

NAV = [
    ("ENGINE", None),
    ("Combat", "\u25c9", "combat"),
    ("Vision", "\u25c8", "vision"),
    ("PLATFORM", None),
    ("Hardware", "\u26a1", "hardware"),
    ("Profiles", "\u25a4", "profiles"),
    ("Telemetry", "\u2248", "telemetry"),
]


# ────────────────────────────────  Reusable primitives  ────────────────────────────────
class Card(ctk.CTkFrame):
    """Panel with a section header + optional right badge."""

    def __init__(self, parent, title, badge=None, accent=None, **kw):
        super().__init__(parent, fg_color=TOKENS["surface"],
                         border_color=TOKENS["border"], border_width=1,
                         corner_radius=10, **kw)
        accent = accent or TOKENS["text_dim"]
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=14, pady=(11, 0))
        ctk.CTkLabel(head, text=title.upper(), font=("Segoe UI Semibold", 9),
                     text_color=TOKENS["text_dim"], anchor="w").pack(side="left")
        if badge:
            b = ctk.CTkLabel(head, text=badge, font=F_TINY, text_color=accent,
                             fg_color=TOKENS["surface_hi"], corner_radius=4,
                             padx=7, height=17)
            b.pack(side="right")
        ctk.CTkFrame(self, height=1, fg_color=TOKENS["border_soft"]).pack(
            fill="x", padx=14, pady=(8, 9))
        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.pack(fill="both", expand=True, padx=14, pady=(0, 12))


class SliderRow(ctk.CTkFrame):
    """Label + numeric box above a compact slider. One row = one config key."""

    def __init__(self, parent, label, value, lo, hi, suffix="", accent=None, step=1):
        super().__init__(parent, fg_color="transparent")
        self.lo, self.hi, self.step, self.suffix = lo, hi, step, suffix
        self.value = value
        accent = accent or TOKENS["accent"]

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x")
        ctk.CTkLabel(top, text=label, font=F_LABEL,
                     text_color=TOKENS["text"], anchor="w").pack(side="left")
        self.box = ctk.CTkLabel(top, text=self._fmt(value), font=F_MONO_B,
                                text_color=accent, fg_color=TOKENS["bg_alt"],
                                corner_radius=4, width=54, height=20)
        self.box.pack(side="right")

        self.sl = ctk.CTkSlider(self, from_=lo, to=hi, command=self._moved,
                                height=12, corner_radius=6,
                                progress_color=accent, button_color=accent,
                                button_hover_color=accent, fg_color="#1B2432",
                                border_width=0, button_length=10)
        self.sl.set(value)
        self.sl.pack(fill="x", pady=(3, 8))

    def _fmt(self, v):
        return f"{v:.2f}{self.suffix}" if self.step < 1 else f"{int(round(v))}{self.suffix}"

    def _moved(self, v):
        v = v if self.step < 1 else int(round(v))
        self.value = v
        self.box.configure(text=self._fmt(v))


def switch_row(parent, title, sub, on=True, accent=None):
    accent = accent or TOKENS["accent"]
    row = ctk.CTkFrame(parent, fg_color=TOKENS["bg_alt"], corner_radius=7,
                       border_width=1, border_color=TOKENS["border_soft"])
    inner = ctk.CTkFrame(row, fg_color="transparent")
    inner.pack(fill="x", padx=10, pady=7)
    txt = ctk.CTkFrame(inner, fg_color="transparent")
    txt.pack(side="left", fill="x", expand=True)
    ctk.CTkLabel(txt, text=title, font=F_LABEL, text_color=TOKENS["text"],
                 anchor="w").pack(fill="x")
    if sub:
        ctk.CTkLabel(txt, text=sub, font=F_TINY, text_color=TOKENS["text_faint"],
                     anchor="w").pack(fill="x")
    var = tk.BooleanVar(value=on)
    ctk.CTkSwitch(inner, text="", variable=var, width=40, height=20,
                  switch_width=36, switch_height=18, progress_color=accent,
                  button_color="#FFFFFF", button_hover_color="#FFFFFF",
                  fg_color="#273343").pack(side="right")
    return row


def select_row(parent, label, values, current):
    row = ctk.CTkFrame(parent, fg_color="transparent")
    ctk.CTkLabel(row, text=label, font=F_LABEL, text_color=TOKENS["text_dim"],
                 anchor="w").pack(side="left")
    menu = ctk.CTkOptionMenu(row, values=values, width=132, height=24,
                             font=F_SMALL, corner_radius=5,
                             fg_color=TOKENS["bg_alt"], button_color=TOKENS["surface_hi"],
                             button_hover_color=TOKENS["border"],
                             text_color=TOKENS["text"], dropdown_font=F_SMALL,
                             dropdown_fg_color=TOKENS["surface"],
                             dropdown_hover_color=TOKENS["surface_hi"])
    menu.set(current)
    menu.pack(side="right")
    return row


def pill(parent, label, value, dot):
    p = ctk.CTkFrame(parent, fg_color=TOKENS["surface"], corner_radius=11,
                     border_width=1, border_color=TOKENS["border"], height=24)
    inner = ctk.CTkFrame(p, fg_color="transparent")
    inner.pack(padx=9, pady=2)
    ctk.CTkLabel(inner, text="\u25cf", font=("Arial", 8), text_color=dot,
                 width=9).pack(side="left", padx=(0, 5))
    ctk.CTkLabel(inner, text=label, font=F_TINY, text_color=TOKENS["text_faint"]
                 ).pack(side="left", padx=(0, 5))
    ctk.CTkLabel(inner, text=value, font=F_MONO, text_color=TOKENS["text"]
                 ).pack(side="left")
    return p


class NavItem(ctk.CTkFrame):
    def __init__(self, parent, label, glyph, active=False, command=None):
        fg = TOKENS["accent_soft"] if active else "transparent"
        super().__init__(parent, fg_color=fg, corner_radius=7, height=34)
        self.active = active
        self.command = command
        self.bar = ctk.CTkFrame(self, width=2, height=16,
                                fg_color=TOKENS["accent"] if active else "transparent",
                                corner_radius=1)
        self.bar.pack(side="left", padx=(0, 0))
        self.row = ctk.CTkFrame(self, fg_color="transparent")
        self.row.pack(fill="both", expand=True, padx=(9, 8), pady=0)
        self.glyph = ctk.CTkLabel(self.row, text=glyph, font=("Segoe UI", 11),
                                  width=16, text_color=TOKENS["accent"] if active else TOKENS["text_faint"])
        self.glyph.pack(side="left")
        self.lbl = ctk.CTkLabel(self.row, text=label, font=("Segoe UI", 10, "bold" if active else "normal"),
                                text_color=TOKENS["text"] if active else TOKENS["text_dim"], anchor="w")
        self.lbl.pack(side="left", padx=(7, 0), fill="x", expand=True)
        for w in (self, self.row, self.glyph, self.lbl):
            w.bind("<Button-1>", self._click)

    def _click(self, _e=None):
        if self.command:
            self.command()


# ────────────────────────────────  App shell  ────────────────────────────────
class Preview(ctk.CTk):
    def __init__(self):
        super().__init__(fg_color=TOKENS["bg"])
        self.title("CVM colorBot — Redesign Preview")
        self.geometry("1180x740")
        self.minsize(1080, 680)
        ctk.set_appearance_mode("dark")

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._build_sidebar()
        self._build_main()
        self.show("combat")
        self._tick()

    # ── Sidebar ──
    def _build_sidebar(self):
        sb = ctk.CTkFrame(self, fg_color=TOKENS["sidebar"], corner_radius=0, width=206)
        sb.grid(row=0, column=0, sticky="nsw")
        # CTkFrame ignores grid_propagate(False); pack_propagate is the one that holds.
        sb.pack_propagate(False)
        ctk.CTkFrame(self, width=1, fg_color=TOKENS["border"]).place(x=205, y=0, relheight=1)

        head = ctk.CTkFrame(sb, fg_color="transparent")
        head.pack(fill="x", padx=16, pady=(16, 14))
        ctk.CTkLabel(head, text="CVM", font=F_LOGO, text_color=TOKENS["accent"]).pack(side="left")
        ctk.CTkLabel(head, text="colorBot", font=("Consolas", 10),
                     text_color=TOKENS["text_faint"]).pack(side="left", padx=(5, 0), pady=(4, 0))

        # Master runtime control
        self.run_btn = ctk.CTkButton(
            sb, text="\u25b6  START ENGINE", height=40, corner_radius=8,
            font=("Segoe UI Semibold", 11), fg_color=TOKENS["accent"],
            hover_color=TOKENS["accent_dim"], text_color="#04140C",
            command=self._toggle_run)
        self.run_btn.pack(fill="x", padx=14, pady=(0, 4))
        self.run_state = ctk.CTkLabel(sb, text="●  Idle \u00b7 engine stopped",
                                      font=F_TINY, text_color=TOKENS["text_faint"])
        self.run_state.pack(anchor="w", padx=18, pady=(0, 12))

        # Live telemetry strip
        tel = ctk.CTkFrame(sb, fg_color=TOKENS["surface"], corner_radius=8,
                           border_width=1, border_color=TOKENS["border"])
        tel.pack(fill="x", padx=14, pady=(0, 14))
        inner = ctk.CTkFrame(tel, fg_color="transparent")
        inner.pack(fill="x", padx=11, pady=9)
        ctk.CTkLabel(inner, text="LIVE", font=("Segoe UI Semibold", 8),
                     text_color=TOKENS["text_faint"]).pack(anchor="w")
        self.tel_fps = ctk.CTkLabel(inner, text="--", font=F_BIG_NUM,
                                    text_color=TOKENS["accent"])
        self.tel_fps.pack(anchor="w", pady=(1, 0))
        ctk.CTkLabel(inner, text="fps capture", font=F_TINY,
                     text_color=TOKENS["text_faint"]).pack(anchor="w")
        sep = ctk.CTkFrame(inner, height=1, fg_color=TOKENS["border_soft"])
        sep.pack(fill="x", pady=7)
        for k, v in (("Latency", "-- ms"), ("Hardware", "Serial")):
            r = ctk.CTkFrame(inner, fg_color="transparent")
            r.pack(fill="x")
            ctk.CTkLabel(r, text=k, font=F_TINY, text_color=TOKENS["text_faint"]).pack(side="left")
            lbl = ctk.CTkLabel(r, text=v, font=F_MONO, text_color=TOKENS["text"])
            lbl.pack(side="right")
            if k == "Latency":
                self.tel_lat = lbl
        self.hw_dot = ctk.CTkLabel(inner, text="● Serial 4M \u00b7 connected", font=F_TINY,
                                   text_color=TOKENS["accent"])
        self.hw_dot.pack(anchor="w", pady=(6, 0))

        # Navigation
        nav = ctk.CTkFrame(sb, fg_color="transparent")
        nav.pack(fill="both", expand=True, padx=10)
        self.nav_items = {}
        for item in NAV:
            if item[1] is None:
                ctk.CTkLabel(nav, text=item[0], font=("Segoe UI Semibold", 8),
                             text_color=TOKENS["text_faint"], anchor="w"
                             ).pack(fill="x", padx=8, pady=(12, 3))
                continue
            label, glyph, key = item
            it = NavItem(nav, label, glyph, command=lambda k=key: self.show(k))
            it.pack(fill="x", pady=1)
            self.nav_items[key] = it

        # Footer: profile + language
        foot = ctk.CTkFrame(sb, fg_color="transparent")
        foot.pack(side="bottom", fill="x", padx=14, pady=(0, 14))
        prof = ctk.CTkFrame(foot, fg_color=TOKENS["surface"], corner_radius=8,
                            border_width=1, border_color=TOKENS["border"])
        prof.pack(fill="x")
        pin = ctk.CTkFrame(prof, fg_color="transparent")
        pin.pack(fill="x", padx=10, pady=7)
        ctk.CTkLabel(pin, text="PROFILE", font=("Segoe UI Semibold", 8),
                     text_color=TOKENS["text_faint"]).pack(anchor="w")
        ctk.CTkLabel(pin, text="config.burst_spray", font=F_MONO,
                     text_color=TOKENS["text_dim"]).pack(anchor="w")
        row = ctk.CTkFrame(foot, fg_color="transparent")
        row.pack(fill="x", pady=(6, 0))
        for t in ("VI", "Nord", "Settings"):
            ctk.CTkButton(row, text=t, height=22, corner_radius=5, font=F_TINY,
                          fg_color=TOKENS["surface"], hover_color=TOKENS["surface_hi"],
                          text_color=TOKENS["text_dim"], border_width=1,
                          border_color=TOKENS["border"]).pack(side="left", expand=True,
                                                              fill="x", padx=(0, 4))

    # ── Main column: title bar + scroll body ──
    def _build_main(self):
        right = ctk.CTkFrame(self, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew")
        right.grid_rowconfigure(1, weight=1)
        right.grid_columnconfigure(0, weight=1)

        top = ctk.CTkFrame(right, fg_color=TOKENS["bg"], height=62, corner_radius=0)
        top.grid(row=0, column=0, sticky="ew")
        top.grid_propagate(False)

        left = ctk.CTkFrame(top, fg_color="transparent")
        left.pack(side="left", padx=22, pady=12)
        self.page_title = ctk.CTkLabel(left, text="Combat", font=F_H1,
                                       text_color=TOKENS["text"], anchor="w")
        self.page_title.pack(anchor="w")
        self.page_sub = ctk.CTkLabel(left, text="", font=F_SMALL,
                                     text_color=TOKENS["text_faint"], anchor="w")
        self.page_sub.pack(anchor="w")

        pills = ctk.CTkFrame(top, fg_color="transparent")
        pills.pack(side="right", padx=18)
        self.p_fps = pill(pills, "FPS", "144", TOKENS["accent"])
        self.p_fps.pack(side="left", padx=4)
        pill(pills, "DELAY", "6.4 ms", TOKENS["cyan"]).pack(side="left", padx=4)
        pill(pills, "TARGETS", "2", TOKENS["amber"]).pack(side="left", padx=4)
        ctk.CTkButton(pills, text="\u2014", width=28, height=24, font=F_SMALL,
                      fg_color="transparent", hover_color=TOKENS["surface_hi"],
                      text_color=TOKENS["text_dim"]).pack(side="left", padx=2)
        ctk.CTkButton(pills, text="\u2715", width=28, height=24, font=F_SMALL,
                      fg_color="transparent", hover_color=TOKENS["rose"],
                      text_color=TOKENS["text_dim"],
                      command=self.destroy).pack(side="left", padx=(2, 0))

        ctk.CTkFrame(right, height=1, fg_color=TOKENS["border_soft"]).grid(
            row=0, column=0, sticky="ews", pady=(61, 0))

        self.body = ctk.CTkScrollableFrame(right, fg_color="transparent",
                                           scrollbar_button_color=TOKENS["border"],
                                           scrollbar_button_hover_color=TOKENS["text_faint"])
        self.body.grid(row=1, column=0, sticky="nsew", padx=20, pady=(14, 16))
        self.body.grid_columnconfigure(0, weight=1, uniform="c")
        self.body.grid_columnconfigure(1, weight=1, uniform="c")

    # ── Routing ──
    def show(self, key):
        for k, it in self.nav_items.items():
            active = k == key
            it.configure(fg_color=TOKENS["accent_soft"] if active else "transparent")
            it.bar.configure(fg_color=TOKENS["accent"] if active else "transparent")
            it.glyph.configure(text_color=TOKENS["accent"] if active else TOKENS["text_faint"])
            it.lbl.configure(text_color=TOKENS["text"] if active else TOKENS["text_dim"],
                             font=("Segoe UI", 10, "bold" if active else "normal"))
        for w in self.body.winfo_children():
            w.destroy()
        meta = {
            "combat": ("Combat", "Aim behaviour, tracking quality and humanization"),
            "vision": ("Vision", "Target color, HSV calibration and contour filtering"),
            "hardware": ("Hardware", "Device API, input backend and capture source"),
            "profiles": ("Profiles", "Config presets, import / export and cloud sync"),
            "telemetry": ("Telemetry", "Live capture health, input events and logs"),
        }[key]
        self.page_title.configure(text=meta[0])
        self.page_sub.configure(text=meta[1])
        getattr(self, f"_page_{key}")()

    def _grid(self, widgets, start_row=0):
        """Place cards two-per-row, stretching. `widgets` = list of (card, col_span)."""
        r = start_row
        c = 0
        for w, span in widgets:
            if c + span > 2:
                r, c = r + 1, 0
            w.grid(row=r, column=c, columnspan=span, sticky="nsew",
                   padx=(0, 6) if c == 0 and span == 1 else (6, 0) if c == 1 else 0,
                   pady=(0, 12))
            c += span
            if c >= 2:
                r, c = r + 1, 0

    # ════════════════════════════ COMBAT ════════════════════════════
    def _page_combat(self):
        b = self.body

        # Status banner
        hero = ctk.CTkFrame(b, fg_color=TOKENS["surface"], corner_radius=10,
                            border_width=1, border_color=TOKENS["border"])
        hero.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        hi = ctk.CTkFrame(hero, fg_color="transparent")
        hi.pack(fill="x", padx=16, pady=12)
        ctk.CTkLabel(hi, text="\u25cf", font=("Arial", 12),
                     text_color=TOKENS["accent"]).pack(side="left", padx=(0, 8))
        ctk.CTkLabel(hi, text="WindMouse", font=("Segoe UI Semibold", 13),
                     text_color=TOKENS["text"]).pack(side="left")
        ctk.CTkLabel(hi, text="holding Side Mouse 4  \u00b7  FOV 300  \u00b7  head",
                     font=F_SMALL, text_color=TOKENS["text_faint"]
                     ).pack(side="left", padx=10)
        sw = ctk.CTkFrame(hi, fg_color="transparent")
        sw.pack(side="right")
        ctk.CTkLabel(sw, text="Aimbot on", font=F_SMALL,
                     text_color=TOKENS["text_dim"]).pack(side="left", padx=(0, 6))
        ctk.CTkSwitch(sw, text="", width=40, height=20, switch_width=36,
                      switch_height=18, progress_color=TOKENS["accent"],
                      button_color="#FFF", button_hover_color="#FFF",
                      fg_color="#273343").pack(side="left")

        # Card: targeting
        c1 = Card(b, "Targeting", badge="CORE", accent=TOKENS["accent"])
        for lab, vals, cur in (
            ("Aim mode", ["WindMouse", "Normal", "Flick", "Silent", "Bezier", "PID"], "WindMouse"),
            ("Target bone", ["head", "body", "nearest"], "head"),
            ("Activation", ["Hold to enable", "Toggle", "Press to enable"], "Hold to enable"),
        ):
            select_row(c1.body, lab, vals, cur).pack(fill="x", pady=3)
        bindrow = ctk.CTkFrame(c1.body, fg_color="transparent")
        bindrow.pack(fill="x", pady=3)
        ctk.CTkLabel(bindrow, text="Keybind", font=F_LABEL,
                     text_color=TOKENS["text_dim"]).pack(side="left")
        ctk.CTkButton(bindrow, text="Side Mouse 4", height=24, width=132, corner_radius=5,
                      font=F_MONO, fg_color=TOKENS["accent_soft"],
                      hover_color=TOKENS["surface_hi"], text_color=TOKENS["accent"],
                      border_width=1, border_color=TOKENS["accent_dim"]).pack(side="right")
        SliderRow(c1.body, "FOV radius", 300, 10, 800, " px").pack(fill="x")
        SliderRow(c1.body, "X offset", 1, -100, 100, "").pack(fill="x")
        SliderRow(c1.body, "Y offset", -3, -100, 100, "").pack(fill="x")

        # Card: algorithm
        c2 = Card(b, "WindMouse tuning", badge="ALGO", accent=TOKENS["cyan"])
        for lab, v, lo, hi, st, suf in (
            ("Gravity", 4.5, 0.1, 30, 0.1, ""),
            ("Wind", 2.0, 0.1, 20, 0.1, ""),
            ("Max step", 8, 1, 100, 1, ""),
            ("Smoothing", 10, 1, 30, 1, ""),
            ("FOV smoothing", 10, 1, 30, 1, ""),
        ):
            SliderRow(c2.body, lab, v, lo, hi, suf, accent=TOKENS["cyan"], step=st).pack(fill="x")

        # Card: speeds
        c3 = Card(b, "Speeds & recoil", badge="AXIS", accent=TOKENS["amber"])
        SliderRow(c3.body, "X speed", 100, 1, 2000, accent=TOKENS["amber"]).pack(fill="x")
        SliderRow(c3.body, "Y speed", 70, 1, 2000, accent=TOKENS["amber"]).pack(fill="x")
        switch_row(c3.body, "Recoil immunity", "Decouple vertical axis while spraying",
                   accent=TOKENS["amber"]).pack(fill="x", pady=(4, 8))
        io = ctk.CTkFrame(c3.body, fg_color="transparent")
        io.pack(fill="x")
        for lab, val in (("In-game sens", "0.235"), ("DPI", "1100")):
            ctk.CTkLabel(io, text=lab, font=F_LABEL,
                         text_color=TOKENS["text_dim"]).pack(side="left")
            ctk.CTkEntry(io, width=62, height=24, font=F_MONO, justify="center",
                         fg_color=TOKENS["bg_alt"], border_color=TOKENS["border"],
                         border_width=1, corner_radius=5).pack(side="left", padx=(6, 14))

        # Card: humanization
        c4 = Card(b, "Humanization", badge="SAFE", accent=TOKENS["violet"])
        SliderRow(c4.body, "Anti-tremor deadband", 1.5, 0, 5, accent=TOKENS["violet"],
                  step=0.1).pack(fill="x")
        SliderRow(c4.body, "Reaction min", 0.08, 0.01, 0.3, " s", accent=TOKENS["violet"],
                  step=0.01).pack(fill="x")
        SliderRow(c4.body, "Reaction max", 0.15, 0.05, 0.5, " s", accent=TOKENS["violet"],
                  step=0.01).pack(fill="x")
        switch_row(c4.body, "Audio feedback", "Beep through OBS on toggle",
                   accent=TOKENS["violet"]).pack(fill="x", pady=(4, 0))

        self._grid([(c1, 1), (c2, 1), (c3, 1), (c4, 1)], start_row=1)

    # ════════════════════════════ VISION ════════════════════════════
    def _page_vision(self):
        b = self.body
        c1 = Card(b, "Target color", badge="PRESET", accent=TOKENS["accent"])
        row = ctk.CTkFrame(c1.body, fg_color="transparent")
        row.pack(fill="x", pady=(0, 8))
        for name, hexc, on in (("Yellow", "#E7C84B", False), ("Purple", "#A345F5", True),
                               ("Red", "#E2453F", False), ("Custom", "#5A6678", False)):
            chip = ctk.CTkFrame(row, fg_color=TOKENS["accent_soft"] if on else TOKENS["bg_alt"],
                                corner_radius=6, border_width=1,
                                border_color=TOKENS["accent"] if on else TOKENS["border"])
            chip.pack(side="left", expand=True, fill="x", padx=(0, 6))
            ci = ctk.CTkFrame(chip, fg_color="transparent")
            ci.pack(padx=8, pady=7)
            ctk.CTkFrame(ci, width=12, height=12, corner_radius=3,
                         fg_color=hexc).pack(side="left", padx=(0, 6))
            ctk.CTkLabel(ci, text=name, font=F_SMALL,
                         text_color=TOKENS["accent"] if on else TOKENS["text_dim"]).pack(side="left")
        ctk.CTkButton(c1.body, text="Launch HSV filter preview", height=32, corner_radius=6,
                      font=F_LABEL, fg_color=TOKENS["surface_hi"],
                      hover_color=TOKENS["border"], text_color=TOKENS["cyan"],
                      border_width=1, border_color=TOKENS["border"]).pack(fill="x")

        c2 = Card(b, "HSV range", badge="CALIBRATION", accent=TOKENS["cyan"])
        hdr = ctk.CTkFrame(c2.body, fg_color="transparent")
        hdr.pack(fill="x", pady=(0, 6))
        for lab, val, col in (("H", "120 \u2013 160", TOKENS["rose"]),
                              ("S", "135 \u2013 255", TOKENS["amber"]),
                              ("V", "115 \u2013 255", TOKENS["cyan"])):
            chip = ctk.CTkFrame(hdr, fg_color=TOKENS["bg_alt"], corner_radius=5)
            chip.pack(side="left", expand=True, fill="x", padx=(0, 6))
            ci = ctk.CTkFrame(chip, fg_color="transparent")
            ci.pack(padx=7, pady=5)
            ctk.CTkLabel(ci, text=lab, font=("Consolas", 9, "bold"),
                         text_color=col).pack(side="left", padx=(0, 6))
            ctk.CTkLabel(ci, text=val, font=F_MONO, text_color=TOKENS["text"]).pack(side="left")
        for lab, v, lo, hi, col in (
            ("Hue min", 120, 0, 179, TOKENS["rose"]), ("Hue max", 160, 0, 179, TOKENS["rose"]),
            ("Sat min", 135, 0, 255, TOKENS["amber"]), ("Val min", 115, 0, 255, TOKENS["cyan"]),
        ):
            SliderRow(c2.body, lab, v, lo, hi, accent=col).pack(fill="x")

        c3 = Card(b, "Contour filters", badge="PRO", accent=TOKENS["amber"])
        for lab, v, lo, hi in (("Merge distance", 250, 50, 500),
                               ("Min contour points", 30, 3, 100),
                               ("Min box area", 90, 10, 400),
                               ("Fill ratio", 0.16, 0.01, 1.0)):
            step = 0.01 if v < 1 else 1
            SliderRow(c3.body, lab, v, lo, hi, accent=TOKENS["amber"], step=step).pack(fill="x")
        switch_row(c3.body, "Require vertical line", "Reject blobs without a spine",
                   accent=TOKENS["amber"]).pack(fill="x", pady=(4, 0))

        c4 = Card(b, "Mask preview", badge="LIVE", accent=TOKENS["accent"])
        prev = ctk.CTkFrame(c4.body, fg_color=TOKENS["bg_alt"], corner_radius=7,
                            height=150, border_width=1, border_color=TOKENS["border_soft"])
        prev.pack(fill="both", expand=True)
        prev.pack_propagate(False)
        cv = tk.Canvas(prev, bg="#0B1120", highlightthickness=0)
        cv.pack(fill="both", expand=True, padx=1, pady=1)
        cv.bind("<Configure>", lambda e: self._draw_mask(cv))
        ctk.CTkLabel(c4.body, text="2 targets detected \u00b7 mask 12.4%",
                     font=F_TINY, text_color=TOKENS["text_faint"]).pack(anchor="w", pady=(7, 0))

        self._grid([(c1, 1), (c2, 1), (c3, 1), (c4, 1)])

    def _draw_mask(self, cv):
        cv.delete("all")
        w, h = cv.winfo_width(), cv.winfo_height()
        if w < 20 or h < 20:
            return
        for vx in range(0, w, 24):
            cv.create_line(vx, 0, vx, h, fill="#12203A")
        for vy in range(0, h, 24):
            cv.create_line(0, vy, w, vy, fill="#12203A")
        rnd = random.Random(7)
        for cx, cy in ((w * 0.38, h * 0.62), (w * 0.68, h * 0.42)):
            for _ in range(46):
                px = cx + rnd.gauss(0, w * 0.055)
                py = cy + rnd.gauss(0, h * 0.12)
                cv.create_rectangle(px, py, px + 3, py + 3, fill="#C084FC", outline="")
            cv.create_rectangle(cx - w * 0.055, cy - h * 0.13, cx + w * 0.055, cy + h * 0.13,
                                outline=TOKENS["accent"], width=1)
            cv.create_line(cx - 5, cy, cx + 5, cy, fill=TOKENS["accent"])
            cv.create_line(cx, cy - 5, cx, cy + 5, fill=TOKENS["accent"])
        mx, my = w * 0.5, h * 0.5
        cv.create_oval(mx - 26, my - 26, mx + 26, my + 26, outline="#2B3B52")
        cv.create_oval(mx - 2, my - 2, mx + 2, my + 2, fill="#4A5A72", outline="")

    # ════════════════════════════ HARDWARE ════════════════════════════
    def _page_hardware(self):
        b = self.body
        c1 = Card(b, "Device API", badge="SERIAL 4M", accent=TOKENS["accent"])
        head = ctk.CTkFrame(c1.body, fg_color=TOKENS["bg_alt"], corner_radius=7,
                            border_width=1, border_color=TOKENS["border_soft"])
        head.pack(fill="x", pady=(0, 8))
        hi = ctk.CTkFrame(head, fg_color="transparent")
        hi.pack(fill="x", padx=10, pady=8)
        ctk.CTkLabel(hi, text="\u25cf", font=("Arial", 11),
                     text_color=TOKENS["accent"]).pack(side="left", padx=(0, 7))
        ctk.CTkLabel(hi, text="Connected \u00b7 COM3 @ 4000000", font=F_LABEL,
                     text_color=TOKENS["text"]).pack(side="left")
        ctk.CTkButton(hi, text="Disconnect", width=88, height=22, corner_radius=5,
                      font=F_TINY, fg_color=TOKENS["surface_hi"],
                      hover_color=TOKENS["border"], text_color=TOKENS["text_dim"]
                      ).pack(side="right")
        for lab, vals, cur in (
            ("Mouse API", ["Serial (Makcu)", "Net", "KmboxA", "MAK API", "Ferrum", "SendInput"], "Serial (Makcu)"),
            ("Serial port", ["Auto", "COM3", "COM5"], "Auto"),
            ("Baudrate", ["4000000", "115200"], "4000000"),
        ):
            select_row(c1.body, lab, vals, cur).pack(fill="x", pady=3)
        switch_row(c1.body, "Auto-connect on launch", None).pack(fill="x", pady=(6, 6))
        ctk.CTkButton(c1.body, text="Test mouse move", height=30, corner_radius=6,
                      font=F_LABEL, fg_color=TOKENS["surface_hi"],
                      hover_color=TOKENS["border"], text_color=TOKENS["accent"]
                      ).pack(fill="x")

        c2 = Card(b, "Keyboard backend", badge="OFF", accent=TOKENS["cyan"])
        switch_row(c2.body, "Use separate keyboard API",
                   "Follows mouse API when disabled",
                   on=False, accent=TOKENS["cyan"]).pack(fill="x", pady=(0, 8))
        for lab, vals, cur in (
            ("Keyboard API", ["Follow Mouse API", "SendInput", "Ferrum"], "Follow Mouse API"),
            ("Baudrate", ["115200", "9600"], "115200"),
        ):
            select_row(c2.body, lab, vals, cur).pack(fill="x", pady=3)

        c3 = Card(b, "Capture source", badge="NDI", accent=TOKENS["amber"])
        for lab, vals, cur in (
            ("Method", ["NDI", "OBS UDP", "Capture Card", "Teleport", "MSS"], "NDI"),
            ("Resolution", ["1920 x 1080", "2560 x 1440"], "1920 x 1080"),
            ("FPS limit", ["144", "240", "Unlimited"], "144"),
        ):
            select_row(c3.body, lab, vals, cur).pack(fill="x", pady=3)
        info = ctk.CTkFrame(c3.body, fg_color=TOKENS["bg_alt"], corner_radius=6)
        info.pack(fill="x", pady=(8, 0))
        ii = ctk.CTkFrame(info, fg_color="transparent")
        ii.pack(fill="x", padx=10, pady=7)
        for k, v in (("Source", "OBS-Desktop"), ("Decode", "1.8 ms"), ("Drop rate", "0.0%")):
            r = ctk.CTkFrame(ii, fg_color="transparent")
            r.pack(fill="x")
            ctk.CTkLabel(r, text=k, font=F_TINY, text_color=TOKENS["text_faint"]).pack(side="left")
            ctk.CTkLabel(r, text=v, font=F_MONO, text_color=TOKENS["text"]).pack(side="right")

        c4 = Card(b, "Screen region", badge="FOV", accent=TOKENS["violet"])
        for lab, v, lo, hi in (("Region X", 320, 0, 1920), ("Region Y", 180, 0, 1080),
                               ("Width", 1280, 10, 1920), ("Height", 720, 10, 1080)):
            SliderRow(c4.body, lab, v, lo, hi, accent=TOKENS["violet"]).pack(fill="x")
        switch_row(c4.body, "Centre on screen", "Auto-recenter when resolution changes",
                   accent=TOKENS["violet"]).pack(fill="x", pady=(4, 0))

        self._grid([(c1, 1), (c2, 1), (c3, 1), (c4, 1)])

    # ════════════════════════════ PROFILES ════════════════════════════
    def _page_profiles(self):
        b = self.body
        c1 = Card(b, "Saved profiles", badge="4", accent=TOKENS["accent"])
        lst = ctk.CTkScrollableFrame(c1.body, fg_color="transparent", height=260,
                                     scrollbar_button_color=TOKENS["border"])
        lst.pack(fill="both", expand=True)
        for name, meta, on in (
            ("config.burst_spray", "Edited 2 min ago \u00b7 128 keys", True),
            ("config.rifle", "Edited yesterday", False),
            ("config.smg_aggressive", "Edited 3 days ago", False),
            ("config.safe_test", "Edited 2026-10-28", False),
        ):
            r = ctk.CTkFrame(lst, fg_color=TOKENS["accent_soft"] if on else TOKENS["bg_alt"],
                             corner_radius=7, border_width=1,
                             border_color=TOKENS["accent_dim"] if on else TOKENS["border_soft"])
            r.pack(fill="x", pady=3)
            ri = ctk.CTkFrame(r, fg_color="transparent")
            ri.pack(fill="x", padx=10, pady=7)
            ctk.CTkLabel(ri, text="\u25cf", font=("Arial", 9),
                         text_color=TOKENS["accent"] if on else TOKENS["text_faint"]
                         ).pack(side="left", padx=(0, 8))
            tcol = ctk.CTkFrame(ri, fg_color="transparent")
            tcol.pack(side="left", fill="x", expand=True)
            ctk.CTkLabel(tcol, text=name, font=F_MONO,
                         text_color=TOKENS["text"] if on else TOKENS["text_dim"],
                         anchor="w").pack(fill="x")
            ctk.CTkLabel(tcol, text=meta, font=F_TINY, text_color=TOKENS["text_faint"],
                         anchor="w").pack(fill="x")
            if on:
                ctk.CTkLabel(ri, text="ACTIVE", font=("Segoe UI Semibold", 8),
                             text_color=TOKENS["accent"], fg_color=TOKENS["surface"],
                             corner_radius=4, padx=6, height=16).pack(side="right")

        c2 = Card(b, "Actions", badge=None, accent=TOKENS["cyan"])
        for text, col, sub in (
            ("Save current", TOKENS["accent"], "Overwrite the active profile"),
            ("Save as new", TOKENS["cyan"], "Create a new profile file"),
            ("Import from file", TOKENS["amber"], "JSON dragged from disk"),
            ("Export to file", TOKENS["violet"], "Share with another machine"),
            ("Delete", TOKENS["rose"], "Removes the selected profile"),
        ):
            btn = ctk.CTkFrame(c2.body, fg_color=TOKENS["bg_alt"], corner_radius=7,
                               border_width=1, border_color=TOKENS["border_soft"])
            btn.pack(fill="x", pady=3)
            bi = ctk.CTkFrame(btn, fg_color="transparent")
            bi.pack(fill="x", padx=10, pady=7)
            ctk.CTkLabel(bi, text="\u25b8", font=("Arial", 9), text_color=col
                         ).pack(side="left", padx=(0, 8))
            tc = ctk.CTkFrame(bi, fg_color="transparent")
            tc.pack(side="left", fill="x", expand=True)
            ctk.CTkLabel(tc, text=text, font=F_LABEL, text_color=TOKENS["text"],
                         anchor="w").pack(fill="x")
            ctk.CTkLabel(tc, text=sub, font=F_TINY, text_color=TOKENS["text_faint"],
                         anchor="w").pack(fill="x")

        c3 = Card(b, "Activity", badge="LOG", accent=TOKENS["amber"])
        log = ctk.CTkTextbox(c3.body, height=200, fg_color=TOKENS["bg_alt"],
                             text_color=TOKENS["text_dim"], font=("Consolas", 9),
                             corner_radius=6, border_width=0)
        log.pack(fill="both", expand=True)
        log.insert("1.0",
                   "12:04:11  loaded config.burst_spray.json\n"
                   "12:04:11  applied 128 keys\n"
                   "12:06:03  saved config.burst_spray.json\n"
                   "12:09:40  exported to rifle_251109.json\n"
                   "12:11:02  imported from clipboard (signature 8f2c)\n")
        log.configure(state="disabled")

        c4 = Card(b, "Clipboard import", badge="AUTO", accent=TOKENS["violet"])
        switch_row(c4.body, "Watch clipboard",
                   "Prompt when a config signature is copied",
                   accent=TOKENS["violet"]).pack(fill="x", pady=(0, 8))
        card = ctk.CTkFrame(c4.body, fg_color=TOKENS["bg_alt"], corner_radius=7,
                            border_width=1, border_color=TOKENS["border_soft"])
        card.pack(fill="x")
        ci = ctk.CTkFrame(card, fg_color="transparent")
        ci.pack(fill="x", padx=10, pady=9)
        ctk.CTkLabel(ci, text="Config detected in clipboard", font=F_LABEL,
                     text_color=TOKENS["text"], anchor="w").pack(fill="x")
        ctk.CTkLabel(ci, text="signature 8f2c \u00b7 128 keys \u00b7 v1.2.1",
                     font=F_TINY, text_color=TOKENS["text_faint"], anchor="w").pack(fill="x")
        brow = ctk.CTkFrame(ci, fg_color="transparent")
        brow.pack(fill="x", pady=(8, 0))
        ctk.CTkButton(brow, text="Import", height=26, corner_radius=5, font=F_SMALL,
                      fg_color=TOKENS["accent"], hover_color=TOKENS["accent_dim"],
                      text_color="#04140C", width=88).pack(side="left", padx=(0, 6))
        ctk.CTkButton(brow, text="Dismiss", height=26, corner_radius=5, font=F_SMALL,
                      fg_color=TOKENS["surface_hi"], hover_color=TOKENS["border"],
                      text_color=TOKENS["text_dim"], width=88).pack(side="left")

        self._grid([(c1, 1), (c2, 1), (c3, 1), (c4, 1)])

    # ════════════════════════════ TELEMETRY ════════════════════════════
    def _page_telemetry(self):
        b = self.body

        strip = ctk.CTkFrame(b, fg_color="transparent")
        strip.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        for i, (lab, val, sub, col) in enumerate((
            ("CAPTURE FPS", "144", "target 144", TOKENS["accent"]),
            ("DECODE", "1.8", "ms", TOKENS["cyan"]),
            ("TOTAL DELAY", "6.4", "ms", TOKENS["amber"]),
            ("DROPPED", "0.0", "%", TOKENS["violet"]),
        )):
            k = ctk.CTkFrame(strip, fg_color=TOKENS["surface"], corner_radius=9,
                             border_width=1, border_color=TOKENS["border"])
            k.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 6, 0))
            strip.grid_columnconfigure(i, weight=1, uniform="k")
            ki = ctk.CTkFrame(k, fg_color="transparent")
            ki.pack(fill="x", padx=13, pady=10)
            ctk.CTkLabel(ki, text=lab, font=("Segoe UI Semibold", 8),
                         text_color=TOKENS["text_faint"]).pack(anchor="w")
            vr = ctk.CTkFrame(ki, fg_color="transparent")
            vr.pack(anchor="w")
            ctk.CTkLabel(vr, text=val, font=F_BIG_NUM, text_color=col).pack(side="left")
            ctk.CTkLabel(vr, text=f"  {sub}", font=F_TINY,
                         text_color=TOKENS["text_faint"]).pack(side="left", pady=(6, 0))
            bar = ctk.CTkProgressBar(ki, height=3, corner_radius=2,
                                     progress_color=col, fg_color="#1B2432")
            bar.set(0.62 + i * 0.08)
            bar.pack(fill="x", pady=(7, 0))

        c1 = Card(b, "Frame time", badge="60 s", accent=TOKENS["cyan"])
        cv = tk.Canvas(c1.body, bg=TOKENS["bg_alt"], highlightthickness=0, height=140)
        cv.pack(fill="both", expand=True)
        cv.bind("<Configure>", lambda e: self._draw_graph(cv))

        c2 = Card(b, "Input events", badge="MOUSE", accent=TOKENS["accent"])
        for name, pressed, cnt in (("Left", False, 312), ("Right", True, 1042),
                                   ("Middle", False, 7), ("Side 4", True, 2881),
                                   ("Side 5", False, 44)):
            r = ctk.CTkFrame(c2.body, fg_color="transparent")
            r.pack(fill="x", pady=2)
            ctk.CTkLabel(r, text="\u25cf", font=("Arial", 10),
                         text_color=TOKENS["accent"] if pressed else TOKENS["text_faint"],
                         width=14).pack(side="left")
            ctk.CTkLabel(r, text=name, font=F_LABEL, text_color=TOKENS["text_dim"],
                         width=56, anchor="w").pack(side="left")
            bar = ctk.CTkProgressBar(r, height=6, corner_radius=3,
                                     progress_color=TOKENS["accent"] if pressed else "#2B3B52",
                                     fg_color="#1B2432")
            bar.set(min(1.0, cnt / 3000))
            bar.pack(side="left", fill="x", expand=True, padx=8)
            ctk.CTkLabel(r, text=str(cnt), font=F_MONO, text_color=TOKENS["text"],
                         width=48, anchor="e").pack(side="right")
        c3 = Card(b, "Engine log", badge="STREAM", accent=TOKENS["amber"])
        ctrl = ctk.CTkFrame(c3.body, fg_color="transparent")
        ctrl.pack(fill="x", pady=(0, 6))
        for txt, col in (("Copy", TOKENS["text_dim"]), ("Clear", TOKENS["text_dim"]),
                         ("Open WebMenu", TOKENS["accent"])):
            ctk.CTkButton(ctrl, text=txt, height=24, corner_radius=5, font=F_TINY,
                          width=len(txt) * 7 + 16, fg_color=TOKENS["surface_hi"],
                          hover_color=TOKENS["border"], text_color=col
                          ).pack(side="left", padx=(0, 6))
        log = ctk.CTkTextbox(c3.body, height=220, fg_color=TOKENS["bg_alt"],
                             text_color=TOKENS["text_dim"], font=("Consolas", 9),
                             corner_radius=6, border_width=0)
        log.pack(fill="both", expand=True)
        log.insert("1.0",
                   "[12:11:02] engine start requested\n"
                   "[12:11:02] hardware: serial COM3 @ 4000000 ok\n"
                   "[12:11:03] capture: NDI source 'OBS-Desktop' attached\n"
                   "[12:11:03] detection: 144 fps, avg decode 1.8 ms\n"
                   "[12:11:07] aim: target locked (head) dist 128 px\n"
                   "[12:11:09] aim: target lost, reacquiring\n"
                   "[12:11:12] trigger: no target in ROI\n")
        log.configure(state="disabled")

        c4 = Card(b, "System", badge="BUILD", accent=TOKENS["violet"])
        for k, v, col in (("Version", "v1.2.1", TOKENS["text"]),
                          ("Python", "3.11.9", TOKENS["text"]),
                          ("customtkinter", "5.2.2", TOKENS["text"]),
                          ("Update", "Up to date", TOKENS["accent"]),
                          ("Theme", "Nord \u00b7 modern", TOKENS["text_dim"])):
            r = ctk.CTkFrame(c4.body, fg_color="transparent")
            r.pack(fill="x", pady=3)
            ctk.CTkLabel(r, text=k, font=F_LABEL, text_color=TOKENS["text_faint"]
                         ).pack(side="left")
            ctk.CTkLabel(r, text=v, font=F_MONO, text_color=col).pack(side="right")
        ctk.CTkButton(c4.body, text="Check for updates", height=30, corner_radius=6,
                      font=F_LABEL, fg_color=TOKENS["surface_hi"],
                      hover_color=TOKENS["border"], text_color=TOKENS["violet"]
                      ).pack(fill="x", pady=(8, 0))

        self._grid([(c1, 1), (c2, 1), (c3, 1), (c4, 1)], start_row=1)

    def _draw_graph(self, cv):
        cv.delete("all")
        w, h = cv.winfo_width(), cv.winfo_height()
        if w < 20 or h < 20:
            return
        pad = 10
        for gy in range(0, h, 28):
            cv.create_line(0, gy, w, gy, fill="#151F2C")
        rnd = random.Random(3)
        pts, target = [], h * 0.45
        y = target
        for i in range(w):
            y += rnd.gauss(0, 1.6) + (target - y) * 0.08
            pts += [i, max(pad, min(h - pad, y))]
        cv.create_line(*pts, fill=TOKENS["cyan"], width=2, smooth=True)
        cv.create_line(0, target, w, target, fill="#2B3B52", dash=(3, 4))
        cv.create_text(8, 10, text="6.4 ms avg   \u00b7   max 11.2 ms", anchor="w",
                       fill=TOKENS["text_faint"], font=("Consolas", 8))

    # ── fake live values ──
    def _tick(self):
        fps = 138 + random.randint(0, 7)
        self.tel_fps.configure(text=str(fps))
        self.tel_lat.configure(text=f"{random.uniform(5.8, 7.4):.1f} ms")
        self.after(1200, self._tick)

    def _toggle_run(self):
        running = self.run_btn.cget("text").startswith("\u25a0")
        ctk.CTkButton.configure(
            self.run_btn,
            text="\u25a0  STOP ENGINE" if not running else "\u25b6  START ENGINE",
            fg_color=TOKENS["rose"] if not running else TOKENS["accent"],
            hover_color="#C43F45" if not running else TOKENS["accent_dim"],
        )
        self.run_state.configure(
            text="●  Running \u00b7 WindMouse active" if not running else "●  Idle \u00b7 engine stopped",
            text_color=TOKENS["accent"] if not running else TOKENS["text_faint"],
        )


if __name__ == "__main__":
    ctk.set_appearance_mode("dark")
    Preview().mainloop()
