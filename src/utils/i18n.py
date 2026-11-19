"""Simple UI translations: one JSON file per language."""
import json
import os

DEFAULT_LANGUAGE = "en"
LANGUAGE_NAMES = {
    "vi": "Tiếng Việt",
    "en": "English",
    "zh-CN": "简体中文",
}


def _locales_dir():
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "locales",
    )


class I18n:
    def __init__(self):
        self._language = DEFAULT_LANGUAGE
        self._strings = {}
        self._names = dict(LANGUAGE_NAMES)
        self._load(self._language)

    @property
    def language(self):
        return self._language

    def available(self):
        found = {}
        locales = _locales_dir()
        if os.path.isdir(locales):
            for name in os.listdir(locales):
                if not name.lower().endswith(".json"):
                    continue
                path = os.path.join(locales, name)
                code = os.path.splitext(name)[0]
                display = LANGUAGE_NAMES.get(code, code)
                try:
                    with open(path, "r", encoding="utf-8") as handle:
                        data = json.load(handle) or {}
                    code = str(data.get("code") or code).strip() or code
                    display = str(data.get("name") or display).strip() or display
                except Exception:
                    pass
                found[code] = display
        for code, display in LANGUAGE_NAMES.items():
            found.setdefault(code, display)
        order = ["vi", "en", "zh-CN"]
        items = [(code, found[code]) for code in order if code in found]
        items.extend(sorted((code, name) for code, name in found.items() if code not in order))
        return items

    def display_names(self):
        return [name for _code, name in self.available()]

    def code_for_name(self, name):
        wanted = str(name or "").strip()
        for code, display in self.available():
            if display == wanted or code == wanted:
                return code
        return DEFAULT_LANGUAGE

    def name_for_code(self, code=None):
        lang = self.normalize(code if code is not None else self._language)
        for item_code, display in self.available():
            if item_code == lang:
                return display
        return LANGUAGE_NAMES.get(lang, lang)

    def normalize(self, code):
        raw = str(code or "").strip().replace("_", "-")
        if not raw:
            return DEFAULT_LANGUAGE
        lowered = raw.lower()
        if lowered in ("en", "en-us", "english"):
            return "en"
        if lowered in ("zh", "zh-cn", "zh-hans", "cn", "chs", "simplified chinese", "简体中文"):
            return "zh-CN"
        for item_code, display in self.available():
            if item_code.lower() == lowered or display == raw:
                return item_code
        return DEFAULT_LANGUAGE

    def set_language(self, code):
        lang = self.normalize(code)
        self._language = lang
        self._load(lang)
        return lang

    def t(self, text, **kwargs):
        key = "" if text is None else str(text)
        if not key:
            return ""
        value = self._strings.get(key, key)
        if kwargs:
            try:
                value = str(value).format(**kwargs)
            except Exception:
                pass
        return value

    def heading(self, text):
        value = self.t(text)
        if self._language == "en":
            return str(value).upper()
        return value

    def _load(self, code):
        path = os.path.join(_locales_dir(), f"{code}.json")
        data = {}
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle) or {}
        except Exception:
            data = {}
        strings = data.get("strings", data) if isinstance(data, dict) else {}
        self._strings = strings if isinstance(strings, dict) else {}
        name = str(data.get("name") or LANGUAGE_NAMES.get(code) or code)
        self._names[code] = name


i18n = I18n()


def t(text, **kwargs):
    return i18n.t(text, **kwargs)


def heading(text):
    return i18n.heading(text)


# --- Tactical HUD string table -------------------------------------------------
# The HUD ships its own English source strings so a missing locale entry never
# blanks a label: `t_hud()` falls back to the default here instead of echoing the
# key. Locale files may override any of these keys under "strings".
HUD_STRINGS = {
    # Header / shell
    "HUD_COLORBOT": "COLORBOT",
    "HUD_FPS": "FPS",
    "HUD_PING": "PING",
    "HUD_HW": "HW",
    "HUD_SIMPLE": "Simple",
    "HUD_WIDE": "Wide",
    "HUD_MINIMIZE": "Minimize",
    "HUD_MAXIMIZE": "Maximize",
    "HUD_CLOSE": "Close",
    "HUD_ENGINE": "ENGINE",
    "HUD_PLATFORM": "PLATFORM",
    "HUD_SETTINGS": "Settings",
    "HUD_CFG": "CFG:",
    "HUD_START_ENGINE": "START ENGINE",
    "HUD_STOP_ENGINE": "STOP ENGINE",
    "HUD_STARTING": "STARTING...",
    "HUD_STOPPING": "STOPPING...",
    "HUD_READY": "READY",
    "HUD_RUNNING": "RUNNING",
    "HUD_STOPPED": "STOPPED",
    "HUD_HOTKEY": "HOTKEY",
    "HUD_UDP": "UDP",
    # Navigation
    "NAV_COMBAT": "Combat",
    "NAV_VISION": "Vision",
    "NAV_HARDWARE": "Hardware",
    "NAV_PROFILES": "Profiles",
    "NAV_TELEMETRY": "Telemetry",
    "NAV_COMBAT_SHORT": "Combat",
    "NAV_VISION_SHORT": "Vision",
    "NAV_HARDWARE_SHORT": "HW",
    "NAV_PROFILES_SHORT": "CFG",
    "NAV_TELEMETRY_SHORT": "LOG",
    # Page metadata
    "PAGE_COMBAT_TITLE": "Main Aimbot",
    "PAGE_COMBAT_SUB": "Aim behaviour, tracking quality and humanization",
    "PAGE_SEC_TITLE": "Secondary Aimbot",
    "PAGE_SEC_SUB": "Second aim profile with its own trigger and tuning",
    "PAGE_VISION_TITLE": "Vision & Color Detection",
    "PAGE_VISION_SUB": "Target color, HSV calibration and contour filtering",
    "PAGE_HARDWARE_TITLE": "Hardware & Capture Service",
    "PAGE_HARDWARE_SUB": "Device API, input backend and capture source",
    "PAGE_PROFILES_TITLE": "Configuration Profiles",
    "PAGE_PROFILES_SUB": "Config presets, import / export and clipboard sync",
    "PAGE_TELEMETRY_TITLE": "Debug & Telemetry",
    "PAGE_TELEMETRY_SUB": "Live capture health, input events and logs",
    # Combat strip
    "HUD_MAIN_AIMBOT": "Main Aimbot",
    "HUD_SEC_AIMBOT": "Sec Aimbot",
    "HUD_ENABLE_AIMBOT": "Enable Aimbot",
    "HUD_ENABLE_ANTISMOKE": "Enable Anti-Smoke",
    "HUD_SLOT_PRIMARY": "SLOT 1 // PRIMARY",
    "HUD_SLOT_SECONDARY": "SLOT 2 // SECONDARY",
    "HUD_SIMULATE_PATH": "Simulate WindMouse Path",
    "HUD_REROLL": "Re-Roll",
    # Vision
    "HUD_MASK_RADAR": "Live OpenCV Mask Radar (216x216)",
    "HUD_RAW_CAPTURE": "RAW CAPTURE + FOV",
    "HUD_HSV_MASK": "HSV INRANGE MASK",
    "HUD_LAUNCH_HSV": "Launch HSV Filter Preview",
    "HUD_FULL_PREVIEW": "Full Preview Window",
    "HUD_HSV_LOWER": "HSV Lower Bounds",
    "HUD_HSV_UPPER": "HSV Upper Bounds",
    "HUD_RANGE": "RANGE:",
    "HUD_NO_SIGNAL": "NO SIGNAL",
    # Hardware
    "HUD_TEST_MOVE": "TEST MOVE",
    "HUD_SWITCH_4M": "SWITCH TO 4M",
    "HUD_MOUSE_CONNECTION": "Mouse Connection",
    "HUD_KEYBOARD_CONNECTION": "Keyboard Connection",
    "HUD_CENTER_CROP": "Center Crop (FOV)",
    # Profiles / Telemetry
    "HUD_SAVE": "SAVE",
    "HUD_LOAD": "LOAD",
    "HUD_DEL": "DEL",
    "HUD_NEW": "NEW",
    "HUD_EXPORT": "EXPORT",
    "HUD_IMPORT": "IMPORT",
    "HUD_ADD": "Add",
    "HUD_PROFILE_NAME": "Profile name...",
    "HUD_ACTIVITY_LOG": "Activity Log",
    "HUD_DELTA": "Delta dX/dY",
    "HUD_BAUDRATE": "Baudrate",
    "HUD_STEP_TICK": "Step Tick",
    "HUD_LIVE_DEBUG": "Live Debug",
    "HUD_BUTTON_STATES": "Button States",
    "HUD_SYSTEM_LOGS": "System Logs",
    "HUD_CLEAR_LOG": "Clear Log",
    "HUD_OPEN_WEBMENU": "Open WebMenu",
    # Accents / themes
    "HUD_EMERALD": "Emerald",
    "HUD_CYAN": "Cyan",
    "HUD_AMBER": "Amber",
    "HUD_CRIMSON": "Crimson",
    "HUD_DARK": "Dark",
    "HUD_MIDNIGHT": "Midnight",
    "HUD_LANG_EN": "English",
    "HUD_LANG_VI": "Tiếng Việt",
    # Platform sub-nav
    "HUD_PLAT_HARDWARE": "Hardware & Capture",
    "HUD_PLAT_PROFILES": "Profiles & Config",
    "HUD_PLAT_TELEMETRY": "Debug & Telemetry",
}


def t_hud(key, default=None):
    """Translate a HUD key, falling back to the bundled English source string.

    Unlike `t()`, a key the locale file forgot does not leak into the UI; the
    English text declared in `HUD_STRINGS` (or `default`) is used instead.
    """
    value = i18n.t(key)
    if value != key:
        return value
    if default is not None:
        return str(default)
    return HUD_STRINGS.get(key, key)
