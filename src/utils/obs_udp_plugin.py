"""OBS xUDP plugin integration helpers for the AI Detection engine.

This module is deliberately stdlib-only (no GUI toolkit, no OpenCV, no capture
backend) so it can be unit tested without a window, without OBS and without
opening a socket. It answers four questions the UI and the capture layer keep
asking:

1. Is the ``obs-color-correction.dll`` xUDP plugin installed on this machine, and
   can we run the bundled installer if it is not?
2. Which OBS filter preset should the user apply for the *currently selected*
   ONNX model? The shipped colour-correction chain (purple boost + contrast
   crush) is tuned for HSV Colorbot; a YOLO model was trained on natural game
   frames, so the AI preset *inverts* those switches.
3. Should ``udp_fov`` crop be skipped because it would cut the frame smaller than
   the model tensor (216 < 320), which truncates players and adds upscale blur
   without making inference any faster?
4. What is the live state of the UDP stream (fps, decode fps, latency, fragment
   drops) and which warnings should the HUD show?
"""
import os
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

# --- Shipped plugin layout ---------------------------------------------------

OBS_PLUGIN_DLL = "obs-color-correction.dll"
TURBOJPEG_DLL = "turbojpeg.dll"
DEFAULT_OBS_DIR = r"C:\Program Files\obs-studio"
DEFAULT_TURBO_DIR = r"C:\libjpeg-turbo64\bin"
PLUGIN_BUNDLE_DIRNAME = "OBS-xUDP-Plugin"

# The plugin guide is written around 144 FPS: 6.94 ms per frame, which leaves
# headroom for the software colour pass and keeps fragment reassembly stable.
AI_OBS_FPS = 144
# 80 is ~7-8 KB/frame at 320x320; 82-85 is still small and keeps edges crisp.
# This constant is the single source of truth: the preset, its text form and the
# tests all read it instead of repeating a second (unused) range tuple.
AI_OBS_JPEG_QUALITY = 82

# Colorbot HSV runs on the *same* OBS xUDP plugin but with the opposite colour
# chain: the purple boost / contrast crush is the preprocessing the HSV mask was
# tuned on, so the preset below keeps it ON. 200 FPS is the 5.0 ms track budget;
# OBS may cap the stream at 144 when the plugin or the game timer locks it.
COLORBOT_OBS_FPS = 200
# 80 keeps a 320x320 frame small enough to fit one MTU-friendly chunk on LAN,
# which matters at 200 FPS where fragment reassembly has only ~5 ms to finish.
COLORBOT_OBS_JPEG_QUALITY = 80
COLORBOT_OBS_CONTRAST_CRUSH = 0.85
# PC1 keeps its native canvas and crops the 1:1 square out of it (see the AI
# preset for why shrinking the whole canvas is wrong).
OBS_CANVAS_WIDTH = 1920
OBS_CANVAS_HEIGHT = 1080

# Tensor edge length per model file. Filename first (no ONNX load for the UI),
# detector introspection only as a fallback.
AI_MODEL_PRESETS = {
    "my_yolo_model.onnx": 320,
    "valorant_detector.onnx": 320,
    "my_yolo_model_640.onnx": 640,
}
AI_MODEL_DEFAULT_SIZE = 640

# A stream is considered starved when no datagram arrived for this long.
STARVED_AFTER_S = 2.0


def _isfile(path: str) -> bool:
    try:
        return bool(path) and os.path.isfile(path)
    except Exception:
        return False


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        if isinstance(value, bool):
            return default
        return float(value)
    except Exception:
        return default


def _as_int(value: Any, default: int = 0) -> int:
    try:
        if isinstance(value, bool):
            return default
        return int(value)
    except Exception:
        return default


def _as_str(value: Any, default: str = "") -> str:
    try:
        if value is None:
            return default
        if isinstance(value, (bytes, bytearray)):
            return value.decode("utf-8", "ignore")
        return str(value)
    except Exception:
        return default


def _config_value(config_module: Any, key: str, default: Any) -> Any:
    """Read a config key without ever raising (MagicMock friendly)."""
    try:
        source = config_module
        if source is None:
            from src.utils.config import config as source  # local import: pure module
        return getattr(source, key, default)
    except Exception:
        return default


# --- Plugin presence / installer --------------------------------------------


def resolve_plugin_root() -> str:
    """Path of the ``OBS-xUDP-Plugin`` folder shipped next to this checkout.

    The bundle always lives beside the repository (``../OBS-xUDP-Plugin``), so
    there is no override knob here: an ``obs_udp_plugin_root`` config key never
    existed and a unit-test-only parameter is a source of truth that production
    can never reach. Callers that need another location pass ``plugin_root`` to
    :func:`check_plugin_status` / :func:`build_install_command` explicitly.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(os.path.dirname(here))
    return os.path.join(os.path.dirname(repo_root), PLUGIN_BUNDLE_DIRNAME)


def check_plugin_status(plugin_root: Optional[str] = None,
                        obs_dir: Optional[str] = None,
                        turbo_dir: Optional[str] = None) -> Dict[str, Any]:
    """Report whether the xUDP plugin (and TurboJPEG) is where OBS looks for it."""
    root = plugin_root or resolve_plugin_root()
    obs = obs_dir or DEFAULT_OBS_DIR
    turbo = turbo_dir or DEFAULT_TURBO_DIR

    obs_dll_path = os.path.join(obs, "obs-plugins", "64bit", OBS_PLUGIN_DLL)
    obs_turbo_path = os.path.join(obs, "bin", "64bit", TURBOJPEG_DLL)
    turbo_lib_path = os.path.join(turbo, TURBOJPEG_DLL)

    bundle_obs_path = os.path.join(root, "obs-plugins", "64bit", OBS_PLUGIN_DLL)
    bundle_turbo_path = os.path.join(root, "bin", "64bit", TURBOJPEG_DLL)
    bundle_ps1 = os.path.join(root, "install.ps1")
    bundle_bat = os.path.join(root, "install.bat")

    obs_dll = _isfile(obs_dll_path)
    obs_turbojpeg = _isfile(obs_turbo_path)
    turbo_lib_dll = _isfile(turbo_lib_path)

    installer = ""
    if _isfile(bundle_ps1):
        installer = "install.ps1"
    elif _isfile(bundle_bat):
        installer = "install.bat"

    bundle_available = _isfile(bundle_obs_path) and _isfile(bundle_turbo_path) and bool(installer)

    missing: List[str] = []
    if not obs_dll:
        missing.append("obs-plugins/64bit/%s in %s" % (OBS_PLUGIN_DLL, obs))
    if not obs_turbojpeg:
        missing.append("bin/64bit/%s in %s" % (TURBOJPEG_DLL, obs))
    if not turbo_lib_dll:
        missing.append("%s in %s" % (TURBOJPEG_DLL, turbo))
    if not installer:
        missing.append("install.ps1 or install.bat in %s" % root)

    notes: List[str] = []
    if obs_dll and not turbo_lib_dll:
        notes.append(
            "Plugin DLL present but %s is not in %s: decode falls back to OpenCV "
            "(~2-3 ms slower per frame)." % (TURBOJPEG_DLL, turbo)
        )
    if not obs_dll and bundle_available:
        notes.append("Bundle found: run the installer (OBS Studio must be closed).")
    if obs_dll and obs_turbojpeg and turbo_lib_dll:
        notes.append("Plugin installed for OBS Studio.")
    if sys.platform != "win32":
        notes.append("This integration targets Windows 64-bit OBS Studio.")

    return {
        "plugin_root": root,
        "obs_dir": obs,
        "turbo_dir": turbo,
        "installed": bool(obs_dll and obs_turbojpeg and turbo_lib_dll),
        "bundle_available": bool(bundle_available),
        "obs_dll": bool(obs_dll),
        "obs_turbojpeg": bool(obs_turbojpeg),
        "turbo_lib_dll": bool(turbo_lib_dll),
        "installer": installer,
        "missing": missing,
        "notes": notes,
        "paths": {
            "obs_dll": obs_dll_path,
            "obs_turbojpeg": obs_turbo_path,
            "turbo_lib_dll": turbo_lib_path,
            "bundle": root,
        },
    }


def build_install_command(plugin_root: Optional[str], elevated: bool = False) -> Optional[List[str]]:
    """Installer command for the bundled bundle, or ``None`` when it is missing.

    ``install.ps1`` writes into ``Program Files`` and stops ``obs64`` first, so it
    needs administrator rights; ``elevated=True`` re-launches the same script via
    ``Start-Process -Verb RunAs`` (the user still sees the UAC prompt).
    """
    root = plugin_root or resolve_plugin_root()
    if not root:
        return None
    ps1 = os.path.join(root, "install.ps1")
    bat = os.path.join(root, "install.bat")
    if _isfile(ps1):
        inner = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps1]
    elif _isfile(bat):
        # A .bat is not a PE image: CreateProcess needs cmd.exe to interpret it.
        inner = ["cmd", "/c", bat]
    else:
        return None
    if not elevated:
        return inner
    quoted_dir = "'%s'" % root.replace("'", "''")
    argument_list = ",".join("'%s'" % part.replace("'", "''") for part in inner[1:])
    return [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        "Start-Process -FilePath '%s' -ArgumentList %s -WorkingDirectory %s -Verb RunAs -Wait"
        % (inner[0].replace("'", "''"), argument_list, quoted_dir),
    ]


def wait_for_install(plugin_root: Optional[str] = None,
                     obs_dir: Optional[str] = None,
                     turbo_dir: Optional[str] = None,
                     timeout: float = 5.0,
                     interval: float = 0.5) -> Dict[str, Any]:
    """Poll :func:`check_plugin_status` until the DLLs really exist.

    ``Start-Process -Verb RunAs`` hands control back as soon as the elevated
    process starts (or as soon as the user dismisses UAC), and the UAC prompt can
    easily outlive a zero exit code. So the only trustworthy completion signal is
    the install state on disk; the UI calls this after launching the installer
    instead of claiming success from the launcher's exit code.
    """
    deadline = time.monotonic() + max(0.0, float(timeout))
    status: Dict[str, Any] = {}
    while True:
        status = check_plugin_status(plugin_root, obs_dir, turbo_dir)
        if status.get("installed") or time.monotonic() >= deadline:
            return status
        time.sleep(max(0.05, float(interval)))


def run_plugin_installer(plugin_root: Optional[str] = None,
                         elevated: bool = False,
                         dry_run: bool = False,
                         timeout: int = 180) -> Tuple[bool, str]:
    """Run the bundled installer. ``dry_run`` returns the command for tests/UI."""
    root = plugin_root or resolve_plugin_root()
    command = build_install_command(root, elevated=elevated)
    if not command:
        return False, "install.ps1 / install.bat not found in %s" % root
    if dry_run:
        return True, " ".join(command)
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            timeout=int(timeout),
            capture_output=True,
            text=True,
        )
    except Exception as exc:  # pragma: no cover - subprocess/platform failures
        return False, "%s: %s" % (type(exc).__name__, exc)
    output = "%s%s" % (completed.stdout or "", completed.stderr or "")
    output = output.strip()
    if completed.returncode == 0:
        return True, output or "installer finished"
    return False, output or ("installer exit code %d" % int(completed.returncode))


# --- AI filter preset --------------------------------------------------------


def _model_basename(model_path: Any) -> str:
    try:
        text = _as_str(model_path).replace("\\", "/").strip()
        return os.path.basename(text).lower()
    except Exception:
        return ""


def preset_input_size(model_path: Any,
                      detector_input_size: Any = None) -> Tuple[int, str]:
    """Square preset edge for the selected model, plus the reason it was chosen."""
    name = _model_basename(model_path)
    if name in AI_MODEL_PRESETS:
        return AI_MODEL_PRESETS[name], "model_table"
    stem = name.rsplit(".", 1)[0] if "." in name else name
    if "_640" in stem:
        return 640, "model_name_640"
    size = detector_input_size
    if isinstance(size, (tuple, list)) and size:
        size = size[0]
    try:
        if size is not None and not isinstance(size, bool):
            value = int(size)
            if value > 0:
                return value, "detector_input_size"
    except Exception:
        pass
    return AI_MODEL_DEFAULT_SIZE, "unknown_model_default_640"


def build_ai_obs_filter_preset(model_path: Any,
                               detector_input_size: Any = None,
                               target_ip: Optional[str] = None,
                               target_port: Optional[Any] = None,
                               config_module: Any = None) -> Dict[str, Any]:
    """OBS filter values for the AI engine (natural colours, no HSV boost).

    The returned ``width``/``height`` are the size of the *Crop/Pad* region the
    PC1 scene must send, not the OBS canvas: the scene stays 1920x1080 and a
    1:1 square around the crosshair is cropped out of it. The matching filter
    order (Crop/Pad above Color Correction) is spelled out by
    :func:`format_ai_obs_filter_preset`.
    """
    size, size_reason = preset_input_size(model_path, detector_input_size)
    if target_ip is None:
        target_ip = _as_str(_config_value(config_module, "udp_ip", "0.0.0.0"), "0.0.0.0")
    if target_port is None:
        target_port = _as_str(_config_value(config_module, "udp_port", "3110"), "3110")

    warnings: List[str] = []
    if size_reason == "unknown_model_default_640":
        warnings.append(
            "Unknown model file: assuming a %dx%d tensor. Adjust Output Resolution "
            "if the ONNX input differs." % (size, size)
        )
    if _as_str(target_ip).strip() in ("", "0.0.0.0", "127.0.0.1"):
        warnings.append(
            "Target IP is a bind address, not a peer: put the LAN IP of the "
            "receiver PC in the OBS filter."
        )

    return {
        "model": _as_str(model_path),
        "width": int(size),
        "height": int(size),
        "fps": int(AI_OBS_FPS),
        "jpeg_quality": int(AI_OBS_JPEG_QUALITY),
        "color_enhancement": False,
        "adaptive_enhancement": False,
        "enhance_purple_tones": False,
        "enhancement_strength": 1.0,
        "reduce_background_colors": False,
        "shadow_rejection": False,
        "contrast_crush": 0.0,
        "outline_thickening": False,
        "target_ip": _as_str(target_ip, "0.0.0.0"),
        "target_port": _as_str(target_port, "3110"),
        "size_reason": size_reason,
        "warnings": warnings,
    }


def format_ai_obs_filter_preset(preset: Dict[str, Any]) -> str:
    """Clipboard/OBS-ready text block for the PC1 (OBS) filter chain.

    States the filter order (Crop/Pad 1:1 above Color Correction) as well as the
    three switches that MUST be off. The Crop/Pad step exists because the scene
    is 1920x1080: shrinking the whole canvas to 320x320 resamples every pixel and
    destroys distant head detail, while cropping a 1:1 square keeps it.
    """
    preset = preset or {}
    width = _as_int(preset.get("width"), AI_MODEL_DEFAULT_SIZE)
    height = _as_int(preset.get("height"), width)
    # Crop offsets on a 1920x1080 canvas, derived from the preset size so a
    # 640x640 preset reports the right numbers instead of a hard-coded 320 pair.
    canvas_w, canvas_h = 1920, 1080
    pad_x = max(0, int((canvas_w - width) / 2))
    pad_y = max(0, int((canvas_h - height) / 2))
    lines = [
        "OBS FILTER PRESET - AI DETECTION (NATURAL COLOURS)",
        "Model: %s" % _as_str(preset.get("model"), "(none)"),
        "Output Resolution: %dx%d (1:1)" % (width, height),
        "Max Network FPS: %d" % _as_int(preset.get("fps"), AI_OBS_FPS),
        "JPEG Quality: %d" % _as_int(preset.get("jpeg_quality"), AI_OBS_JPEG_QUALITY),
        "Target IP: %s" % _as_str(preset.get("target_ip"), "0.0.0.0"),
        "Target Port: %s" % _as_str(preset.get("target_port"), "3110"),
        "",
        "PC1 (OBS / STREAMING PC) - FILTER ORDER (top to bottom):",
        "1. Crop/Pad  ->  crop a %dx%d (1:1) square around the crosshair" % (width, height),
        "   Canvas %dx%d: Left %d, Right %d, Top %d, Bottom %d"
        % (canvas_w, canvas_h, pad_x, pad_x, pad_y, pad_y),
        "   (formula: (%d - %d) / 2 and (%d - %d) / 2; adjust for another canvas)"
        % (canvas_w, width, canvas_h, height),
        "2. Color Correction (obs-color-correction.dll) -> the switches below",
        "   Crop/Pad MUST stay ABOVE Color Correction in the filter list.",
        "   Do NOT set the OBS canvas/output to %dx%d: that rescales the whole"
        % (width, height),
        "   %dx%d scene and destroys distant head detail. Crop the 1:1 region instead."
        % (canvas_w, canvas_h),
        "",
        "Color Enhancement: OFF",
        "Adaptive Enhancement: OFF",
        "Enhance Purple Tones: OFF",
        "Enhancement Strength: %.2f" % _as_float(preset.get("enhancement_strength"), 1.0),
        "Reduce Background Colors: OFF",
        "Shadow Rejection: OFF",
        "Contrast Crush: %.2f" % _as_float(preset.get("contrast_crush"), 0.0),
        "Outline Thickening: OFF",
        "",
        "QUAN TRONG: TAT Color Enhancement / Reduce Background Colors /",
        "Contrast Crush = 0 de model AI nhan mau tu nhien.",
        (
            "The purple / dimmed chain is tuned for HSV Colorbot ([120,160] hue). "
            "A YOLO model was trained on natural game frames, so boosting purple "
            "and crushing contrast shifts the input distribution: skin and armour "
            "detail disappear and confidence drops."
        ),
    ]
    for warning in preset.get("warnings") or []:
        lines.append("WARNING: %s" % warning)
    return "\n".join(lines)


# --- Colorbot (HSV) filter preset -------------------------------------------


def build_colorbot_obs_filter_preset(target_ip: Optional[str] = None,
                                     target_port: Optional[Any] = None,
                                     fps: int = COLORBOT_OBS_FPS,
                                     width: int = 320,
                                     height: int = 320,
                                     config_module: Any = None) -> Dict[str, Any]:
    """OBS filter values for the HSV Colorbot engine at 200 FPS.

    This is the mirror image of :func:`build_ai_obs_filter_preset`: the purple
    boost is the whole point, because the HSV mask in ``detection.py`` looks for
    hue ``[120,160]`` and the shipped ``obs-color-correction.dll`` chain forces
    enemy outlines into exactly that band. The returned ``width``/``height`` are
    the 1:1 *Crop/Pad* region PC1 sends, not the OBS canvas.
    """
    if target_ip is None:
        target_ip = _as_str(_config_value(config_module, "udp_ip", "0.0.0.0"), "0.0.0.0")
    if target_port is None:
        target_port = _as_str(_config_value(config_module, "udp_port", "3110"), "3110")

    out_width = max(1, _as_int(width, 320))
    out_height = max(1, _as_int(height, 320))
    max_fps = max(1, _as_int(fps, COLORBOT_OBS_FPS))

    warnings: List[str] = []
    if _as_str(target_ip).strip() in ("", "0.0.0.0", "127.0.0.1"):
        warnings.append(
            "Target IP is a bind address, not a peer: put the LAN IP of the "
            "receiver PC in the OBS filter."
        )

    return {
        "width": int(out_width),
        "height": int(out_height),
        "fps": int(max_fps),
        "jpeg_quality": int(COLORBOT_OBS_JPEG_QUALITY),
        "color_enhancement": True,
        "adaptive_enhancement": False,
        "enhance_purple_tones": True,
        "enhancement_strength": 1.0,
        "reduce_background_colors": True,
        "shadow_rejection": False,
        "contrast_crush": float(COLORBOT_OBS_CONTRAST_CRUSH),
        "outline_thickening": True,
        "target_ip": _as_str(target_ip, "0.0.0.0"),
        "target_port": _as_str(target_port, "3110"),
        "warnings": warnings,
    }


def format_colorbot_obs_filter_preset(preset: Dict[str, Any]) -> str:
    """Clipboard/OBS-ready text block for the PC1 Colorbot (HSV) filter chain.

    The order matters: Crop/Pad 1:1 must sit *above* Color Correction so the
    purple boost runs on the 320x320 crop instead of the full 1920x1080 canvas
    (same reason as the AI preset, opposite colour switches).
    """
    preset = preset or {}
    width = max(1, _as_int(preset.get("width"), 320))
    height = max(1, _as_int(preset.get("height"), width))
    # Same derivation as the AI preset: the PC1 scene is 1920x1080 and only the
    # 1:1 centre square is cropped, so 320x320 -> 800/380 and 640x640 -> 640/220.
    canvas_w, canvas_h = OBS_CANVAS_WIDTH, OBS_CANVAS_HEIGHT
    pad_x = max(0, int((canvas_w - width) / 2))
    pad_y = max(0, int((canvas_h - height) / 2))
    fps = _as_int(preset.get("fps"), COLORBOT_OBS_FPS)
    lines = [
        "OBS FILTER PRESET - COLORBOT HSV (PURPLE BOOST) @ %d FPS" % fps,
        "Target IP: %s" % _as_str(preset.get("target_ip"), "0.0.0.0"),
        "Target Port: %s" % _as_str(preset.get("target_port"), "3110"),
        "Output Resolution: %dx%d (1:1)" % (width, height),
        "FOV (Crop Size) = %d" % width,
        "Max Network FPS: %d" % fps,
        "   (if the game or the plugin locks the timer at 144, set Max Network FPS = 144)",
        "JPEG Quality: %d" % _as_int(preset.get("jpeg_quality"), COLORBOT_OBS_JPEG_QUALITY),
        "",
        "PC1 (OBS / STREAMING PC) - FILTER ORDER (top to bottom):",
        "1. Crop/Pad  ->  Relative = ON, crop a %dx%d (1:1) square around the crosshair"
        % (width, height),
        "   Canvas %dx%d: Left %d, Right %d, Top %d, Bottom %d"
        % (canvas_w, canvas_h, pad_x, pad_x, pad_y, pad_y),
        "   (formula: (%d - %d) / 2 and (%d - %d) / 2; adjust for another canvas)"
        % (canvas_w, width, canvas_h, height),
        "2. Color Correction (obs-color-correction.dll) -> the switches below",
        "   Crop/Pad MUST stay ABOVE Color Correction in the filter list.",
        "",
        "Color Correction switches (all ON for the HSV [120,160] hue band, Adaptive/Shadow OFF):",
        "Color Enhancement: ON",
        "Adaptive Enhancement: OFF",
        "Enhance Purple Tones: ON",
        "Reduce Background Colors: ON",
        "Shadow Rejection: OFF",
        "Contrast Crush: %.2f" % _as_float(preset.get("contrast_crush"), COLORBOT_OBS_CONTRAST_CRUSH),
        "Outline Thickening: ON",
        "",
        "GHI CHU: day la chuoi nguoc voi preset AI Detection - Colorbot HSV can",
        "tang tim / nen nen / dap tuong phan de mask bat outline, khong phai mau tu nhien.",
    ]
    for warning in preset.get("warnings") or []:
        lines.append("WARNING: %s" % warning)
    return "\n".join(lines)


# --- UDP crop guard ----------------------------------------------------------


def _is_ai_engine(config_module: Any) -> bool:
    engine = _as_str(_config_value(config_module, "detection_engine", "")).strip().lower()
    if engine in ("ai_detection", "ai"):
        return True
    if engine in ("colorbot", "hsv"):
        return False
    # Same convention as Config.from_dict: a missing key falls back to the boolean.
    return bool(_config_value(config_module, "ai_detection_enabled", False))


def udp_crop_decision(config_module: Any,
                      fov: Optional[Any] = None,
                      model_path: Optional[Any] = None,
                      mode: str = "UDP") -> Dict[str, Any]:
    """Decide whether the UDP centre crop must be skipped for the AI engine.

    The crop formula is ``_crop_frame_center(frame, fov, fov)``, i.e. the visible
    edge is ``2 * udp_fov``. A model that consumes 320x320 cannot see a 216x216
    crop without upscaling, and it is *not* faster (the tensor is fixed), so the
    guard skips the crop while leaving HSV Colorbot byte-identical to before.
    """
    mode_name = _as_str(mode, "UDP").strip() or "UDP"
    if fov is None:
        fov = _config_value(config_module, "udp_fov", 320)
    half_px = _as_int(fov, 320)
    total_px = half_px * 2

    if model_path is None:
        model_path = _config_value(config_module, "ai_model_path", "")

    min_px = _as_int(_config_value(config_module, "ai_udp_min_crop_px", 0), 0)
    if min_px <= 0:
        min_px = int(preset_input_size(model_path)[0])

    decision = {
        "mode": mode_name,
        "enabled": False,
        "half_px": half_px,
        "total_px": total_px,
        "min_px": int(min_px),
        "ai_engine": bool(_is_ai_engine(config_module)),
        "model": _as_str(model_path),
        "bypass": False,
        "reason": "crop_disabled",
    }

    if mode_name.upper() != "UDP":
        return decision
    if not bool(_config_value(config_module, "udp_fov_enabled", False)):
        return decision
    decision["enabled"] = True

    if not bool(_config_value(config_module, "ai_udp_bypass_tiny_crop", True)):
        decision["reason"] = "option_off"
        return decision
    if not decision["ai_engine"]:
        decision["reason"] = "engine_colorbot"
        return decision
    if half_px > 0 and total_px >= min_px:
        decision["reason"] = "crop_ok"
        return decision

    decision["bypass"] = True
    decision["reason"] = "tiny_crop"
    return decision


def should_bypass_udp_crop(config_module: Any,
                           fov: Optional[Any] = None,
                           model_path: Optional[Any] = None,
                           mode: str = "UDP") -> bool:
    """Thin wrapper around :func:`udp_crop_decision`."""
    return bool(udp_crop_decision(config_module, fov=fov, model_path=model_path, mode=mode).get("bypass"))


# --- Live telemetry ----------------------------------------------------------


def _warning(code: str, message: str) -> Dict[str, str]:
    return {"code": code, "message": message}


def build_udp_telemetry_snapshot(capture: Any,
                                 config_module: Any = None,
                                 plugin_status: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Normalise the UDP receiver state for the HUD.

    ``capture`` is duck-typed (``mode``, ``is_connected()``, ``udp_manager``,
    ``_ip``/``_port``): nothing from ``src.capture`` is imported here, and a
    ``MagicMock`` service degrades to ``{"available": False}`` instead of raising.
    """
    mode_name = _as_str(getattr(capture, "mode", ""), "").strip()
    snapshot: Dict[str, Any] = {
        "available": False,
        "mode": mode_name,
        "connected": False,
        "receiving": False,
        "starved": False,
        "fps": 0.0,
        "decode_fps": 0.0,
        "resolution": None,
        "width": 0,
        "height": 0,
        "receive_ms": 0.0,
        "decode_ms": 0.0,
        "fragment_drops": 0,
        "packet_count": 0,
        "last_packet_age_s": None,
        "endpoint": "",
        "crop": {},
        "warnings": [],
        "summary": "UDP: idle",
    }

    if plugin_status is None:
        try:
            plugin_status = check_plugin_status()
        except Exception:
            plugin_status = None

    try:
        snapshot["crop"] = udp_crop_decision(config_module, mode=mode_name or "UDP")
    except Exception:
        snapshot["crop"] = {}

    if mode_name.upper() != "UDP":
        snapshot["summary"] = "UDP capture not selected (mode: %s)" % (mode_name or "unknown")
        return snapshot

    ip = _as_str(getattr(capture, "_ip", ""), "").strip()
    port = _as_str(getattr(capture, "_port", ""), "").strip()
    if not ip:
        ip = _as_str(getattr(capture, "ip", ""), "").strip()
    if not port:
        port = _as_str(_config_value(config_module, "udp_port", "3110"), "3110")
    snapshot["endpoint"] = "%s:%s" % (ip or "0.0.0.0", port or "3110")

    try:
        snapshot["connected"] = bool(capture.is_connected())
    except Exception:
        snapshot["connected"] = False

    receiver = None
    try:
        manager = getattr(capture, "udp_manager", None)
        if manager is not None:
            receiver = manager.get_receiver()
    except Exception:
        receiver = None

    stats: Dict[str, Any] = {}
    meta: Dict[str, Any] = {}
    if receiver is not None:
        try:
            candidate = receiver.get_performance_stats()
            if isinstance(candidate, dict):
                stats = candidate
        except Exception:
            stats = {}
        try:
            candidate = receiver.get_last_frame_meta()
            if isinstance(candidate, dict):
                meta = candidate
        except Exception:
            meta = {}

    if receiver is not None:
        snapshot["receiving"] = bool(
            stats.get("is_receiving", getattr(receiver, "is_receiving", False))
        )
    snapshot["fps"] = max(0.0, _as_float(stats.get("current_fps", 0.0)))
    snapshot["decode_fps"] = max(0.0, _as_float(stats.get("decoding_fps", 0.0)))
    snapshot["receive_ms"] = max(0.0, _as_float(meta.get("receive_ms", stats.get("receive_delay_ms", 0.0))))
    snapshot["decode_ms"] = max(0.0, _as_float(meta.get("decode_ms", stats.get("decode_delay_ms", 0.0))))
    snapshot["fragment_drops"] = max(0, _as_int(stats.get("fragment_drops", getattr(receiver, "fragment_drops", 0))))
    snapshot["packet_count"] = max(0, _as_int(stats.get("packet_count", getattr(receiver, "packet_count", 0))))
    age = stats.get("last_packet_age_s")
    snapshot["last_packet_age_s"] = None if age is None else max(0.0, _as_float(age))

    width = height = 0
    if receiver is not None:
        try:
            frame = receiver.get_current_frame()
            shape = getattr(frame, "shape", None)
            if shape is not None and len(shape) >= 2:
                height = _as_int(shape[0], 0)
                width = _as_int(shape[1], 0)
        except Exception:
            width = height = 0
    if width > 0 and height > 0:
        snapshot["width"] = width
        snapshot["height"] = height
        snapshot["resolution"] = "%dx%d" % (width, height)

    snapshot["available"] = bool(receiver is not None and (snapshot["connected"] or snapshot["packet_count"] > 0))
    snapshot["starved"] = bool(
        snapshot["connected"]
        and (
            snapshot["packet_count"] <= 0
            or (snapshot["last_packet_age_s"] is not None
                and snapshot["last_packet_age_s"] > STARVED_AFTER_S)
        )
    )

    warnings: List[Dict[str, str]] = []
    if isinstance(plugin_status, dict) and not plugin_status.get("installed"):
        missing = plugin_status.get("missing") or []
        warnings.append(_warning(
            "plugin_missing",
            "OBS xUDP plugin not installed%s"
            % ((": " + "; ".join(_as_str(m) for m in missing[:2])) if missing else ""),
        ))
    if snapshot["connected"] and snapshot["packet_count"] <= 0:
        warnings.append(_warning(
            "no_packets",
            "UDP port %s is bound but no packets arrived: check OBS streaming, the "
            "Windows firewall and that no other instance holds the port." % (port or "?"),
        ))
    if snapshot["starved"]:
        warnings.append(_warning(
            "starved",
            "Stream stalled: %s packets, last packet %s."
            % (
                snapshot["packet_count"],
                "never" if snapshot["last_packet_age_s"] is None
                else "%.1fs ago" % snapshot["last_packet_age_s"],
            ),
        ))
    if snapshot["fragment_drops"] > 0:
        warnings.append(_warning(
            "fragment_drops",
            "%d UDP fragment drop(s): lower OBS JPEG quality or network FPS, or "
            "raise the receive buffer." % snapshot["fragment_drops"],
        ))
    crop = snapshot.get("crop") or {}
    if crop.get("bypass"):
        warnings.append(_warning(
            "tiny_crop_bypassed",
            "AI mode: udp_fov crop skipped (%dpx < %dpx model input) to keep the "
            "player in frame." % (crop.get("total_px", 0), crop.get("min_px", 0)),
        ))
    elif crop.get("reason") == "crop_ok" and crop.get("ai_engine"):
        warnings.append(_warning(
            "crop_active_for_ai",
            "AI mode is cropping the UDP frame to %dpx; detection sees a narrower FOV."
            % crop.get("total_px", 0),
        ))
    snapshot["warnings"] = warnings
    snapshot["summary"] = format_udp_telemetry_line(snapshot)
    return snapshot


def format_udp_telemetry_line(snapshot: Dict[str, Any]) -> str:
    """One compact HUD line; never raises on a partial snapshot."""
    snapshot = snapshot or {}
    if not snapshot.get("available") and not snapshot.get("connected"):
        if snapshot.get("mode") and str(snapshot.get("mode")).upper() != "UDP":
            return "UDP: not selected"
        return "UDP: idle"
    parts = [
        "UDP %s" % _as_str(snapshot.get("endpoint"), "?"),
        "%.0f FPS" % _as_float(snapshot.get("fps"), 0.0),
        "dec %.0f" % _as_float(snapshot.get("decode_fps"), 0.0),
    ]
    resolution = _as_str(snapshot.get("resolution"), "").strip()
    parts.append(resolution if resolution else "no frame")
    parts.append("rx %.1fms" % _as_float(snapshot.get("receive_ms"), 0.0))
    parts.append("dec %.1fms" % _as_float(snapshot.get("decode_ms"), 0.0))
    parts.append("drops %d" % _as_int(snapshot.get("fragment_drops"), 0))
    if snapshot.get("starved"):
        parts.append("STARVED")
    return " | ".join(parts)
