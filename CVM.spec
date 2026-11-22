# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.building.splash import Splash
from PyInstaller.utils.hooks import collect_all


class ProgressSplash(Splash):
    """Splash screen with live progress bar and percentage instead of raw DLL names."""

    def __init__(self, image_file, binaries, datas, total_files=500, **kwargs):
        self._total_files = max(int(total_files), 1)
        super().__init__(image_file, binaries, datas, **kwargs)

    def generate_script(self):
        script = f"""proc _ipc_server {{channel clientaddr clientport}} {{
    set client_name [format <%s:%d> $clientaddr $clientport]
    chan configure $channel \\
        -buffering none \\
        -encoding utf-8 \\
        -eofchar \\x04 \\
        -translation cr
    chan event $channel readable [list _ipc_caller $channel $client_name]
}}
proc _ipc_caller {{channel client_name}} {{
    chan gets $channel cmd
    if {{[chan eof $channel]}} {{
        chan close $channel
        exit
    }} elseif {{![chan blocked $channel]}} {{
        if {{[string match "update_text*" $cmd]}} {{
            global status_text
            set first [expr {{[string first "(" $cmd] + 1}}]
            set last [expr {{[string last ")" $cmd] - 1}}]
            set status_text [string range $cmd $first $last]
        }}
    }}
}}
set server_socket [socket -server _ipc_server -myaddr localhost 0]
set server_port [fconfigure $server_socket -sockname]
set env(_PYI_SPLASH_IPC) [lindex $server_port 2]
image create photo splash_image
splash_image put $_image_data
unset _image_data
set total_files {self._total_files}
set loaded_files 0
set current_pct 2
proc update_progress {{canvas _var - -}} {{
    upvar $_var val
    global total_files loaded_files current_pct
    if {{[string match "STAGE:*" $val]}} {{
        set parts [split $val ":"]
        set pct [lindex $parts 1]
        set label [join [lrange $parts 2 end] ":"]
        if {{[string is integer -strict $pct] && $pct > $current_pct}} {{
            set current_pct $pct
        }}
        $canvas itemconfigure status_lbl -text $label
    }} else {{
        incr loaded_files
        set pct [expr {{int(4 + (82.0 * $loaded_files) / $total_files)}}]
        if {{$pct > 86}} {{ set pct 86 }}
        if {{$pct > $current_pct}} {{
            set current_pct $pct
        }}
        $canvas itemconfigure status_lbl -text "Extracting runtime..."
    }}
    set fill_x [expr {{32 + int(376.0 * $current_pct / 100.0)}}]
    $canvas coords bar_fill 32 184 $fill_x 190
    $canvas itemconfigure pct_lbl -text "${{current_pct}}%"
}}
package require Tk
set image_width [image width splash_image]
set image_height [image height splash_image]
if {{[info exists _pyi_screen_geometry]}} {{
    set display_x $_pyi_screen_geometry(x)
    set display_y $_pyi_screen_geometry(y)
    set display_width $_pyi_screen_geometry(width)
    set display_height $_pyi_screen_geometry(height)
}} else {{
    set display_x 0
    set display_y 0
    set display_width [winfo screenwidth .]
    set display_height [winfo screenheight .]
}}
set x_position [expr {{int($display_x + 0.5*($display_width - $image_width))}}]
set y_position [expr {{int($display_y + 0.5*($display_height - $image_height))}}]
frame .root
canvas .root.canvas \\
    -width $image_width \\
    -height $image_height \\
    -borderwidth 0 \\
    -highlightthickness 0
.root.canvas create image \\
    [expr {{$image_width / 2}}] \\
    [expr {{$image_height / 2}}] \\
    -image splash_image
font create statusFont -family Consolas -size 9
font create pctFont -family Consolas -size 9 -weight bold
.root.canvas create rectangle 32 184 408 190 -fill #222222 -outline #2E2E2E -width 1
.root.canvas create rectangle 32 184 40 190 -fill #FFFFFF -outline "" -tag bar_fill
.root.canvas create text 32 176 -fill #A0A0A0 -font statusFont -anchor sw -tag status_lbl -text "Loading CVM..."
.root.canvas create text 408 176 -fill #FFFFFF -font pctFont -anchor se -tag pct_lbl -text "2%"
trace add variable status_text write [list update_progress .root.canvas]
wm attributes . -transparentcolor magenta
.root.canvas configure -background magenta
pack .root
grid .root.canvas -column 0 -row 0 -columnspan 1 -rowspan 2
wm overrideredirect . 1
wm geometry . +${{x_position}}+${{y_position}}
wm attributes . -topmost 1
raise .
"""
        with open(self.script_name, "w", encoding="utf-8") as script_file:
            script_file.write(script)
        return script


def _is_test_entry(name: str) -> bool:
    norm = str(name).replace("\\", "/").lower()
    if "/tests/" in f"/{norm}/":
        return True
    return ".tests." in norm or norm.endswith(".tests")


datas = [
    ("ABCurves", "ABCurves"),
    ("themes", "themes"),
    ("locales", "locales"),
    ("cvm.jpg", "."),
    ("version.json", "."),
    ("configs/default_cvm.json", "configs"),
]

binaries = [
    ("src/utils/mouse/API/kmboxA/pyd/kmA.cp311-win_amd64.pyd", "src/utils/mouse/API/kmboxA/pyd"),
    ("src/utils/mouse/API/Net/dll/kmNet.cp311-win_amd64.pyd", "src/utils/mouse/API/Net/dll"),
]

hiddenimports = [
    "PIL._tkinter_finder",
    "serial",
    "serial.tools",
    "serial.tools.list_ports",
    "serial.tools.list_ports_windows",
    "turbojpeg",
    "mss",
    "mss.windows",
    "requests",
    "packaging",
    "packaging.version",
    "darkdetect",
    "cv2",
    "numpy",
    "src.utils.mouse.ArduinoAPI",
    "src.utils.mouse.DHZAPI",
    "src.utils.mouse.FerrumAPI",
    "src.utils.mouse.KmboxAAPI",
    "src.utils.mouse.MakAPI",
    "src.utils.mouse.MakV2",
    "src.utils.mouse.MakV2Binary",
    "src.utils.mouse.MakcuControllerAPI",
    "src.utils.mouse.MakxdMakAPI",
    "src.utils.mouse.MediusAPI",
    "src.utils.mouse.NetAPI",
    "src.utils.mouse.SendInputAPI",
    "src.utils.mouse.SerialAPI",
    "src.utils.mouse.keycodes",
    "src.utils.mouse.state",
    "src.capture.CaptureCard",
    "src.capture.CaptureCardGStreamer",
    "src.capture.OBS_UDP",
    "src.capture.mss_capture",
    "src.capture.ndi",
    "src.capture.obs_teleport_capture",
    "src.aim_system.Bezier",
    "src.aim_system.NCAF",
    "src.aim_system.RCS",
    "src.aim_system.abcurves_controller",
    "src.aim_system.anti_smoke_detector",
    "src.aim_system.mode_abcurves",
    "src.aim_system.mode_bezier",
    "src.aim_system.mode_dispatcher",
    "src.aim_system.mode_flick",
    "src.aim_system.mode_ncaf",
    "src.aim_system.mode_normal",
    "src.aim_system.mode_pid",
    "src.aim_system.mode_silent",
    "src.aim_system.mode_windmouse",
    "src.aim_system.normal",
    "src.aim_system.silent",
    "src.aim_system.target_smoother",
    "src.aim_system.windmouse_smooth",
]

for pkg in ("customtkinter", "cyndilib", "medius", "numba", "llvmlite", "abcurves_native"):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg)
    datas += [item for item in pkg_datas if not _is_test_entry(item[1])]
    binaries += [item for item in pkg_binaries if not _is_test_entry(item[1])]
    hiddenimports += [m for m in pkg_hidden if not _is_test_entry(m)]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["torch", "onnxruntime", "pandas", "matplotlib", "pytest", "IPython", "scipy", "PIL._avif", "numba.tests", "llvmlite.tests"],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

splash = ProgressSplash(
    "themes/icon/cvm_splash.png",
    binaries=a.binaries,
    datas=a.datas,
    total_files=max(len(a.binaries) + len(a.datas), 1),
    text_pos=(32, 186),
    text_font="Consolas",
    minify_script=False,
    always_on_top=True,
    center="primary",
)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    splash,
    splash.binaries,
    [],
    name="CVM",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="themes/icon/cvm.ico",
)
