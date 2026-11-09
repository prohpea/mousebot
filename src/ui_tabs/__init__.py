"""UI tab modules package.

Flick V2 and Calibration are built here so ``ui.py`` only orchestrates: it keeps
the nav, the scheduler and the config plumbing, and calls these builders.
"""

from .calibration_tab import (
    build_flick_calibration_card,
    clear_measurement,
    fit_and_save,
    refresh_calibration_card,
    apply_valorant_scale,
    record_sample,
)
from .flick_tab import (
    build_diagnostics,
    build_flick_panel,
    build_flick_readouts,
    build_flick_v2_tab,
    build_channel_sliders,
    copy_diagnostics_payload,
    refresh_diagnostics,
    refresh_flick_readouts,
    refresh_flick_summary,
)

__all__ = [
    "build_channel_sliders",
    "build_diagnostics",
    "build_flick_calibration_card",
    "build_flick_panel",
    "build_flick_readouts",
    "build_flick_v2_tab",
    "apply_valorant_scale",
    "clear_measurement",
    "copy_diagnostics_payload",
    "fit_and_save",
    "record_sample",
    "refresh_calibration_card",
    "refresh_diagnostics",
    "refresh_flick_readouts",
    "refresh_flick_summary",
]
