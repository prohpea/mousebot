"""
version — the ONE source of truth for the application version.

Before this module the version string was duplicated in ``version.json``, the
window title, the title-bar label, a card badge, the AppUserModelID, README and
CHANGELOG. Six places, four of which could drift independently. Everything now
reads :func:`load_version_info`.

Design rules (plan section 6.1):

* stdlib only — no ``customtkinter``, no ``src.ui``, no network. Importing this
  module must never initialise Tk or the updater.
* the JSON file is cached by ``(mtime, size)`` so a release that rewrites the
  file is picked up without a restart, and the hot paths (title, badge) do not
  re-read the disk.
* any parse/validation failure falls back to :data:`VERSION_FALLBACK` and logs
  exactly once, so a corrupt ``version.json`` cannot stop the app from starting.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Optional

#: Used when ``version.json`` is missing, unreadable or invalid.
VERSION_FALLBACK = "2.1.0"
CODENAME_FALLBACK = "Flick V2"
RELEASE_DATE_FALLBACK = "2026-11-09"
SCHEMA_FALLBACK = 3
CHANGELOG_FALLBACK = (
    "v2.1.0 — Flick V2 Complete UI & Valorant Calibration\n\n"
    "- Flick V2 tab with Gain, Settle Delay, Max Counts, Budget, Iterations, "
    "Deadzone and Switch Radius for Main and Sec.\n"
    "- Valorant calibration preset (0.07 deg/count at sens 1.0) with provenance.\n"
    "- Performance: preview throttling, calibration cache, per-tag move queue.\n"
    "- Fixes: calibration impulse isolation, flick rollback timing, settle/budget "
    "validation, duplicate config load."
)

#: ``2.1.0`` with an optional pre-release/build suffix.
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.\-]+)?$")


def project_root() -> str:
    """Absolute path of the repository/project root (parent of ``src``)."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def version_file_path() -> str:
    """Absolute path of ``version.json`` at the project root."""
    return os.path.join(project_root(), "version.json")


@dataclass(frozen=True)
class VersionInfo:
    """Immutable snapshot of ``version.json``."""

    version: str = VERSION_FALLBACK
    release_date: str = RELEASE_DATE_FALLBACK
    codename: str = CODENAME_FALLBACK
    schema: int = SCHEMA_FALLBACK
    changelog: str = CHANGELOG_FALLBACK

    # -- derived labels -----------------------------------------------------
    def label(self) -> str:
        """``"v2.1.0 PRO"`` — the title-bar label."""
        return f"v{self.version} PRO"

    def badge(self) -> str:
        """``"v2.1.0 · Flick V2"`` — the engine badge."""
        if self.codename:
            return f"v{self.version} \u00b7 {self.codename}"
        return f"v{self.version}"

    def title(self) -> str:
        """``"CVM colorBot v2.1.0 PRO"`` — the window title."""
        return f"CVM colorBot {self.label()}"

    def summary(self) -> str:
        """``"v2.1.0 (Flick V2)"`` — the startup print."""
        if self.codename:
            return f"v{self.version} ({self.codename})"
        return f"v{self.version}"

    def as_dict(self) -> dict:
        return {
            "version": self.version,
            "release_date": self.release_date,
            "codename": self.codename,
            "schema": self.schema,
            "changelog": self.changelog,
        }


def _fallback() -> VersionInfo:
    return VersionInfo()


def _coerce_text(value: Any, default: str) -> str:
    text = str(value if value is not None else "").strip()
    return text or default


def _coerce_schema(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return int(default)
    return parsed if parsed > 0 else int(default)


def parse_version_payload(data: Any) -> VersionInfo:
    """Validate a decoded ``version.json`` payload into a :class:`VersionInfo`.

    Raises ``ValueError`` when the payload is not a mapping with a semver
    ``version`` field; callers fall back to :func:`_fallback` on error.
    """
    if not isinstance(data, dict):
        raise ValueError("version payload is not an object")
    version = str(data.get("version") or "").strip()
    if not _SEMVER_RE.match(version):
        raise ValueError(f"invalid semver in version.json: {version!r}")
    return VersionInfo(
        version=version,
        release_date=_coerce_text(data.get("release_date"), RELEASE_DATE_FALLBACK),
        codename=_coerce_text(data.get("codename"), CODENAME_FALLBACK),
        schema=_coerce_schema(data.get("schema"), SCHEMA_FALLBACK),
        changelog=_coerce_text(data.get("changelog"), CHANGELOG_FALLBACK),
    )


#: ``(mtime, size)`` of the file the cached info was built from.
_CACHE_KEY: Optional[tuple] = None
_CACHE_INFO: Optional[VersionInfo] = None
_WARNED = False


def _warn_once(message: str) -> None:
    global _WARNED
    if _WARNED:
        return
    _WARNED = True
    try:
        from src.utils.debug_logger import log_print

        log_print(f"[Version] {message}")
    except Exception:
        pass


def load_version_info(refresh: bool = False) -> VersionInfo:
    """Return the cached :class:`VersionInfo`, re-reading the file when it changed.

    ``refresh=True`` forces a disk read (used by tests and the update dialog).
    """
    global _CACHE_KEY, _CACHE_INFO

    path = version_file_path()
    try:
        stat = os.stat(path)
        key = (int(stat.st_mtime_ns), int(stat.st_size))
    except OSError:
        # Missing file: return the fallback but do not poison the cache, so a
        # file created later is picked up.
        _warn_once(f"{path} not found; using built-in {VERSION_FALLBACK}.")
        return _CACHE_INFO if _CACHE_INFO is not None else _fallback()

    if not refresh and _CACHE_INFO is not None and _CACHE_KEY == key:
        return _CACHE_INFO

    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        info = parse_version_payload(payload)
    except Exception as exc:  # noqa: BLE001 - never raise to the UI
        _warn_once(f"failed to read {path}: {exc}; using built-in {VERSION_FALLBACK}.")
        if _CACHE_INFO is not None:
            return _CACHE_INFO
        return _fallback()

    _CACHE_KEY = key
    _CACHE_INFO = info
    return info


def reset_cache() -> None:
    """Drop the cached info (tests / release tooling)."""
    global _CACHE_KEY, _CACHE_INFO, _WARNED
    _CACHE_KEY = None
    _CACHE_INFO = None
    _WARNED = False


# ---------------------------------------------------------------------------
# Small accessors used by the UI / updater / main
# ---------------------------------------------------------------------------


def get_version() -> str:
    return load_version_info().version


def get_codename() -> str:
    return load_version_info().codename


def get_release_date() -> str:
    return load_version_info().release_date


def get_schema() -> int:
    return load_version_info().schema


def get_version_label() -> str:
    """``"v2.1.0 PRO"``."""
    return load_version_info().label()


def get_engine_badge() -> str:
    """``"v2.1.0 · Flick V2"``."""
    return load_version_info().badge()


def get_window_title() -> str:
    """``"CVM colorBot v2.1.0 PRO"``."""
    return load_version_info().title()


def get_version_summary() -> str:
    """``"v2.1.0 (Flick V2)"``."""
    return load_version_info().summary()


def get_changelog() -> str:
    return load_version_info().changelog
