"""Safe Profile Diff & Pinned Quick-Profile Manager."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Tuple


@dataclass(frozen=True)
class ProfileDiff:
    """Categorized differences between active config and a candidate profile."""

    aim_changes: Tuple[Tuple[str, Any, Any], ...]
    system_changes: Tuple[Tuple[str, Any, Any], ...]

    @property
    def total_changes(self) -> int:
        return len(self.aim_changes) + len(self.system_changes)


def compute_profile_diff(
    current_config: Any,
    target_dict: Dict[str, Any],
    aim_keys: Iterable[str],
) -> ProfileDiff:
    """Split profile differences into safe Aim-only keys vs System/Hardware/HSV keys."""
    aim_key_set = set(aim_keys)
    aim_changes: List[Tuple[str, Any, Any]] = []
    system_changes: List[Tuple[str, Any, Any]] = []

    important_system_keys = {
        "capture_mode",
        "udp_ip",
        "udp_port",
        "color",
        "custom_hsv_min_h",
        "custom_hsv_min_s",
        "custom_hsv_min_v",
        "custom_hsv_max_h",
        "custom_hsv_max_s",
        "custom_hsv_max_v",
        "mouse_method",
        "com_port",
        "net_ip",
        "net_port",
        "target_fps",
    }

    for k, new_val in target_dict.items():
        if not hasattr(current_config, k):
            continue
        cur_val = getattr(current_config, k)
        if cur_val == new_val:
            continue
        if k in aim_key_set:
            aim_changes.append((k, cur_val, new_val))
        elif k in important_system_keys:
            system_changes.append((k, cur_val, new_val))

    return ProfileDiff(
        aim_changes=tuple(aim_changes),
        system_changes=tuple(system_changes),
    )


def normalize_pinned_profiles(raw_list: Any, available_names: List[str], max_slots: int = 6) -> List[str]:
    """Keep valid, unique pinned profile names up to max_slots."""
    avail_set = set(available_names)
    pinned: List[str] = []
    if isinstance(raw_list, (list, tuple)):
        for name in raw_list:
            s = str(name or "").strip()
            if s and s in avail_set and s not in pinned:
                pinned.append(s)
            if len(pinned) >= max_slots:
                break
    return pinned
