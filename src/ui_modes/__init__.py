"""UI mode layouts.

``simple_dashboard`` is imported lazily by ``src.ui`` (inside the builder) so this
package stays cheap to import and free of an import cycle.
"""

__all__ = ["build_simple_dashboard", "refresh_simple_dashboard"]


def build_simple_dashboard(app, parent):
    from src.ui_modes.simple_dashboard import build_simple_dashboard as _build

    return _build(app, parent)


def refresh_simple_dashboard(app, changed=None):
    from src.ui_modes.simple_dashboard import refresh_simple_dashboard as _refresh

    return _refresh(app, changed)
