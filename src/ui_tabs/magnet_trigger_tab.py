"""
magnet_trigger_tab — RETIRED in v2.1.0.

The Magnet Trigger UI was never reachable: ``ViewerApp._show_magnet_trigger_tab``
redirected to Combat before any of this module could run, and nothing imported
it. Building the tab meant constructing ~60 widgets for a screen the user could
never see.

The backend (``src/aim_system/MagnetTrigger.py`` and the ``magnet_*`` config
keys) is untouched and still functional through the trigger pipeline. Only this
presentation layer is gone.

``build_magnet_trigger_tab`` is kept as a redirect shim for one release so saved
layouts or external scripts that import it do not break.
"""

from __future__ import annotations


RETIRED_MESSAGE = (
    "Magnet Trigger has no dedicated tab in v2.1.0; its settings live in the "
    "Combat pipeline. The function redirects to the Combat tab."
)


def build_magnet_trigger_tab(app):
    """Redirect to the Combat tab (Magnet Trigger UI was retired)."""
    try:
        app._show_magnet_trigger_tab()
    except Exception:
        app._show_aimbot_tab()
    return None


__all__ = ["build_magnet_trigger_tab", "RETIRED_MESSAGE"]
